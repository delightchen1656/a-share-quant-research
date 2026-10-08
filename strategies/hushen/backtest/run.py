"""Single local entry. Daily execution approximation; platform callbacks tested separately."""
from pathlib import Path
import sys,json,hashlib,html
import pandas as pd
import engine as e
HOME=Path(__file__).resolve().parents[1]

def main():
    manifest=json.loads((HOME/'research/migration.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((HOME/'supermind_hushen_1.py').read_bytes()).hexdigest()==manifest['entry_sha256'], 'Strategy changed: rebuild and validate rankings first'
    for relative,expected in manifest['runtime_input_hashes'].items():
        assert hashlib.sha256((HOME/relative).read_bytes()).hexdigest()==expected, 'Frozen input changed: '+relative
    market=e.Market();results=[]
    try:
        for year in range(2020,2027):
            for month in (1,7):
                start='%d-%02d-01'%(year,month)
                result,_=e.simulate(market,start,'2026-09-30',save='start_'+start)
                result['version']='Hushen1 D7f; cached signals daily ledger'
                results.append(result)
                e.r.dump('halfyear_results.json',results)
    finally:market.actions.close()
    frame=pd.DataFrame(results)
    columns=['requested_start','actual_start','end','initial_cash','final_equity','total_return','cagr','max_drawdown','sharpe','trades','total_cost']
    frame[columns].to_csv(HOME/'results/summary.csv',index=False,encoding='utf-8-sig')
    page='<meta charset="utf-8"><title>沪深1 本地回测</title><style>body{font:16px sans-serif;margin:32px}td,th{padding:8px;border:1px solid #ddd}table{border-collapse:collapse}</style><h1>沪深1 · D7f</h1><p>10万元独立账户，统一至2026-09-30。日线近似撮合，不是平台实测。排名来自冻结因子缓存；盘前取数兼容性另由回调测试验证。</p><p>费用已扣除，末日不强制平仓。保留历史数据与选优边界，不宣称独立未见盲测。原详细审计见归档。</p>'+frame[columns].to_html(index=False,float_format=lambda x:'%.6f'%x)
    (HOME/'results/report.html').write_text(page,encoding='utf-8')
    print('COMPLETE',HOME/'results/report.html')
if __name__=='__main__':main()
