"""Fixed leader-pool comparisons, retrospective classification, no production writes."""
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import argparse
import ast
import json
import pickle

import numpy as np
import pandas as pd
import lightgbm as lgb

import research_hushen2_buy_weekdays as replay
from replay_hushen2_local import ROOT, STRATEGY, APP, GAME, CASES, sha, load

VARIANTS = ['current', 'leader_no_refill', 'leader_refill', 'leader_pool_rank']
SOURCE = ROOT / 'archive/hushen_2/pre_registration_research_20261020/results/batch_004_pre2025_factor_tuning/base_component_panel_pre2025.parquet'
PACK = ROOT / 'archive/reports/holdout_restricted/hushen2_entry_weekdays/pre2025_20261027_035916/INPUTS_PRE2025.pkl'
LEADERS = ROOT / '研究尝试/方向1_超跌反弹/holdout_restricted/leader_classification/mainboard_leader_codes.json'
QUOTES = ROOT / '研究尝试/方向1_超跌反弹/inputs_pre2025/full_mainboard'


def component_panel(out):
    """Rebuild from the exact current frozen quote vintage, price cutoff2024."""
    cache = out / 'COMPONENT_PANEL_PRE2025.parquet'
    if cache.exists():
        return pd.read_parquet(cache), json.loads((out / 'PANEL_INPUTS.json').read_text(encoding='utf-8'))
    market = (APP / 'tracker/market.py').read_text(encoding='utf-8')
    feature = next(n for n in ast.parse(market).body if isinstance(n, ast.FunctionDef) and n.name == 'model_features')
    feature_source = ast.get_source_segment(market, feature)
    namespace = dict(pd=pd, np=np, SIGNAL_START='2015-01-01')
    exec(compile(feature_source, '<frozen_model_feature_function>', 'exec'), namespace)
    manifest = json.loads((GAME / 'frozen_inputs/market/DOWNLOAD_COMPLETE.json').read_text(encoding='utf-8'))
    identity = json.loads((CASES / 'INPUT_IDENTITY.json').read_text(encoding='utf-8'))
    excluded = set(identity['excluded_symbols'])
    models = {}
    model_manifest = json.loads((STRATEGY / 'model/manifest.json').read_text(encoding='utf-8'))
    for name in ('utility', 'pen025'):
        path = STRATEGY / 'model' / f'{name}.txt'
        assert sha(path) == model_manifest[name]
        models[name] = lgb.Booster(model_str=path.read_text(encoding='utf-8'))
    rows = []
    inputs = {}
    for i, (symbol, files) in enumerate(manifest['receipts'].items(), 1):
        if symbol in excluded:
            continue
        rel, expected = next((r, h) for r, h in files.items() if 'qfq' in r)
        path = GAME / 'frozen_inputs/market' / rel
        assert sha(path) == expected, symbol
        inputs[str(path.relative_to(ROOT))] = expected
        b = pd.read_parquet(path, filters=[('date', '<=', pd.Timestamp('2024-12-31'))]).sort_values('date').reset_index(drop=True)
        if len(b) < 120:
            continue
        b['date'] = pd.to_datetime(b.date)
        assert b.date.max() <= pd.Timestamp('2024-12-31')
        for c in ['open', 'high', 'low', 'close', 'preclose', 'volume', 'amount', 'turn', 'tradestatus', 'isST']:
            b[c] = pd.to_numeric(b[c], errors='coerce')
        b['symbol'] = symbol
        f = namespace['model_features'](b)
        if len(f):
            rows.append(f)
        if i % 600 == 0:
            print('FEATURE_FILES', i, len(manifest['receipts']), flush=True)
    panel = pd.concat(rows, ignore_index=True).sort_values(['date', 'symbol']).reset_index(drop=True)
    # Existing source uses population-scale cap proxy and cross-sectional ranks.
    for name, model in models.items():
        panel[name] = model.predict(panel[model.feature_name()], num_threads=4)
    panel['pen100'] = 0.
    panel['_cap'] = panel.f_log_amount - np.log(panel.f_turn.clip(lower=1e-6))
    ranks = panel.groupby('date')[['_cap', 'vol60', 'overnight20', 'intraday20', 'mom120', 'close_to_high60', 'mom20']].rank(pct=True, method='average') - .5
    panel['h_size_neg'] = -ranks['_cap']
    panel['h_vol60_neg'] = -ranks.vol60
    panel['h_overnight_pos'] = ranks.overnight20
    panel['h_intraday_neg'] = -ranks.intraday20
    panel['t_mom120_pos'] = ranks.mom120
    panel['t_high60_pos'] = ranks.close_to_high60
    panel['t_mom20_pos'] = ranks.mom20
    panel['t_vol60_neg'] = -ranks.vol60
    columns = ['date', 'symbol', 'close', 'atr_pct', 'utility', 'pen025', 'pen100'] + [c for c in panel if c.startswith(('h_', 't_'))]
    panel = panel[columns]
    panel.to_parquet(cache, index=False)
    evidence = dict(source='Current frozen quote vintage; pyarrow date predicate <=20241231, history retained for rolling warmup',
                    excluded_symbols=sorted(excluded), feature_source=feature_source, quote_hashes=inputs,
                    models={name: model_manifest[name] for name in models}, min_date=str(panel.date.min()), max_date=str(panel.date.max()))
    (out / 'PANEL_INPUTS.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    return panel, evidence


def ranked(panel, builder, spec):
    m = builder.component_m(panel, tuple(spec['M_internal']))
    h = builder.component_h(panel, tuple(spec['H_internal']))
    out = panel[['date', 'symbol', 'close', 'atr_pct']].copy()
    out['score'] = .6 * m + .4 * h
    out['factor'] = 'C04_NEW'
    return out.dropna(subset=['score']).sort_values(['date', 'score', 'symbol'], ascending=[True, False, True], kind='stable')


def prepare(out):
    selection = json.loads((STRATEGY / 'CURRENT_SELECTION.json').read_text(encoding='utf-8'))['selection']
    assert selection['signal_filter']['policy'] == 'original_top3_atr_ge025_no_refill_v1'
    assert selection['slots'] == 5 and selection['initial_cash'] == 100000
    spec = selection['factor_spec']
    assert spec['outer'] == [.6, 0., .4]
    protected = [STRATEGY / 'CURRENT_SELECTION.json', APP / 'CURRENT_SELECTION.json', GAME / 'runtime/run_batch.py', GAME / 'runtime/baseline_fixed_ioc.py', CASES / 'INPUT_PACK.pkl']
    protected += list((STRATEGY / 'model').glob('*.txt'))
    before = {str(p): sha(p) for p in protected}
    builder = load('leader_frozen_builder', STRATEGY / 'runtime/frozen_builder.py')
    with PACK.open('rb') as f:
        p = pickle.load(f)
    panel, panel_evidence = component_panel(out)
    assert panel.date.max() < pd.Timestamp('2025-01-01')
    assert not panel.duplicated(['date', 'symbol']).any()
    codes = set(json.loads(LEADERS.read_text(encoding='utf-8-sig')))
    full = ranked(panel, builder, spec)
    pool = panel.loc[panel.symbol.str[:6].isin(codes)].copy()
    # Base panel stores full-market percentile components. Re-rank the primitive
    # components inside the leader pool before combining/smoothing them.
    components = [c for c in pool if c.startswith(('t_', 'h_'))]
    pool[components] = pool.groupby('date', sort=False)[components].rank(pct=True, method='average') - .5
    pool_ranked = ranked(pool, builder, spec)
    full = full.loc[full.date.between('2020-01-01', '2024-12-31')]
    pool_ranked = pool_ranked.loc[pool_ranked.date.between('2020-01-01', '2024-12-31')]
    top = full.groupby('date', sort=False).head(3).copy()
    signals = {
        'current': top,
        'leader_no_refill': top.loc[top.symbol.str[:6].isin(codes)].copy(),
        'leader_refill': full.loc[full.symbol.str[:6].isin(codes)].groupby('date', sort=False).head(3).copy(),
        'leader_pool_rank': pool_ranked.groupby('date', sort=False).head(3).copy(),
    }
    symbols = sorted(set().union(*(set(s.symbol) for s in signals.values())))
    quote_manifest = json.loads((QUOTES / 'QUOTE_MANIFEST.json').read_text(encoding='utf-8'))
    hashes = {r['code']: r['sha256'] for r in quote_manifest['files'] if r['mode'] == 'raw'}
    raw_hashes = {}
    new_symbols = []
    for symbol in symbols:
        if symbol in p['bars']:
            continue
        path = QUOTES / 'raw' / f'{symbol[:6]}.parquet'
        assert sha(path) == hashes[symbol[:6]], symbol
        raw_hashes[str(path.relative_to(ROOT))] = hashes[symbol[:6]]
        b = pd.read_parquet(path)
        b['date'] = pd.to_datetime(b.date)
        assert b.date.max() <= pd.Timestamp('2024-12-31')
        for c in ['open', 'high', 'low', 'close', 'preclose', 'volume', 'amount']:
            b[c] = pd.to_numeric(b[c], errors='raise')
        p['bars'][symbol] = b.set_index('date').sort_index()[next(iter(p['bars'].values())).columns]
        new_symbols.append(symbol)
    lookup = []
    for symbol in symbols:
        b = p['bars'][symbol]
        lookup.append(pd.DataFrame({'date': b.index, 'symbol': symbol, 'close': b.close.to_numpy()}))
    lookup = pd.concat(lookup, ignore_index=True)
    assert not lookup.duplicated(['date', 'symbol']).any()
    for variant, s in signals.items():
        # Frozen baseline computes priceTR on its qfq signal-feature bars, then
        # joins RAW close for execution. Recomputing ATR on raw bars would change
        # the baseline around company actions, so preserve the signal-panel ATR.
        s = s.drop(columns=['close']).merge(lookup, on=['date', 'symbol'], how='left', validate='one_to_one')
        assert s[['close', 'atr_pct']].notna().all().all()
        # Original ATR gate stays AFTER top3, also in the refilled leader variant.
        s = s.loc[s.atr_pct.ge(.025)].sort_values(['date', 'score', 'symbol'], ascending=[True, False, True], kind='stable').reset_index(drop=True)
        assert s.groupby('date').size().le(3).all()
        if variant != 'current':
            assert s.symbol.str[:6].isin(codes).all()
        signals[variant] = s
    reference = p['signals'].sort_values(['date', 'score', 'symbol'], ascending=[True, False, True]).reset_index(drop=True)
    s = signals['current']
    pd.testing.assert_frame_equal(s[['date', 'symbol']], reference[['date', 'symbol']])
    for c in ['score', 'close', 'atr_pct']:
        assert np.allclose(s[c], reference[c], atol=1e-12, rtol=1e-12), c
    a = set(zip(signals['leader_no_refill'].date, signals['leader_no_refill'].symbol))
    b = set(zip(signals['leader_refill'].date, signals['leader_refill'].symbol))
    # ATR filtering can remove replacement leaders but may not remove original survivors.
    assert a <= b
    protocol = dict(
        scope='2020-2024 yearly Q1 all trading-day starts to same year end',
        variants=VARIANTS, retraining='Fourth direction reserved pending original labels/parameters; not run',
        baseline='100000,5slots20%,fixedIOC,2%capacity,7/30calendar,T+1,stopfirst,4ATRtake/1.5ATRstop,expiryclose,37dayentryblackout',
        atr='Frozen baseline qfq-feature priceTR=SMA14(max(high-low,abs(high-preclose),abs(low-preclose)))/close clipped .015-.05; raw close only for execution; >=.025 after top3; no ATR refill',
        leader_no_refill='Original full-universe top3 then leader and ATR filters',
        leader_refill='Full-universe frozen scores, choose first3 leaders, then original ATR gate',
        leader_pool_rank='Frozen predictions; primitive components re-ranked in leader pool, then original M/H rank and5observation smoothing, leader top3, original ATR gate',
        caution='Current20261027 leader classification retrospectively applied, not historical membership or blind development; root previously exposed to holdout',
        date_boundary='No prices/returns after20241231; current classification is deliberate known exception',
        protected_before=before,
        inputs={str(f.relative_to(ROOT)): sha(f) for f in [out / 'COMPONENT_PANEL_PRE2025.parquet', PACK, LEADERS, QUOTES / 'QUOTE_MANIFEST.json', STRATEGY / 'runtime/frozen_builder.py']},
        panel_evidence='PANEL_INPUTS.json',
        additional_raw_hashes=raw_hashes, additional_symbols=new_symbols,
        baseline_signal_parity=True,
        signal_counts={v: {str(y): int(s.date.dt.year.eq(y).sum()) for y in range(2020,2025)} for v, s in signals.items()},
    )
    for variant, s in signals.items():
        s.to_parquet(out / f'SIGNALS_{variant}.parquet', index=False)
    with (out / 'INPUTS_PRE2025.pkl').open('wb') as f:
        pickle.dump(p, f, pickle.HIGHEST_PROTOCOL)
    (out / 'PROTOCOL.json').write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding='utf-8')
    print('PREPARED', protocol['signal_counts'], 'ADDITIONAL_SYMBOLS', len(new_symbols), flush=True)


def initialize(out):
    replay.initialize(out)
    for path in (Path(out) / 'actions').glob('*.json'):
        receipt = json.loads(path.read_text(encoding='utf-8'))
        assert receipt['error_code'] == '0'
        key = receipt['key']
        symbol, year = key.split('/')
        assert int(year) <= 2024
        p = replay.G['p']
        if key in p['known']:
            continue
        p['known'].add(key)
        for row in receipt['records']:
            if not row.get('dividOperateDate'):
                continue
            d = pd.Timestamp(row['dividOperateDate'])
            number = lambda k: float(str(row.get(k, '')).strip() or 0)
            p['actions'].setdefault((d, symbol), []).append(dict(
                cash=number('dividCashPsBeforeTax'), stock=number('dividStocksPs') + number('dividReserveToStockPs'),
                taxable_stock=number('dividStocksPs'), pay=pd.Timestamp(row.get('dividPayDate') or d),
                release=pd.Timestamp(row.get('dividStockMarketDate') or d), source=str(path)))
    replay.VARIANTS = {v: None for v in VARIANTS}
    replay.G['signals'] = {v: pd.read_parquet(Path(out) / f'SIGNALS_{v}.parquet') for v in VARIANTS}


def run(job):
    replay.G['p']['signals'] = replay.G['signals'][job[0]]
    return replay.run(job)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--fetch-gaps', action='store_true')
    args = parser.parse_args()
    out = args.output or ROOT / 'archive/reports/holdout_restricted/hushen2_leader_pool' / datetime.now().strftime('pre2025_%Y%m%d_%H%M%S')
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    print('OUTPUT', out, flush=True)
    if args.fetch_gaps:
        import baostock as bs
        gaps = json.loads((out / 'SUMMARY.json').read_text(encoding='utf-8'))['action_gaps']
        folder = out / 'actions'
        folder.mkdir(exist_ok=True)
        assert bs.login().error_code == '0'
        try:
            for key in gaps:
                symbol, year = key.split('/')
                assert int(year) <= 2024
                response = bs.query_dividend_data(code=symbol[-2:].lower() + '.' + symbol[:6], year=year, yearType='operate')
                records = []
                while response.error_code == '0' and response.next():
                    records.append(dict(zip(response.fields, response.get_row_data())))
                assert response.error_code == '0'
                payload = dict(key=key, error_code=response.error_code, records=records, fetched_at=datetime.now().isoformat())
                (folder / (key.replace('/', '_') + '.json')).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
                print('ACTION_RECEIPT', key, len(records), flush=True)
        finally:
            bs.logout()
    if not args.resume:
        prepare(out)
    protocol = json.loads((out / 'PROTOCOL.json').read_text(encoding='utf-8'))
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize, initargs=(str(out),)) as pool:
        for future in as_completed([pool.submit(run, (v, y)) for y in range(2020,2025) for v in VARIANTS]):
            row = future.result()
            rows.append(row)
            print('COMPLETE', row['year'], row['variant'], 'GAPS', row['action_gaps'], flush=True)
    rows.sort(key=lambda r: (r['year'], VARIANTS.index(r['variant'])))
    for row in rows:
        m = pd.read_parquet(out / str(row['year']) / row['variant'] / 'START_METRICS.parquet')
        row['cumulative_return_median'] = float(m.cumulative_return.median())
        row['annualized_return_median'] = float(m.annualized_return.median())
    gaps = sorted({g for r in rows for g in r['action_gaps']})
    assert all(sha(Path(f)) == h for f, h in protocol['protected_before'].items())
    result = dict(status='verified' if not gaps else 'incomplete_action_coverage', rows=rows, action_gaps=gaps,
                  protected_unchanged=True, baseline_signal_and_account_parity=True, retraining_pending=True)
    (out / 'SUMMARY.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('STATUS', result['status'], 'ACTION_GAPS', gaps, flush=True)


if __name__ == '__main__':
    main()
