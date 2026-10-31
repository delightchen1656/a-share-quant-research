"""User-directed daily-bar exit experiment; preserve all earlier registrations."""
from pathlib import Path
import json
import hashlib
import datetime
import shutil

BASE=Path(__file__).resolve().parent.parent
OLD=BASE/'audits/holdout_restricted/monday_account_backtest_v1_1'
OUT=BASE/'audits/holdout_restricted/monday_account_daily_v3'
RULES=BASE/'audits/holdout_restricted/monday_trading_rules_daily_v3'
SRC=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()

def dump(path,payload):
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    RULES.mkdir(parents=True,exist_ok=True)
    assert not (RULES/'REGISTRATION.json').exists()
    rules=json.loads((BASE/'audits/holdout_restricted/monday_trading_rules_v2/RULES.json').read_text(encoding='utf-8'))
    rules.update(id='Monday_selection_Tuesday_touch_daily_reopen_floor_v3',
        status='User-approved daily OHLC approximation, registered before its account results.',
        authorization='User: 就日线，出现开板就按照跌停卖出',
        parent_rules_sha256=sha(BASE/'audits/holdout_restricted/monday_trading_rules_v2/RULES.json'))
    rules['holding'].update(normal_exit='Tuesday valid close when low has not touched that day lower limit.',
        limit_touch_exit='Tuesday low <= daily lower limit + 0.004 activates persistent emergency exit. If daily high > lower limit + 0.004, assume reopening and sell at that day lower limit.',
        unresolved_after_Tuesday='Emergency exit persists on EVERY following trading day. If high > that day lower limit + 0.004, sell listed shares at that day lower limit. A full-session lower-limit lock carries over.',
        partial_exit='Sell all currently listed shares in this idealized test. Unlisted entitlements retain exit intent until listed; do not fabricate their early sale.')
    rules['sell'].update(order_type='Daily-bar hypothetical reopening sale, or ordinary Tuesdayclose.',
        normal_price='Tuesdayclose if no touch; if suspended/missing, mark overdue and retry first subsequent valid dailyclose, subject to lower-limit lock.',
        emergency_price='Current session reconstructed legal lower limit; fixed conservative valuation even if below the observed session low, separately counted as hypothetical outside-range pricing.',
        timing_evidence='Daily OHLC cannot establish first reopening or available depth. On trigger day, open above floor and close at floor leaves touch/reopen order ambiguous; counted explicitly and still filled under user-authorized approximation.',
        retry='Every subsequent actual trading day; never wait until nextTuesday.',
        capacity_policy='No sell-side volume cap or lowerlimit-plus-tick. Buy-side unchanged. All listed shares assumed filled at proxy price.')
    rules['intraday_resolution']=dict(currently_approved_proxy='daily_OHLC_floor_price',
        daily_trigger='Tuesday low <= lower + 0.004',daily_reopen='active valid daily high > lower + 0.004',
        ambiguous_order='Triggerday open > lower + 0.004 and close <= lower + 0.004; no proof high followed touch.',
        full_lock='active high <= lower + 0.004: no fill',
        limitations='No precise intraday time, order queue, capacity or first-reopen execution certification. No intraday download required.')
    rules['schedule']['old_position_exit']='Attempt every trading day after overdue/emergency; original Monday opening buys use prior confirmed cash/slots.'
    rules['capital']['same_open_emergency_exit']='All Monday entry budgets and slots fixed before same-session exits; never recycle unconfirmed sell proceeds or freed slots.'
    dump(RULES/'RULES.json',rules)
    text='''日线开板卖出V3（用户指定近似）
周一买入、冻结模型与因子、top10、买入容量、事前定量、预算与交易费用不变。
周二未触及跌停：按有效收盘价卖出。
周二最低价触及当日跌停价，且最高价高于该价：视为开板，全部已上市可卖股份按当日跌停价记成交。
周二全天封死跌停：保留退出意图，之后每个交易日重试；当日最高价高于当日跌停价即按当日跌停价记成交。
此为用户指定的日线成交近似，无法证实先触板再开板、首次开板时点和盘口容量。触板日开盘高于跌停而收盘封板的顺序歧义单独计数，但主结果仍按此近似成交。
后续日直接高开、全天未回落至跌停时，仍按当日跌停价保守记账，单列成交价低于日内最低价的假设次数，不称其为真实历史成交。
停牌/缺价不能伪造成交；普通到期退出因停牌延期时，恢复有效报价后尝试收盘退出。缺行未经核实仍是异常。
未上市送转股保留权益及退出意图，上市后再处理。周一买单不能使用同场未确认卖出所得现金或名额。
本次不是因子优化，研发仅2021—2023既有逐年向前分数；后验结果不得读取或回流。旧规则和结果保留。
'''
    (RULES/'RULES.txt').write_text(text,encoding='utf-8')
    spec=json.loads((OLD/'spec.json').read_text(encoding='utf-8'))
    spec.update(rules_sha256=sha(RULES/'RULES.json'),execution_version='daily_reopen_floor_v3',
        authorization='User-directed daily proxy exit revision; no model changes and no posterior result read.',
        auction_semantics='Daily OHLC conditional entry and hypothetical floor-price emergency exit, no certified fills.',
        no_optimization='No factor or model changes. Exit rule only changed by explicit user instruction before this replay.')
    dump(OUT/'spec.json',spec)
    for name in ['scores.parquet','weekly_schedule.parquet','company_collection_audit.json','company_events_conditional.json']:
        shutil.copy2(OLD/name,OUT/name)
    for name in ['common.py','execution.py','portfolio.py','account_validation.py','company_data.py']:
        source=(BASE/'src_account_v1_1'/name).read_text(encoding='utf-8')
        if name=='common.py':
            source=source.replace('monday_account_backtest_v1_1','monday_account_daily_v3')
        (SRC/name).write_text(source,encoding='utf-8')
    # Only replace the sell leg. Buys execute before exits so no same-auction
    # sale can fund or free a slot for the already determined Monday orders.
    path=SRC/'portfolio.py'
    source=path.read_text(encoding='utf-8').replace('reference_adjust\n','reference_adjust\nfrom daily_exit import daily_sell\n')
    start=source.index('        if date.weekday()==1:\n            for s,p in list(positions.items()):')
    end=source.index('        # Record-close ownership',start)
    source=source[:start]+'''        for s,p in list(positions.items()):
            if date.weekday()!=1 and not p.get('exit_due',False):
                continue
            bar=quotes.bar(s,i)
            fill,reason,state=daily_sell(bar,p['qty'],p['entry_date'],date,
                                        p.get('exit_due',False),p.get('emergency',False))
            p.update(exit_due=state['exit_due'],emergency=state['emergency'])
            if state['triggered_today']:
                log(date,'limit_touch',symbol=s)
            if fill is None:
                log(date,'sell_delayed',symbol=s,reason=reason)
                continue
            cash+=fill['notional']-fill['fee']
            trade=trade_records[p['trade_id']]
            trade['exit_notional']+=fill['notional']
            trade['exit_fee']+=fill['fee']
            trade['sold_shares']+=fill['qty']
            p['qty']=0
            transactions.append(dict(method=method,date=key,symbol=s,side='sell',trade_id=p['trade_id'],**fill))
            log(date,'sell',symbol=s,qty=fill['qty'],price=fill['price'],exit_kind=fill['exit_kind'],
                ambiguous_order=fill['ambiguous_order'],outside_daily_range=fill['outside_daily_range'])
            if not p['unlisted']:
                trade.update(status='closed',exit_date=key)
                del positions[s]
''' +source[end:]
    path.write_text(source,encoding='utf-8')
    dump(RULES/'REGISTRATION.json',dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        before_new_account_results=True,rules_sha256=sha(RULES/'RULES.json'),spec_sha256=sha(OUT/'spec.json'),
        no_new_intraday_query=True,no_posterior_results_read=True))
    print('Daily proxy V3 registered; prior V2 and V1 preserved.',flush=True)

if __name__=='__main__':main()
