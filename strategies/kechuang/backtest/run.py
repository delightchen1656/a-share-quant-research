"""科创基准1：冻结动态旧版，50万元、14个半年起点，不训练不调参。"""
from pathlib import Path
import json, html
import data_helpers as p
import engine as e
HERE=Path(__file__).resolve().parent
STAR=HERE.parent
OUT=STAR/'results/latest'
END='2026-09-30'
def main():
    OUT.mkdir(parents=True,exist_ok=True);e.OUT=OUT
    source=STAR/'supermind_kechuang_1.py'
    provenance=json.loads((STAR/'research/provenance.json').read_text(encoding='utf-8'))
    assert p.sha(source)==provenance['platform_sha256'],'Platform changed; revalidate before replay'
    snap=HERE/'data/snapshot_20260930'
    manifest=json.loads((snap/'manifest.json').read_text(encoding='utf-8'))
    assert all(p.sha(snap/f)==v['sha256'] for f,v in manifest.items())
    print('Verified frozen platform and snapshot; computing features',flush=True)
    ns=p.namespace(source.read_text(encoding='utf-8-sig'))
    models=[p.fast(json.loads(p.zlib.decompress(p.base64.b64decode(ns[k])))) for k in ['_EMBEDDED_MODEL_B64','_EMBEDDED_STOP_MODEL_B64']]
    ds,panels,meta=p.dataset(snap,'2020-01-01',END)
    ds=ds[ds.symbol.isin(models[0]['universe'])].copy()
    ds['p']=ns['_batch_probabilities'](models[0],ds[p.F].to_numpy())
    ds['stop']=ns['_batch_probabilities'](models[1],ds[p.F].to_numpy())
    ds['score']=ds.p-.22*ds.stop
    eligible=ds[(ds.p>=.63)&(ds.stop<=.50)].sort_values(['date','score','symbol'],ascending=[True,False,True])
    cand={d:list(g.head(8).symbol) for d,g in eligible.groupby('date')}
    p.save(OUT/'corporate_actions.json',json.loads((HERE/'data/corporate_actions.json').read_text(encoding='utf-8')))
    actions=e.actions([])
    cal=p.pd.read_csv(p.DATA/'metadata/trade_calendar_20261004.csv')
    dates=p.pd.DatetimeIndex(p.pd.to_datetime(cal.loc[cal.is_trading_day.eq(1),'calendar_date']))
    dates=dates[(dates>='2019-12-20')&(dates<=END)]
    ns['_exit_action']=e.old_exit
    models[0]['max_positions']=14
    reference=json.loads((STAR/'research/reference_metrics.json').read_text(encoding='utf-8'))
    rows=[]
    for y in range(2020,2027):
        for m in ['01','07']:
            start=f'{y}-{m}-01'
            metrics,curve,tx,diffs=e.run_starts((ns,models,dates,panels,cand,meta,set()),actions,start)
            metrics.update(requested_start=start,fees=float(tx.fee.sum()))
            assert curve.cash.min()>=-.01 and tx.loc[tx.side=='BUY','qty'].ge(200).all()
            prior=next(r for r in reference if r['start']==start)
            for k in ['final_asset','total_return','cagr','max_drawdown','sharpe_rf0','avg_exposure','fills','fees']:
                assert p.np.isclose(metrics[k],prior[k],rtol=1e-10,atol=1e-7),(start,k,metrics[k],prior[k])
            dest=OUT/start;dest.mkdir(exist_ok=True)
            p.save(dest/'metrics.json',metrics);curve.to_parquet(dest/'daily_equity.parquet',index=False)
            tx.to_parquet(dest/'trades.parquet',index=False);p.save(dest/'reference_price_differences.json',diffs)
            rows.append(metrics);p.save(STAR/'results/summary.json',rows)
            print('PARITY PASS',start,round(metrics['final_asset'],2),flush=True)
    p.save(OUT/'verification.json',dict(runs=14,reference_parity=True,models_retrained=False,platform_unchanged=p.sha(source)==provenance['platform_sha256'],platform_tested=False))
    headers=['入场日','最终资产（万元）','累计收益','年化收益','最大回撤','Sharpe','平均仓位','成交笔数','费用（元）']
    table='<tr>'+''.join('<th>'+v+'</th>' for v in headers)+'</tr>'
    for r in rows:
        vals=[r['requested_start'],f"{r['final_asset']/10000:,.2f}",f"{r['total_return']:.2%}",f"{r['cagr']:.2%}",f"{abs(r['max_drawdown']):.2%}",f"{r['sharpe_rf0']:.3f}",f"{r['avg_exposure']:.2%}",str(r['fills']),f"{r['fees']:,.2f}"]
        table+='<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in vals)+'</tr>'
    (STAR/'results/report.html').write_text('<!doctype html><meta charset="utf-8"><title>科创基准1本地回放</title><style>body{font:15px Microsoft YaHei;margin:30px}td,th{padding:9px;border-bottom:1px solid #ddd}table{border-collapse:collapse}</style><h1>科创基准1：旧动态原版</h1><p>50万元独立空仓；每日；现金不足整笔跳过；截至2026-09-30。本地日线近似，非平台或实盘收益。14起点与重构前逐项数值一致。</p><table>'+table+'</table><p>费用为佣金与旧引擎千一卖出印花税合计；滑点进入成交价、分红税另计。保留旧费率近似以验证重构不改变结果，不代表券商精确口径。重叠起点不是独立测试。</p>',encoding='utf-8')
if __name__=='__main__':main()
