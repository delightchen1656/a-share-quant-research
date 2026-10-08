"""Same V6 strategy, independent asynchronous order/account simulator.

--mode minute requires genuine unadjusted completed-minute bars. Orders first
match the NEXT bar, never a bar already visible to the strategy. OHLC touch and
volume matching is an approximation, NOT exchange queue/5-level reconstruction.
--mode daily-proxy explicitly uses two synthetic opening events, no intraday
claims. It is provided for the repository's existing daily-only history.
"""
from pathlib import Path
from types import SimpleNamespace as NS
import argparse
import copy
import hashlib
import importlib.util
import json
import math
import pandas as pd
import numpy as np

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
OLD = BASE / 'test2_weekly/original_202001'
ENTRY = HERE / 'supermind_baseline2_execution_v6_minute.py'

def mod(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

engine = mod(BASE / 'start_date_study/study.py', 'v6_account_library')

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


class Account(engine.Account):
    def __init__(self, start, actions, days, meta, impact=.001):
        self.orders, self.events, self.audit = {}, [], []
        self.now = pd.Timestamp(start) + pd.Timedelta(hours=9, minutes=31)
        self.date = pd.Timestamp(start)
        self.day, self.bars = {}, {}
        self.impact = impact
        self.cancel_queue = set()
        # Parent supplies the audited FIFO dividend / bonus-share bookkeeping.
        def load(_):
            m = engine.module(ENTRY, 'v6_platform_local')
            self.real_init = m.init
            m.init = lambda context: None
            return m
        engine.load_model = load
        super().__init__('D11', pd.Timestamp(start), actions, days, meta)
        self.context.run_info = NS(frequency='1m')
        m = self.m
        m.init = self.real_init
        m.get_datetime = lambda: self.now.to_pydatetime()
        m.get_orders = lambda: [copy.copy(o) for o in self.orders.values() if pd.Timestamp(o.created).normalize() == self.date]
        m.get_open_orders = lambda: [copy.copy(o) for o in self.orders.values() if o.status in ('ACTIVE', 'PENDING_CANCEL')]
        m.cancel_order = self.cancel
        m.log = NS(info=lambda message: None, warn=lambda message: self.audit.append(str(message)))
        m.init(self.context)

    def sync(self):
        super().sync()
        frozen = sum(self.m._buy_cost(o.amount-o.filled_amount, o.limit_price)
                     for o in self.orders.values() if o.status in ('ACTIVE', 'PENDING_CANCEL') and o.qty > 0)
        self.stock.available_cash = max(0., self.cash - frozen)
        self.stock.frozen_cash += frozen
        for s, p in self.positions.items():
            pending = sum(o.amount-o.filled_amount for o in self.orders.values()
                          if o.symbol == s and o.qty < 0 and o.status in ('ACTIVE', 'PENDING_CANCEL'))
            p.available_amount = max(0, p.available_amount - pending)

    def receipt(self, o):
        self.events.append(dict(time=self.now, id=o.order_id, symbol=o.symbol,
                                status=o.status, filled=o.filled_amount, amount=o.amount, limit=o.limit_price))
        self.m.on_order(self.context, copy.copy(o))

    def order(self, symbol, quantity, price=None):
        assert price is not None and abs(price * 100 - round(price * 100)) < 1e-6
        if quantity > 0 and self.m._buy_cost(quantity, price) > self.stock.available_cash + 1e-8:
            return None
        if quantity < 0 and -quantity > self.positions[symbol].available_amount:
            return None
        oid = str(len(self.orders) + 1)
        o = NS(order_id=oid, symbol=symbol, qty=quantity, amount=abs(quantity), filled_amount=0,
               limit_price=float(price), created=self.now, status='ACTIVE', avg_price=0.,
               transaction_cost=0., value=0., commission_paid=0., transfer_paid=0., stamp_paid=0.)
        self.orders[oid] = o
        self.receipt(o)
        self.sync()
        return oid

    def cancel(self, oid):
        o = self.orders[str(oid)]
        if o.status not in ('ACTIVE', 'PENDING_CANCEL'):
            return None
        # Deliberately asynchronous: matching can race a cancel request.
        o.status = 'PENDING_CANCEL'
        self.cancel_queue.add(o.order_id)
        self.receipt(o)
        return None

    def settle(self, o, quantity, price):
        s, qty = o.symbol, quantity if o.qty > 0 else -quantity
        value = round(quantity * price, 2)
        cumulative = o.value + value
        commission = round(max(5., cumulative * .0003), 2) - o.commission_paid
        transfer = round(cumulative * (.00002 if self.date < pd.Timestamp('2022-04-29') else .00001), 2) - o.transfer_paid
        stamp = (round(cumulative * (.001 if self.date < pd.Timestamp('2023-08-28') else .0005), 2)
                 - o.stamp_paid) if qty < 0 else 0.
        fees = round(commission + transfer + stamp, 2)
        divtax = 0.
        if qty > 0:
            if value + fees > self.cash + 1e-8:
                return False
            assert qty % 100 == 0
            self.cash -= value + fees
            p = self.holdings.setdefault(s, dict(qty=0, last=price, lots=[]))
            p['qty'] += qty
            p['lots'].append(dict(q=qty, buy=self.date, release=self.date + pd.Timedelta(days=1), div=0.))
        else:
            assert quantity <= self.available(s)
            p = self.holdings[s]
            remaining = quantity
            for lot in p['lots']:
                if lot['release'] > self.date or lot['buy'] >= self.date:
                    continue
                q = min(remaining, lot['q'])
                remaining -= q
                lot['q'] -= q
                rate = .2 if self.date <= lot['buy'] + pd.DateOffset(months=1) else (
                    .1 if self.date <= lot['buy'] + pd.DateOffset(years=1) else 0.)
                divtax += q * lot['div'] * rate
                if not remaining:
                    break
            assert remaining == 0
            divtax = round(divtax, 2)
            p['lots'] = [lot for lot in p['lots'] if lot['q']]
            p['qty'] += qty
            self.cash += value - fees - divtax
            if not p['qty']:
                del self.holdings[s]
        o.value = cumulative
        o.commission_paid += commission
        o.transfer_paid += transfer
        o.stamp_paid += stamp
        o.filled_amount += quantity
        o.avg_price = o.value / o.filled_amount
        o.transaction_cost += fees
        if o.filled_amount == o.amount:
            o.status = 'FILLED'
        self.fees += fees
        self.tax += divtax
        self.trades.append(dict(date=self.date, time=self.now, order_id=o.order_id, symbol=s, qty=qty,
                                price=price, commission=commission, transfer=transfer, stamp=stamp, dividend_tax=divtax))
        self.receipt(o)
        trade = NS(order_id=o.order_id, order_book_id=s, exec_id=str(len(self.trades)), side='BUY' if qty > 0 else 'SELL',
                   last_price=price, last_quantity=quantity, tax=stamp, commission=commission, transaction_cost=fees)
        self.m.on_trade(self.context, trade)
        self.sync()
        return True

    def match(self, bars):
        used = {}
        for o in list(self.orders.values()):
            if o.status not in ('ACTIVE', 'PENDING_CANCEL') or self.now <= o.created:
                continue
            b = bars.get(o.symbol)
            if b is None or b.is_paused or b.volume <= 0:
                continue
            buy = o.qty > 0
            # No assumed fills on a one-price locked limit board.
            if (buy and b.low >= b.high_limit - 1e-8) or (not buy and b.high <= b.low_limit + 1e-8):
                continue
            if buy:
                if b.open <= o.limit_price:
                    price = min(o.limit_price, b.open * (1 + self.impact), b.high)
                elif b.low < o.limit_price:
                    price = o.limit_price
                else:
                    continue
            else:
                if b.open >= o.limit_price:
                    price = max(o.limit_price, b.open * (1 - self.impact), b.low)
                elif b.high > o.limit_price:
                    price = o.limit_price
                else:
                    continue
            price = round(float(price), 2)
            cap = max(0, int(b.volume * .25 / 100) * 100 - used.get(o.symbol, 0))
            quantity = min(o.amount-o.filled_amount, cap)
            if buy or quantity != o.amount-o.filled_amount:
                quantity = int(quantity // 100) * 100
            if quantity > 0 and self.settle(o, quantity, price):
                used[o.symbol] = used.get(o.symbol, 0) + quantity
        for oid in self.cancel_queue:
            o = self.orders[oid]
            if o.status != 'FILLED':
                o.status = 'CANCELLED'
                self.receipt(o)
        self.cancel_queue.clear()
        self.sync()

    def begin_day(self, date, index, prev, ranks):
        self.date, self.day = date, self.days[date]
        self.corporate()
        self.sync()
        g = self.m.g
        for s, old in g.alpha_close_shares.items():
            now = self.holdings.get(s, {}).get('qty', 0)
            if old > 0 and now > 0 and old != now and s in g.alpha_targets:
                g.alpha_targets[s] = int(math.floor(g.alpha_targets[s] * now / old + 1e-8))
        g.alpha_index, g.alpha_ready, g.alpha_last_data = index, True, str(prev.date())
        if g.alpha_first or (index - 1) % 20 == 0:
            g.alpha_ranks = ranks[str(prev.date())]
        needed = set(self.holdings) | set(g.alpha_targets) | set(g.alpha_ranks)
        g.alpha_info = {s: dict(volume20=self.days[prev][s].volume20, previous_st=bool(self.days[prev][s].isST))
                        for s in needed if s in self.days[prev]}
        return needed

    def finish_day(self):
        self.now = self.date + pd.Timedelta(hours=15, minutes=30)
        for o in self.orders.values():
            if o.status in ('ACTIVE', 'PENDING_CANCEL'):
                o.status = 'CANCELLED'
                self.receipt(o)
        self.sync()
        self.m._after_trading(self.context)
        market = 0.
        for s, p in self.holdings.items():
            row = self.day.get(s)
            if row is not None and row.close > 0:
                p['last'] = float(row.close)
            market += p['qty'] * p['last']
            assert p['qty'] == sum(lot['q'] for lot in p['lots'])
        assert self.cash >= -.01
        equity = self.cash + market + sum(amount for date, amount in self.receivables)
        self.curve.append(dict(date=self.date, equity=equity, cash=self.cash, market_value=market, exposure=market/equity))


MINUTE_COLUMNS = ['datetime', 'symbol', 'open', 'high', 'low', 'close', 'volume', 'high_limit', 'low_limit', 'is_st', 'is_paused']

def load_minutes(path):
    x = pd.read_parquet(path)
    missing = set(MINUTE_COLUMNS) - set(x.columns)
    if missing:
        raise ValueError('Missing unadjusted minute columns: %s' % sorted(missing))
    x.datetime = pd.to_datetime(x.datetime)
    if x.datetime.dt.tz is not None:
        raise ValueError('Use naive Asia/Shanghai timestamps of COMPLETED bars')
    if x.duplicated(['datetime', 'symbol']).any():
        raise ValueError('Duplicate minute bars')
    nums = ['open', 'high', 'low', 'close', 'volume', 'high_limit', 'low_limit', 'is_st', 'is_paused']
    x[nums] = x[nums].apply(pd.to_numeric, errors='raise')
    if not np.isfinite(x[nums].to_numpy()).all():
        raise ValueError('Nonfinite minute data')
    if not (x.is_st.isin([0, 1]) & x.is_paused.isin([0, 1]) & x.volume.ge(0)).all():
        raise ValueError('Invalid flags/volume')
    active = x[x.is_paused.eq(0)]
    if not (active.low.gt(0) & active.low.le(active[['open', 'close']].min(axis=1)) &
            active.high.ge(active[['open', 'close']].max(axis=1)) &
            active.low.ge(active.low_limit-.011) & active.high.le(active.high_limit+.011)).all():
        raise ValueError('Invalid OHLC / daily price bounds')
    return {pd.Timestamp(t): {r.symbol: NS(**r._asdict()) for r in frame.itertuples(index=False)}
            for t, frame in x.groupby('datetime', sort=True)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['daily-proxy', 'minute'], required=True)
    parser.add_argument('--minutes', type=Path)
    parser.add_argument('--start', default='2020-01-01')
    parser.add_argument('--end', default='2026-09-30')
    parser.add_argument('--impact', type=float, default=.001)
    args = parser.parse_args()
    entry_hash = sha(ENTRY)
    runner_hash = sha(Path(__file__))
    if not 0 <= args.impact <= .05:
        parser.error('impact must be between 0 and .05')
    if args.mode == 'minute' and args.minutes is None:
        parser.error('--mode minute requires --minutes; never substitute daily data')
    calendar_path = BASE/'start_date_study/benchmark.parquet'
    dates = pd.DatetimeIndex(pd.read_parquet(calendar_path).date)
    if pd.Timestamp(args.end) > dates.max():
        parser.error('Requested end exceeds locally verified data through %s' % dates.max().date())
    run_dates = dates[(dates >= args.start) & (dates <= args.end)]
    if len(run_dates) < 2:
        parser.error('Need at least two trading dates')
    inputs = json.loads((OLD/'evaluation_inputs.json').read_text(encoding='utf-8'))
    p = mod(BASE/'test2_retrain_2022/pipeline.py', 'v6_data_paths')
    checks = dict(calendar=sha(calendar_path) == inputs['benchmark_sha256'],
                  raw_inputs=all(sha(p.DATA/'raw'/r['symbol'][-2:]/(r['symbol']+'.parquet')) == r['sha256'] for r in inputs['files']))
    if not all(checks.values()):
        raise ValueError('Frozen ranking inputs changed; regenerate audited rankings before replay: %s' % checks)
    ranks = json.loads((OLD/'rankings.json').read_text(encoding='utf-8'))
    required = {str(dates[dates.get_loc(d)-1].date()) for d in run_dates
                if d == run_dates[0] or (dates.get_loc(d)-1) % 20 == 0}
    if required - ranks.keys():
        raise ValueError('This start requires additional frozen factor rankings: %s' % sorted(required-ranks.keys()))
    out = HERE / ('results_' + args.mode.replace('-', '_'))
    out.mkdir(exist_ok=True)
    p.HERE = out
    loader = mod(BASE/'baseline_2/halfyear_starts_20261008/ledger.py', 'v6_data_loader')
    days, actions, outs = loader.load(p, engine, ranks, dates, calendar_path.parent)
    minutes = load_minutes(args.minutes) if args.mode == 'minute' else None
    a = Account(run_dates[0], actions, days, outs, args.impact)
    for d in run_dates:
        i = dates.get_loc(d)
        needed = a.begin_day(d, i, dates[i-1], ranks)
        if minutes is None:
            # Explicit daily proxy: synthetic opening decision then opening fill.
            # No intraday path, no repricing; final daily close used ONLY to value NAV.
            for minute in (31, 32):
                now = d + pd.Timedelta(hours=9, minutes=minute)
                bars = {}
                for s in needed:
                    r = days[d].get(s)
                    if r is None:
                        continue
                    pct = .05 if r.isST and d < pd.Timestamp('2026-07-06') else .1
                    bars[s] = NS(datetime=now, open=r.open, high=r.open, low=r.open, close=r.open,
                                 volume=r.volume, is_st=bool(r.isST), is_paused=r.tradestatus != 1,
                                 high_limit=math.floor(r.preclose*(1+pct)*100+.5)/100,
                                 low_limit=math.floor(r.preclose*(1-pct)*100+.5)/100)
                a.now, a.bars = now, bars
                a.match(bars)
                a.m._handle_bar(a.context, bars)
        else:
            for now in pd.date_range(d+pd.Timedelta(hours=9, minutes=31), d+pd.Timedelta(hours=10, minutes=1), freq='min'):
                bars = minutes.get(now, {})
                if needed - bars.keys():
                    raise ValueError('Incomplete minute coverage at %s; missing %s symbols (include zero-volume paused rows)' %
                                     (now, len(needed-bars.keys())))
                a.now, a.bars = now, bars
                a.match(bars)
                a.m._handle_bar(a.context, bars)
        a.finish_day()
        if len(a.curve) % 250 == 0:
            print('REPLAY', args.mode, d.date(), round(a.curve[-1]['equity'], 2), flush=True)
    q = pd.DataFrame(a.curve)
    if sha(ENTRY) != entry_hash or sha(Path(__file__)) != runner_hash:
        raise RuntimeError('Source changed while replay was running; discard run and restart')
    nav = q.equity.to_numpy()
    ret = nav / np.r_[100000., nav[:-1]] - 1
    result = dict(mode=args.mode, start=str(run_dates[0].date()), end=str(run_dates[-1].date()), initial_cash=100000,
                  final_equity=float(nav[-1]), total_return=float(nav[-1]/100000-1),
                  cagr=float((nav[-1]/100000)**(365.25/((run_dates[-1]-run_dates[0]).days+1))-1),
                  max_drawdown=float((1-nav/np.maximum.accumulate(np.r_[100000.,nav])[1:]).max()),
                  sharpe=float(ret.mean()/ret.std(ddof=1)*np.sqrt(252)), fill_count=len(a.trades),
                  submitted_orders=len(a.orders), transaction_fees=a.fees, dividend_tax=a.tax,
                  unresolved_actions=len(a.issues), reference_differences=len(a.reference_diffs),
                  audit_alerts=len(a.audit), final_cash=a.cash,
                  limitation='Daily opening proxy: two synthetic open events, fills at open (zero realized price impact), daily volume capacity, asynchronous cash may defer purchases; NOT minute strategy performance' if minutes is None else
                             'Next-minute OHLC/volume approximation, no bid/ask queue reconstruction')
    q.to_parquet(out/'daily_equity.parquet', index=False)
    pd.DataFrame(a.trades).to_parquet(out/'trades.parquet', index=False)
    pd.DataFrame(a.events).to_parquet(out/'orders.parquet', index=False)
    dump(out/'results.json', result)
    dump(out/'issues.json', dict(corporate=a.issues, reference=a.reference_diffs, audit=a.audit))
    dump(out/'manifest.json', dict(platform_sha256=entry_hash, local_sha256=runner_hash,
                                  input_manifest_sha256=sha(OLD/'evaluation_inputs.json'), ranking_sha256=sha(OLD/'rankings.json'),
                                  minute_sha256=sha(args.minutes) if args.minutes else None, impact=args.impact, checks=checks))
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
