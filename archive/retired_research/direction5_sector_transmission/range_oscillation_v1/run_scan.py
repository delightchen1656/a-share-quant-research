"""Frozen descriptive nominal-price range screen. Never computes economic returns."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import datetime
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SPEC = json.loads((HERE / 'spec.json').read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def longest_run(mask):
    best = run = 0
    for value in mask:
        run = run + 1 if value else 0
        best = max(best, run)
    return best


def traversals(close, valid, quote_chain, lower, upper):
    """Alternating opposite-zone touches, separated in calendar and quote movement."""
    width = upper - lower
    if width <= 0:
        return 0
    low_zone = lower + SPEC['touch_zone_box_fraction'] * width
    high_zone = upper - SPEC['touch_zone_box_fraction'] * width
    minimum_move = SPEC['minimum_reference_quote_move_log_box_fraction'] * np.log(upper / lower)
    state = 0
    anchor_i = 0
    anchor_price = anchor_chain = 0.0
    count = 0
    for i in np.flatnonzero(valid):
        side = -1 if close[i] <= low_zone else (1 if close[i] >= high_zone else 0)
        if not side:
            continue
        if not state:
            state, anchor_i, anchor_price, anchor_chain = side, i, close[i], quote_chain[i]
        elif side == state:
            if (side == -1 and close[i] < anchor_price) or (side == 1 and close[i] > anchor_price):
                anchor_i, anchor_price, anchor_chain = i, close[i], quote_chain[i]
        elif i - anchor_i >= SPEC['minimum_sessions_between_opposite_touches'] and side * (quote_chain[i] - anchor_chain) >= minimum_move:
            count += 1
            state, anchor_i, anchor_price, anchor_chain = side, i, close[i], quote_chain[i]
    return count


def describe(close, valid, quote_chain):
    first, second = valid[:252], valid[252:]
    values = close[valid]
    a, b = close[:252][first], close[252:][second]
    if min(len(a), len(b)) < 2:
        return None
    lower, upper = np.quantile(values, [0.05, 0.95])
    l1, u1 = np.quantile(a, [0.05, 0.95])
    l2, u2 = np.quantile(b, [0.05, 0.95])
    width = upper - lower
    if width <= 0 or lower <= 0:
        return None
    positions = np.flatnonzero(valid)
    x = positions - positions.mean()
    y = np.log(values)
    trend = abs(float(x @ (y - y.mean()) / (x @ x)) * 503 / np.log(upper / lower))
    center = abs(float(np.median(b) - np.median(a))) / width
    boundary = max(abs(l2 - l1), abs(u2 - u1)) / width
    full_traversals = traversals(close, valid, quote_chain, lower, upper)
    h1_traversals = traversals(close[:252], first, quote_chain[:252], lower, upper)
    h2_traversals = traversals(close[252:], second, quote_chain[252:], lower, upper)
    frozen_coverage = float(np.mean((b >= l1) & (b <= u1)))
    conditions = {
        'width': SPEC['box_width_min'] <= upper / lower - 1 <= SPEC['box_width_max'],
        'extremes': values.max() / values.min() - 1 <= SPEC['full_close_range_max'],
        'center': center <= SPEC['center_drift_max_box_fraction'],
        'boundary': boundary <= SPEC['boundary_drift_max_box_fraction'],
        'trend': trend <= SPEC['absolute_log_trend_max_log_box_fraction'],
        'cycles': full_traversals >= SPEC['minimum_full_window_traversals'] and min(h1_traversals, h2_traversals) >= SPEC['minimum_each_half_traversals'],
        'last_in_box': bool(valid[-1] and lower <= close[-1] <= upper),
    }
    confirmation = bool(frozen_coverage >= SPEC['minimum_second_half_coverage_in_frozen_first_half_band'] and valid[-1] and l1 <= close[-1] <= u1)
    score = 100 * float(np.mean([
        np.clip(1 - trend / .35, 0, 1), np.clip(1 - center / .25, 0, 1),
        np.clip(1 - boundary / .35, 0, 1), np.clip(full_traversals / 12, 0, 1),
        frozen_coverage, valid.mean(),
    ]))
    return dict(lower=float(lower), upper=float(upper), box_width=float(upper / lower - 1),
                close_extreme_range=float(values.max() / values.min() - 1),
                formation_lower=float(l1), formation_upper=float(u1),
                center_drift=float(center), boundary_drift=float(boundary), abs_trend=float(trend),
                traversals=full_traversals, first_half_traversals=h1_traversals,
                second_half_traversals=h2_traversals,
                second_half_frozen_coverage=frozen_coverage,
                last_close=float(close[-1]) if valid[-1] else None,
                box_position=float((close[-1] - lower) / width) if valid[-1] else None,
                score=score, shape_pass=all(conditions.values()), confirmation_pass=confirmation,
                shape_failures=';'.join(k for k, v in conditions.items() if not v))


def structural_dates(ledger, references, rights):
    share = (ledger.bonus_per_share.fillna(0).ne(0) | ledger.transfer_per_share.fillna(0).ne(0))
    structural = [(s, d) for s, d in zip(ledger.loc[share, 'symbol'], pd.to_datetime(ledger.loc[share, 'ex_date']))]
    bad = references.status.str.contains('rights_issue|reorganization|directed_transfer|no_known_dividend', regex=True)
    structural += [(s, d) for s, d in zip(references.loc[bad, 'symbol'], pd.to_datetime(references.loc[bad, 'reference_date']))]
    structural += [(s, d) for s, d in zip(rights.SECUCODE, pd.to_datetime(rights.ex_date))]
    grouped = {}
    for symbol, date in structural:
        if pd.notna(date) and date <= pd.Timestamp(SPEC['data_cutoff']):
            grouped.setdefault(symbol, set()).add(date.to_datetime64())
    return {s: np.array(sorted(v), dtype='datetime64[ns]') for s, v in grouped.items()}


def self_tests():
    n = 504
    close = 10 + np.sin(np.arange(n) * 2 * np.pi / 84)
    valid = np.ones(n, dtype=bool)
    chain = np.log(close / close[0])
    m = describe(close, valid, chain)
    assert m['shape_pass'] and m['confirmation_pass'] and m['traversals'] >= 6, m
    trend = np.linspace(8., 12., n)
    assert not describe(trend, valid, np.log(trend / trend[0]))['shape_pass']
    one_v = np.r_[np.linspace(11., 9., 252), np.linspace(9., 11., 252)]
    assert not describe(one_v, valid, np.log(one_v / one_v[0]))['shape_pass']
    assert traversals(close, valid, np.zeros(n), 9.1, 10.9) == 0
    unavailable = np.zeros(n, dtype=bool)
    unavailable[100:106] = True
    assert longest_run(unavailable) == 6
    assert longest_run(np.array([True, True, False, True])) == 2
    fake = pd.DataFrame({'symbol':['TEST'], 'ex_date':[pd.Timestamp('2021-01-04')], 'bonus_per_share':[0.1], 'transfer_per_share':[0.]})
    empty_ref = pd.DataFrame({'symbol':pd.Series(dtype=str), 'reference_date':pd.Series(dtype=str), 'status':pd.Series(dtype=str)})
    empty_rights = pd.DataFrame({'SECUCODE':pd.Series(dtype=str), 'ex_date':pd.Series(dtype=str)})
    assert len(structural_dates(fake, empty_ref, empty_rights)['TEST']) == 1
    return {'bounded_wave_pass':True, 'monotonic_trend_fail':True, 'one_v_fail':True,
            'mechanical_raw_moves_zero_quote_change_not_cycles':True,
            'unavailable_calendar_gap_detected':True, 'share_event_flagged':True}


def main():
    registration = json.loads((HERE / 'registration.json').read_text())
    assert registration['spec_sha256'] == sha(HERE / 'spec.json')
    tests = self_tests()
    calendar_path = ROOT / 'inputs_pre2025/trading_calendar_v1/calendar.parquet'
    calendar = pd.read_parquet(calendar_path)
    days = calendar.loc[calendar.is_trading_day.eq(1) & calendar.calendar_date.le(SPEC['data_cutoff']), 'calendar_date'].to_numpy(dtype='datetime64[ns]')
    assert np.all(days[1:] > days[:-1])
    asofs = [(year, np.flatnonzero(pd.DatetimeIndex(days).year == year)[-1]) for year in SPEC['asof_years']]
    manifest_path = ROOT / 'inputs_pre2025/kline_v1/manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    ledger_path = ROOT / 'datasets/corporate_actions_reconciled_v3/dividend_event_ledger_provisional.parquet'
    reference_path = ROOT / 'datasets/corporate_actions_reconciled_v3/reference_window_reconciliation.parquet'
    rights_path = ROOT / 'datasets/rights_issues_eastmoney_v1/scope_rights_issue_events.parquet'
    name_path = ROOT / 'inputs_pre2025/industry_official_v1/membership_publication_history.parquet'
    ledger = pd.read_parquet(ledger_path)
    references = pd.read_parquet(reference_path)
    rights = pd.read_parquet(rights_path)
    structural = structural_dates(ledger, references, rights)
    cash_events = {s: pd.to_datetime(g.ex_date).to_numpy() for s, g in ledger.loc[ledger.cash_per_share.gt(0)].groupby('symbol')}
    mismatch = {s: pd.to_datetime(g.reference_date).to_numpy() for s, g in references.loc[references.status.eq('generic_reference_formula_mismatch_needs_investigation')].groupby('symbol')}
    names = pd.read_parquet(name_path)
    name_maps = {}
    for year, end in asofs:
        available = names.loc[pd.to_datetime(names.knowledge_start).le(pd.Timestamp(days[end]))]
        last_pub = pd.to_datetime(available.knowledge_start).max()
        subset = available.loc[pd.to_datetime(available.knowledge_start).eq(last_pub)]
        assert not subset.symbol.duplicated().any()
        name_maps[year] = subset.set_index('symbol')[['stock_name', 'published_date']].to_dict('index')
    def count_between(grouped, symbol, start, end):
        dates = grouped.get(symbol, np.array([], dtype='datetime64[ns]'))
        return int(np.sum((dates >= start) & (dates <= end)))

    def worker(item):
        symbol = item['symbol']
        path = manifest_path.parent / item['snapshot_file']
        assert sha(path) == item['snapshot_sha256'], path
        # Column predicate physically prevents loading 2024 rows into research frames.
        df = pd.read_parquet(path, filters=[('date', '<=', pd.Timestamp(SPEC['data_cutoff']))]).copy()
        if df.empty:
            return [], [], {'symbol':symbol, 'rows_used':0, 'maximum_date':None, 'hash_verified':True}
        df['date'] = pd.to_datetime(df.date)
        assert df.date.is_monotonic_increasing and not df.date.duplicated().any()
        assert df.date.max() <= pd.Timestamp(SPEC['data_cutoff'])
        indices = np.searchsorted(days, df.date.to_numpy())
        assert np.all(indices < len(days)) and np.array_equal(days[indices], df.date.to_numpy())
        numbers = df[['open', 'high', 'low', 'close', 'volume', 'amount', 'pctChg']].apply(pd.to_numeric, errors='coerce').to_numpy(float)
        good = (df.tradestatus.astype(str).eq('1').to_numpy() & np.isfinite(numbers).all(axis=1)
                & (numbers[:, :6] > 0).all(axis=1) & (numbers[:, 6] > -100))
        close = np.full(len(days), np.nan)
        amount = np.full(len(days), np.nan)
        valid = np.zeros(len(days), dtype=bool)
        st = np.ones(len(days), dtype=bool)
        pct = np.zeros(len(days))
        close[indices] = numbers[:, 3]
        amount[indices] = numbers[:, 5]
        valid[indices] = good
        st[indices] = df.isST.astype(str).ne('0').to_numpy()
        pct[indices[good]] = numbers[good, 6] / 100
        quote_chain = np.cumsum(np.log1p(pct))
        metrics, forwards = [], []
        for year, end in asofs:
            start = end - 503
            sl = slice(start, end + 1)
            v = valid[sl]
            row = dict(symbol=symbol, year=year, asof=str(pd.Timestamp(days[end]).date()),
                       window_start=str(pd.Timestamp(days[start]).date()),
                       active_coverage=float(v.mean()), first_half_coverage=float(v[:252].mean()),
                       second_half_coverage=float(v[252:].mean()),
                       maximum_unavailable_run=longest_run(~v), current_not_ST=bool(not st[end]),
                       current_valid=bool(valid[end]))
            recent = amount[max(0, end - 19):end + 1][valid[max(0, end - 19):end + 1]]
            row['last20_median_amount'] = float(np.median(recent)) if len(recent) else None
            row['last20_valid_count'] = len(recent)
            row['data_quality_pass'] = bool(min(v.mean(), v[:252].mean(), v[252:].mean()) >= .95 and longest_run(~v) <= 5 and valid[end] and not st[end])
            row['liquidity_pass'] = bool(len(recent) and np.median(recent) >= SPEC['minimum_last20_median_amount_cny'])
            row['structural_event_dates'] = count_between(structural, symbol, days[start], days[end])
            row['cash_event_count'] = count_between(cash_events, symbol, days[start], days[end])
            row['reference_mismatch_count'] = count_between(mismatch, symbol, days[start], days[end])
            row['structural_integrity_pass'] = row['structural_event_dates'] == 0
            row['historical_name'] = name_maps[year].get(symbol, {}).get('stock_name', symbol)
            row['name_publication_date'] = str(name_maps[year].get(symbol, {}).get('published_date', 'unavailable'))
            desc = describe(close[sl], v, quote_chain[sl])
            if desc:
                row.update(desc)
            else:
                row.update(shape_pass=False, confirmation_pass=False, shape_failures='insufficient_or_constant_quotes', score=0.)
            row['primary_pass'] = bool(row['data_quality_pass'] and row['liquidity_pass'] and row['structural_integrity_pass'] and row['shape_pass'] and row['confirmation_pass'])
            row['all_failures'] = ';'.join([k for k in ['data_quality_pass','liquidity_pass','structural_integrity_pass','shape_pass','confirmation_pass'] if not row[k]])
            metrics.append(row)
            if not row['primary_pass']:
                continue
            for horizon in SPEC['forward_horizons_sessions']:
                f = dict(symbol=symbol, year=year, asof=row['asof'], horizon=horizon,
                         lower=row['lower'], upper=row['upper'], status='not_matured', persistence_success=False)
                if end + horizon < len(days):
                    fv = valid[end + 1:end + horizon + 1]
                    fc = close[end + 1:end + horizon + 1]
                    f['end_date'] = str(pd.Timestamp(days[end + horizon]).date())
                    f['quote_coverage'] = float(fv.mean())
                    f['inside_fraction_valid'] = float(np.mean((fc[fv] >= row['lower']) & (fc[fv] <= row['upper']))) if fv.any() else None
                    breach = fv & ((fc < .99 * row['lower']) | (fc > 1.01 * row['upper']))
                    f['maximum_outside_run'] = longest_run(breach)
                    f['structural_event_dates'] = count_between(structural, symbol, days[end + 1], days[end + horizon])
                    if f['structural_event_dates']:
                        f['status'] = 'not_comparable_structural_event'
                    elif f['quote_coverage'] < .95:
                        f['status'] = 'unknown_low_quote_coverage'
                    else:
                        f['persistence_success'] = bool(f['inside_fraction_valid'] >= .8 and f['maximum_outside_run'] < 10)
                        f['status'] = 'success' if f['persistence_success'] else 'broken_or_low_coverage_in_band'
                forwards.append(f)
        return metrics, forwards, dict(symbol=symbol, rows_used=len(df), maximum_date=str(df.date.max().date()), hash_verified=True)

    all_metrics, all_forwards, file_audits = [], [], []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i, (rows, forwards, audit) in enumerate(pool.map(worker, manifest['files']), 1):
            all_metrics.extend(rows)
            all_forwards.extend(forwards)
            file_audits.append(audit)
            if i % 500 == 0:
                print(f'verified and scanned {i}/{len(manifest["files"])} files', flush=True)
    frame = pd.DataFrame(all_metrics).sort_values(['year','primary_pass','score','symbol'], ascending=[True,False,False,True])
    forward = pd.DataFrame(all_forwards)
    out = HERE / 'results'
    out.mkdir(exist_ok=True)
    frame.to_parquet(out / 'all_stock_metrics.parquet', index=False)
    frame.loc[frame.primary_pass].to_parquet(out / 'primary_candidates.parquet', index=False)
    forward.to_parquet(out / 'forward_persistence.parquet', index=False)
    pd.DataFrame(file_audits).to_parquet(out / 'input_file_audit.parquet', index=False)
    summary = []
    for year, group in frame.groupby('year'):
        base = group.data_quality_pass & group.liquidity_pass
        summary.append(dict(year=int(year), observed_symbols=len(group), quote_quality=int(group.data_quality_pass.sum()),
                            quality_and_liquidity=int(base.sum()), shape_with_quality=int((base & group.shape_pass).sum()),
                            confirmed_without_integrity_filter=int((base & group.shape_pass & group.confirmation_pass).sum()),
                            primary_candidates=int(group.primary_pass.sum())))
    source_paths = [manifest_path, calendar_path, ledger_path, reference_path, rights_path, name_path,
                    ROOT / 'research_protocol_v1.json', ROOT / 'research_stage_gates_v2.json',
                    ROOT / 'audits/data_revision_v5_registration.json']
    audit = dict(completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 spec_sha256=sha(HERE/'spec.json'), script_sha256=sha(__file__), self_tests=tests,
                 files_verified=len(file_audits), rows_used=sum(x['rows_used'] for x in file_audits),
                 data_maximum_date=max(x['maximum_date'] for x in file_audits if x['maximum_date']),
                 post_2023_rows_loaded_into_frames=0, asof_summary=summary,
                 inputs=[dict(path=str(p.relative_to(ROOT)),sha256=sha(p)) for p in source_paths],
                 global_gates_changed=False, economic_returns_computed=False,
                 caveat='Observed snapshot universe; delisted/absent security completeness not established. Retrospective corporate quality diagnostics, not a point-in-time executable universe.')
    dump(out/'audit.json', audit)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    print(frame.loc[frame.year.eq(2023) & frame.primary_pass, ['symbol','historical_name','lower','upper','traversals','second_half_frozen_coverage','score']].head(20).to_string(index=False), flush=True)
    if len(forward):
        print(forward.groupby(['year','horizon','status']).size().to_string(), flush=True)


if __name__ == '__main__':
    main()
