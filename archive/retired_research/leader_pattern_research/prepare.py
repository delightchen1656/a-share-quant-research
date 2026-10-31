"""Independent three-pattern study: freeze scope and inventory, no signal results."""
from pathlib import Path
import json,hashlib,datetime
import pandas as pd
import pyarrow.parquet as pq

BASE=Path(__file__).resolve().parent
ROOT=BASE.parent
OUT=BASE/'holdout_restricted/patterns_v1';OUT.mkdir(parents=True,exist_ok=True)
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(path,x):Path(path).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def date_range(path):
    p=pq.ParquetFile(path);column=p.schema_arrow.names.index('date')
    bounds=[]
    for n in range(p.num_row_groups):
        stat=p.metadata.row_group(n).column(column).statistics
        if stat and stat.has_min_max:bounds.append((str(stat.min),str(stat.max)))
    return dict(rows=p.metadata.num_rows,first=min(a for a,b in bounds) if bounds else None,last=max(b for a,b in bounds) if bounds else None)

def main():
    assert not (OUT/'REQUEST.json').exists(),'Retain registered study scopes'
    source=ROOT/'outputs/industry_linkage_screen_20261027/holdout_restricted/user_woer_benchmark_v2/qualified_stocks.parquet'
    data=pd.read_parquet(source)
    pool=data[['code','name','board','board_code']].rename(columns={'board':'screen_best_board'})
    assert len(pool)==185 and pool.code.nunique()==185
    pool.to_parquet(OUT/'frozen_pool_185.parquet',index=False)
    pool.to_csv(OUT/'frozen_pool_185.csv',index=False,encoding='utf-8-sig')
    audit=ROOT/'data_updates/20261026/audit.json';meta=ROOT/'sh_sz_market_research/data_pipeline/data/metadata/refresh_20261026.json'
    status=json.loads(audit.read_text(encoding='utf-8'));assert status['status']=='ok' and status['target']=='2026-10-26'
    assert json.loads(meta.read_text(encoding='utf-8'))['status']=='ok'
    inventory=[]
    for row in pool.itertuples():
        symbol=row.code+('.SH' if row.code.startswith('6') else '.SZ')
        folder=ROOT/'evening_accumulation/data' if row.code.startswith('688') else ROOT/'sh_sz_market_research/data_pipeline/data'
        suffix=Path(symbol+'.parquet') if row.code.startswith('688') else Path('SH' if row.code.startswith('6') else 'SZ')/(symbol+'.parquet')
        r=dict(code=row.code,name=row.name,symbol=symbol)
        for mode in ['raw','qfq']:
            p=folder/mode/suffix
            r[mode]=dict(available=p.exists(),path=str(p),**(date_range(p) if p.exists() else {}))
        inventory.append(r)
    dump(OUT/'daily_data_inventory.json',dict(candidates=185,local_raw_available=sum(r['raw']['available'] for r in inventory),
        local_qfq_available=sum(r['qfq']['available'] for r in inventory),stocks=inventory,
        protected_market_commit_sha256=sha(audit),metadata_sha256=sha(meta),
        no_core_data_updated_or_modified=True,no_old_strategy_models_or_results_read=True))
    request=dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        authorization='User asks three independent pattern backtests within the185selected board-indicator stocks.',
        fixed_pool_rows=185,pool_source_sha256=sha(source),pool_snapshot_sha256=sha(OUT/'frozen_pool_185.parquet'),
        pool_definition_date='2026-10-27',pool_price_screen_cutoff='2026-10-26',
        proposed_replay_start='2019-01-01',available_committed_end='2026-10-26',
        bias='Current185names were selected using recent relationships. Historical replay has ex-post universe selection bias; do not call this a clean historical point-in-time pool or a new blind test.',
        first=dict(user_rule='五连跌筑底3连阳回来，然后后续2个月的价格',
            pending='Definition of five declines, three positive candles and bottom confirmation. Proposed future horizon40exchange sessions.'),
        second=dict(user_rule='首板如果开板，按照涨停价格买入成功；后续每天查询分时，如果再尾盘开板就卖出',
            hypothetical_entry='User explicitly assumes full fill at upper limit after opening; this is a hypothetical fill, not orderbook certification.',
            pending='Tail session boundary, minute-resolution approximation and exit when no later afternoon opening occurs. Tplus1 always respected.',
            data='Historical minute prices and contemporaneous legal price limits required. Daily high/low cannot replace ordered intraday paths.'),
        third=dict(user_rule='上涨行情中，小阴跌之后次日放量上涨买入，间隔五个交易日卖出',
            pending='Trend, pullback, volume threshold and order timing; proposed MA20/MA60,1-3negativecandles,1.5timesprior20volume,nextopen,D+5close awaiting reply.'),
        initial_output='First show independent signal counts, forward paths and per-event horizon returns; account aggregation requires explicit position/conflict assumptions, never substitute event mean for account CAGR.',
        corporate_actions='Shape features use documented adjusted prices. Executable prices use raw quotes; held shares/cash actions/record,paymentandlistingdates must be reconciled before economic net return claims.',
        rule_freeze_status='Pending three concise user clarifications. No new pattern signals or returns computed.',
        independent_of_existing_strategies=True,no_stopped_strategy_restored=True,no_broker_or_production_changes=True)
    dump(OUT/'REQUEST.json',request)
    print('Frozen scope185stocks; localraw',sum(r['raw']['available'] for r in inventory),'qfq',sum(r['qfq']['available'] for r in inventory),'cutoff2026-10-26; patternparameterspending.',flush=True)

if __name__=='__main__':main()
