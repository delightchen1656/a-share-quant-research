"""Frozen 3-1, fourteen 100k starts; local opening-price interpretation, no training."""
from pathlib import Path
import sys,inspect,json,html
HERE=Path(__file__).resolve().parent
BASE=HERE.parent/'baseline_3_2/retrain_2022'
sys.path.insert(0,str(BASE/'search_1000'))
import search as s
p=s.p;pd=s.pd;np=s.np
OUT=HERE/'results'
SOURCE=HERE.parent/'supermind_baseline_3_1_high_attack_adaptive_expiry_daily.py'
END='2026-09-30'

def old_exit(price,state,amount,today,position_days):
    entry=state['entry']
    if price<=entry*.93:return 'STOP',0
    if price>=entry*1.34:return 'TPALL',0
    if price>=entry*1.24 and not state['half']:
        target=int(amount/2)
        return ('TPHALF',target) if target>=200 and amount-target>=200 else None
    age=(today-state['entry_date']).days if state['entry_date'] is not None else position_days
    if age>=60:return 'TIME60',0
    if age>=30 and price/entry-1<.10:return 'TIME30',0
    return None

def executor(panels,meta,start,actions):
    env=dict(s.__dict__);env['old_exit']=old_exit
    source=inspect.getsource(s.executor)
    source=source.replace("ns['g'].model={'max_positions':14,'top_per_day':8}","ns['g'].model={'max_positions':14,'top_per_day':8};ns['_exit_action']=old_exit")
    source=source.replace('prepared_days=days,print=', 'prepared_days=days,CASH=100000.,print=')
    needle="                signal=float(prevday[s].close)*(r.adjust_ratio if np.isfinite(r.adjust_ratio) else 1.)"
    replacement="                signal=float(r.open)"
    source=source.replace('    exec(src,env)',f'    assert {needle!r} in src\n    src=src.replace({needle!r},{replacement!r})\n    exec(src,env)')
    source=source.replace('/1e6-1','/100000.-1')
    exec(source,env)
    return env['executor'](panels,meta,start,END,actions)

def main():
    OUT.mkdir(exist_ok=True);s.OUT=OUT;p.OUT=OUT
    original_hash=p.sha(SOURCE)
    ns=p.namespace(SOURCE.read_text(encoding='utf-8'))
    models=[p.fast(json.loads(p.zlib.decompress(p.base64.b64decode(ns[k])))) for k in ['_EMBEDDED_MODEL_B64','_EMBEDDED_STOP_MODEL_B64']]
    assert models[0]['max_positions']==14 and models[0]['top_per_day']==8
    universe=set(models[0]['universe'])
    snapshot=BASE/'snapshots'/END
    manifest=json.loads((snapshot/'manifest.json').read_text())
    assert all(p.sha(snapshot/f)==v['sha256'] for f,v in manifest.items())
    ds,panels,meta=p.dataset(snapshot,'2020-01-01',END)
    ds=ds[ds.symbol.isin(universe)].copy()
    ns['g'].model=models[0]
    feature_checks=0
    for symbol,group in ds.groupby('symbol'):
        q=pd.read_parquet(snapshot/'qfq'/(symbol+'.parquet')).set_index('date')
        for _,row in group.iloc[[0,-1]].iterrows():
            frame=q.loc[:row.date].tail(121).rename(columns={'turn':'turnover_rate','amount':'turnover','pctChg':'quote_rate','isST':'is_st'}).copy()
            frame['is_st']=frame.is_st.astype(str).eq('1')
            f=ns['_last_features'](frame)
            assert f is not None and np.allclose(f,row[p.F].to_numpy(float),rtol=1e-6,atol=1e-7),(symbol,row.date)
            feature_checks+=1
    ds['p']=ns['_batch_probabilities'](models[0],ds[p.F].to_numpy())
    ds['stop']=ns['_batch_probabilities'](models[1],ds[p.F].to_numpy())
    ds['score']=ds.p-.22*ds.stop
    cand=s.candidates(ds,.63,.50)
    print('SCORED',len(ds),'feature_checks',feature_checks,flush=True)
    cache={}
    for f in (HERE.parent/'baseline_3_2').rglob('corporate_actions.json'):
        cache.update(json.loads(f.read_text(encoding='utf-8')))
    p.save(OUT/'corporate_actions.json',cache)
    actions=s.prepare_actions(panels,{x for v in cand.values() for x in v},'2020-01-01',END)
    p.save(HERE/'protocol.json',{'strategy':str(SOURCE),'sha256':original_hash,'cash':100000,'end':END,
        'starts':[f'{y}-{m}-01' for y in range(2020,2027) for m in ['01','07']],
        'model_training':False,'universe':'original embedded static pool','p_threshold':.63,'s_threshold':.50,
        'execution':'prior-session candidates; OPEN proxy for original platform last_price exits; fills at open+/-0.2%',
        'exit_precedence':'original partial-profit branch before expiry, including inability to sell half below400 shares',
        'commission':.0003,'minimum_commission':5,'sell_stamp':.001,'transfer_fee_separate':False,
        'dividend_tax':.20,'daily_volume_cap':.25,'max_order_shares':50000,'min_buy_shares':200,
        'annualization':'calendar days/365.25 from actual first session','sharpe':'daily returns,252 sessions,rf0',
        'count':'executed buy/sell records including partial exits, not completed roundtrips',
        'caveat':'local approximation, not platform replay or independent OOS; original models/static universe retained',
        'snapshot_manifest_sha256':p.sha(snapshot/'manifest.json')})
    rows=[]
    for year in range(2020,2027):
        for month in ['01','07']:
            start=f'{year}-{month}-01'
            result=executor(panels,meta,start,actions)(cand)
            s.save_run(start,result)
            metrics,curve,trades,_=result
            tx=trades[trades.side!='WRITE_OFF'].copy()
            stamp=float(tx.loc[tx.side!='BUY','amount'].sum()*.001)
            fees=float(tx.fee.sum())
            commission=float(np.maximum(5,tx.amount*.0003).sum())
            assert np.isclose(fees,commission+stamp)
            assert np.isclose(metrics['total_return'],curve.equity.iloc[-1]/100000-1)
            assert curve.cash.min()>=-.01 and tx.qty.between(1,50000).all()
            assert tx.loc[tx.side=='BUY','qty'].ge(200).all()
            for (date,symbol),g in tx.groupby(['date','symbol']):
                assert not ((g.side=='BUY').any() and (g.side!='BUY').any())
                assert g.qty.sum()<=int(panels[symbol].loc[date,'volume']*.25)
            row=dict(metrics,requested_start=start,executed_fills=len(tx),commission=commission,stamp_tax=stamp,total_fees=fees)
            rows.append(row);p.save(OUT/'comparison.json',rows)
            print('RESULT',start,round(metrics['final_asset'],2),round(metrics['cagr']*100,2),flush=True)
    assert p.sha(SOURCE)==original_hash
    p.save(OUT/'verification.json',{'passed':True,'runs':14,'feature_parity_checks':feature_checks,
        'frozen_source_unchanged':True,'snapshot_hashes_verified':len(manifest),'fee_reconciliation':True,'capital':100000})
    headers=['计划起点','实际起点','最终资产(元)','累计收益','年化收益','最大回撤','Sharpe','成交笔数','佣金(元)','印花税(元)','费用合计(元)']
    table=[]
    for x in rows:
        vals=[x['requested_start'],x['start'],f"{x['final_asset']:,.2f}",f"{x['total_return']:.2%}",f"{x['cagr']:.2%}",f"{abs(x['max_drawdown']):.2%}",f"{x['sharpe_rf0']:.2f}",str(x['executed_fills']),f"{x['commission']:,.2f}",f"{x['stamp_tax']:,.2f}",f"{x['total_fees']:,.2f}"]
        table.append('<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in vals)+'</tr>')
    page='<!doctype html><meta charset="utf-8"><title>科创3-1 10万元起点比较</title><style>body{font:15px Microsoft YaHei;margin:32px;color:#193149}table{border-collapse:collapse;width:100%}td,th{padding:10px;border-bottom:1px solid #ccd9e3;text-align:right}th{background:#e8f3f5}p{line-height:1.8}</style><h1>科创3-1：14个起点，独立10万元</h1><p>统一截止2026-09-30。旧模型、静态股票池、10%单票仓位；本地开盘价解释回放，不是SuperMind实测。</p><table><tr>'+''.join('<th>'+x+'</th>' for x in headers)+'</tr>'+''.join(table)+'</table><p>最大回撤为幅度。成交笔数为实际买卖记录数，包含分批退出。费用合计=佣金+印花税，不含滑点、分红扣税；费用已从净值扣除。佣金万三最低5元、卖出印花税全期千一，未单列过户费，属于历史税费近似。年化按实际开始至截止日的日历天数计算；不足一年年化仅作换算。完整假设见protocol.json。</p>'
    (HERE/'report.html').write_text(page,encoding='utf-8')
    print('COMPLETE',flush=True)

if __name__=='__main__':main()
