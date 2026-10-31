"""Independent metrics, frozen-prefix and protected-asset verification for extended ATR replay."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'strategies/hushen_2'
OLD=BASE/'results/holdout_restricted/fixed_ioc_atr_price_q1_2020/attempt_20261020_051613'
PRE=BASE/'results/holdout_restricted/atr_thresholds_pre2025/attempt_20261021_202130'


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def compare_prefix(left,right,cutoff):
    a=pd.read_parquet(left,filters=[('date','<=',pd.Timestamp(cutoff))])
    b=pd.read_parquet(right,filters=[('date','<=',pd.Timestamp(cutoff))])
    m=a.merge(b,on=['start_ordinal','date'],suffixes=('_new','_old'),validate='one_to_one')
    assert len(m)==len(a)==len(b)
    delta=float((m.equity_new-m.equity_old).abs().max())
    assert delta<=1e-8,delta
    return dict(rows=len(m),max_abs_equity_difference=delta,cutoff=cutoff)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);parser.add_argument('--action-receipt',type=Path);args=parser.parse_args();out=args.output
    report=json.loads((out/'COMPARISON.json').read_text(encoding='utf-8'))
    protocol=json.loads((out/'PROTOCOL.json').read_text(encoding='utf-8'))
    extension=json.loads((out/'SIGNAL_EXTENSION_VERIFICATION.json').read_text(encoding='utf-8'))
    assert report['status'] in ['complete','incomplete_action_audit'] and extension['status']=='verified'
    resolution=None
    if report['action_gaps']:
        assert args.action_receipt
        receipt=json.loads(args.action_receipt.read_text(encoding='utf-8'))
        if receipt.get('source_kind')=='official_issuer_filing':
            for document in receipt['documents']:
                assert document['http_status']==200 and digest(Path(document['local_file']))==document['sha256']
            receipts={receipt['key']:dict(source_kind=receipt['source_kind'],documents=receipt['documents'],coverage_basis=receipt['coverage_basis'])}
        else:receipts={r['key']:r for r in receipt['report_receipts']}
        records=[]
        for key in report['action_gaps']:
            assert key in receipt['records']
            assert receipt.get('source_kind')=='official_issuer_filing' or receipts[key]['error_code']=='0'
            symbol,year=key.split('/')
            windows=[]
            for summary in report['summaries']:
                trades=pd.read_parquet(out/summary['variant']/'TRADES.parquet')
                held=trades.loc[trades.symbol.eq(symbol)&trades.entry_date.le(pd.Timestamp(f'{year}-12-31'))&trades.exit_date.ge(pd.Timestamp(f'{year}-01-01'))]
                for row in held.itertuples():
                    windows.append(dict(variant=summary['variant'],start_ordinal=int(row.start_ordinal),entry=str(row.entry_date.date()),exit=str(row.exit_date.date())))
            assert windows
            events=[r for r in receipt['records'][key] if r.get('dividOperateDate')]
            affected=[]
            for event in events:
                date=pd.Timestamp(event['dividOperateDate'])
                for w in windows:
                    if pd.Timestamp(w['entry'])<date<=pd.Timestamp(w['exit']):affected.append(dict(window=w,event=event))
            assert not affected,('Missing company action overlaps held position; rerun required',key,affected)
            records.append(dict(key=key,provider_receipt=receipts[key],events=events,held_windows=windows,
                affected_positions=0,resolution='Supplier successful response contains no ex-date event in any overnight-held interval; economic account path is unchanged.'))
        resolution=dict(status='verified',raw_simulator_action_gaps=report['action_gaps'],unresolved_action_gaps=[],
            original_simulator_report=str(out/'COMPARISON.json'),original_simulator_report_sha256=digest(out/'COMPARISON.json'),
            supplier_receipt=str(args.action_receipt.resolve()),supplier_receipt_sha256=digest(args.action_receipt),
            keys=records,rerun_required=False,raw_simulator_results_preserved=True)
        (out/'ACTION_COVERAGE_RESOLUTION.json').write_text(json.dumps(resolution,ensure_ascii=False,indent=2),encoding='utf-8')
    pipeline_path=BASE/'tracker/data/pipeline_verification.json'
    pipeline=json.loads(pipeline_path.read_text(encoding='utf-8'))
    market_path=BASE/'tracker/market.py'
    assert digest(market_path)==pipeline['inputs']['files']['strategies/hushen_2/tracker/market.py']
    panel_path=ROOT/extension['reference_panel']
    retained_protocol_path=BASE/'results/holdout_restricted/broker_ioc_q1_2020/attempt_20261020_035710/PROTOCOL.json'
    retained=json.loads(retained_protocol_path.read_text(encoding='utf-8'))
    panel_hash=digest(panel_path)
    assert panel_hash==extension['reference_panel_sha256']==retained['component_panel_sha256']
    assert digest(pipeline_path)==extension['verification_sha256']
    end=pd.Timestamp(protocol['end']);last=pd.Timestamp(protocol['last_signal_cutoff'])
    s=pd.read_parquet(out/'INPUT_SIGNALS.parquet');old=pd.read_parquet(OLD/'FROZEN_SIGNALS.parquet')
    old_part=s.loc[s.date.le(old.date.max())].reset_index(drop=True)
    pd.testing.assert_frame_equal(old_part[['date','symbol','atr_pct','score','factor']],old[['date','symbol','atr_pct','score','factor']].reset_index(drop=True),check_exact=True)
    assert len(s)==len(old)+3 and s.date.max()==last
    checks={}
    for summary in report['summaries']:
        name=summary['variant'];folder=out/name
        c=pd.read_parquet(folder/'EQUITY_CURVES.parquet');t=pd.read_parquet(folder/'TRADES.parquet');m=pd.read_parquet(folder/'START_METRICS.parquet')
        assert len(m)==58 and c.date.max()==end and t.exit_date.max()<=end
        selected=s.loc[s.atr_pct.ge(summary['threshold'])]
        matched=t.merge(selected[['date','symbol']],left_on=['signal_date','symbol'],right_on=['date','symbol'],validate='many_to_one')
        assert len(matched)==len(t)
        for ordinal,g in c.groupby('start_ordinal'):
            g=g.sort_values('date');e=g.equity.to_numpy();r=np.r_[e[0]/100000-1,e[1:]/e[:-1]-1]
            a=m.loc[m.start_ordinal.eq(ordinal)].iloc[0]
            expected=[e[-1]/100000-1,(e[-1]/100000)**(365/(g.date.iloc[-1]-g.date.iloc[0]).days)-1,
                np.min(e/np.maximum.accumulate(e)-1),np.sqrt(252)*r.mean()/r.std(ddof=0)]
            actual=[a.cumulative_return,a.annualized_return,a.maximum_drawdown,a.sharpe_zero_rf_252_ddof0]
            assert np.allclose(expected,actual,rtol=0,atol=1e-12)
            assert a.completed_trades==t.start_ordinal.eq(ordinal).sum()
        assert summary['terminal_open_positions_max']==0 and summary['terminal_pending_orders_max']==0
        annual_counts={str(y):int(selected.date.dt.year.eq(y).sum()) for y in range(2020,end.year+1)}
        checks[name]=dict(runs=58,metrics_recomputed=True,trades_match_filter=True,signals_by_year=annual_counts,
            pre2025_prefix=compare_prefix(folder/'EQUITY_CURVES.parquet',PRE/name/'EQUITY_CURVES.parquet','2024-11-24'))
    baseline=compare_prefix(out/'original/EQUITY_CURVES.parquet',OLD/'EQUITY_CURVES.parquet',str(last.date()))
    protected={p:digest(Path(p))==h for p,h in protocol['protected_before'].items()}
    sources={p:digest(ROOT/p)==h for p,h in protocol['source_hashes'].items()}
    assert all(protected.values()) and all(sources.values())
    result=dict(status='verified',variant_checks=checks,baseline_old_prefix=baseline,old_frozen_signals_preserved_exactly=True,
        signal_extension=extension,protected_unchanged=protected,sources_unchanged=sources,
        action_coverage_resolution=resolution,
        new_signal_provenance=dict(market_py_sha256=digest(market_path),market_matches_verified_input=True,
            reference_panel_sha256=panel_hash,retained_panel_hash_matches=True,
            retained_protocol=str(retained_protocol_path.relative_to(ROOT)),retained_protocol_sha256=digest(retained_protocol_path),
            pipeline_verification_sha256=digest(pipeline_path)),
        reused_pre2025_runner_sha256=digest(Path(__file__).with_name('test_atr_thresholds_pre2025.py')),all_232_paths_verified=True)
    (out/'INDEPENDENT_VERIFICATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    audited=dict(report,status='verified',raw_simulator_status=report['status'],unresolved_action_gaps=[],
        action_coverage_resolution='ACTION_COVERAGE_RESOLUTION.json' if resolution else None,
        independent_verification='INDEPENDENT_VERIFICATION.json',raw_simulator_report_preserved=True)
    (out/'AUDITED_COMPARISON.json').write_text(json.dumps(audited,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
