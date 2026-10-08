"""Five predeclared local threshold neighbours; retrospective median terminal wealth."""
from pathlib import Path
import sys,inspect,json,html
HERE=Path(__file__).resolve().parent;STAR=HERE.parent
sys.path.insert(0,str(STAR/'baseline_3_1_start_dates_100k_20261008'))
import run as ref
p=ref.p;s=ref.s;pd=p.pd;np=p.np
OUT=HERE/'results';END='2026-09-30'
CONFIGS=[('original',.63,.50),('up061',.61,.50),('up065',.65,.50),('stop048',.63,.48),('stop052',.63,.52)]

def main():
    OUT.mkdir(parents=True,exist_ok=True);p.OUT=OUT;s.OUT=OUT
    sha=p.sha(ref.SOURCE)
    protocol={'capital':500000,'starts':'all trading days2020-01-01..2020-06-30','end':END,'configs':CONFIGS,'objective':'median final asset; tie original then config order','training':False,'risk_limit':None,'interpretation':'retrospective full-history tuning, correlated accounts, NOT OOS','source_sha256':sha,'cost':'inherited original fixed .001 stamp, .0003min5 commission,.002slip; local proxy'}
    p.save(HERE/'protocol.json',protocol)
    snapshot=ref.BASE/'snapshots'/END
    manifest=json.loads((snapshot/'manifest.json').read_text(encoding='utf-8'))
    assert all(p.sha(snapshot/f)==v['sha256'] for f,v in manifest.items())
    ds,panels,meta=p.dataset(snapshot,'2020-01-01',END)
    ns=p.namespace(ref.SOURCE.read_text(encoding='utf-8'))
    models=[p.fast(json.loads(p.zlib.decompress(p.base64.b64decode(ns[k])))) for k in ['_EMBEDDED_MODEL_B64','_EMBEDDED_STOP_MODEL_B64']]
    ds=ds[ds.symbol.isin(models[0]['universe'])].copy()
    ds['p']=ns['_batch_probabilities'](models[0],ds[p.F].to_numpy());ds['stop']=ns['_batch_probabilities'](models[1],ds[p.F].to_numpy());ds['score']=ds.p-.22*ds.stop
    cand={name:s.candidates(ds,pt,st) for name,pt,st in CONFIGS}
    cache={}
    for folder in [STAR/'baseline_3_2',STAR/'baseline_3_rebuild_20261008/ablation',STAR/'baseline_3_1_start_dates_500k_20261008']:
        for f in folder.rglob('corporate_actions.json'):cache.update(json.loads(f.read_text(encoding='utf-8')))
    p.save(OUT/'corporate_actions.json',cache)
    actions=s.prepare_actions(panels,{x for c in cand.values() for v in c.values() for x in v},'2020-01-01',END)
    cal=pd.read_csv(p.DATA/'metadata/trade_calendar_20261004.csv')
    dates=pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_trading_day.eq(1),'calendar_date']))
    dates=dates[(dates>='2019-12-20')&(dates<=END)]
    src=inspect.getsource(p.replay.run_starts)
    src=src.replace("starts=dates[(dates>='2021-01-01')&(dates<='2021-03-31')]","starts=dates[(dates>='2020-01-01')&(dates<='2020-06-30')]")
    src=src.replace('                signal=float(prevday[s].close)*(r.adjust_ratio if np.isfinite(r.adjust_ratio) else 1.)','                signal=float(r.open)')
    src=src[:src.index('    out=pd.DataFrame(results)')]+'    return results,all_curves,all_trades,reference_differences\n'
    ns['_exit_action']=ref.old_exit
    summaries=[]
    for name,pt,st in CONFIGS:
        directory=OUT/name;directory.mkdir(exist_ok=True)
        env=dict(p.replay.__dict__);env.update(CASH=500000.,END=pd.Timestamp(END),OUT=directory)
        def progress(*args,**kwargs):
            if len(args)>1 and (args[1]%20==0 or args[1]==1):print(name,*args,flush=True)
        env['print']=progress;exec(src,env)
        results,curves,trades,diffs=env['run_starts']((ns,models,dates,panels,cand[name],meta,set()),actions)
        p.save(directory/'accounts.json',results)
        pd.concat(curves).to_parquet(directory/'daily_equity.parquet',index=False)
        pd.DataFrame(trades).to_parquet(directory/'trades.parquet',index=False)
        p.save(directory/'reference_differences.json',diffs)
        t=pd.DataFrame(results)
        assert len(t)==len(dates[(dates>='2020-01-01')&(dates<='2020-06-30')])
        durations=[]
        for c in curves:
            assert c.cash.min()>=-.01
            underwater=c.equity.to_numpy()<np.maximum.accumulate(np.r_[500000,c.equity.to_numpy()])[1:]-.001
            length=maximum=0
            for flag in underwater:
                length=length+1 if flag else 0;maximum=max(maximum,length)
            durations.append(maximum)
        summary={'name':name,'p':pt,'s':st,'accounts':len(t),'median_asset':float(t.final_asset.median()),'p10_asset':float(t.final_asset.quantile(.1)),'min_asset':float(t.final_asset.min()),'median_cagr':float(t.cagr.median()),'median_drawdown':float(-t.max_drawdown.median()),'worst_drawdown':float(-t.max_drawdown.min()),'loss_fraction':float(t.total_return.lt(0).mean()),'longest_underwater_sessions':max(durations)}
        summaries.append(summary);p.save(OUT/'summary.json',summaries);print('SUMMARY',json.dumps(summary),flush=True)
        if name=='original':
            previous=json.loads((STAR/'baseline_3_1_start_dates_500k_20261008/results/comparison.json').read_text(encoding='utf-8'))[0]
            assert np.isclose(results[0]['final_asset'],previous['final_asset'])
    best=max(summaries,key=lambda x:x['median_asset']);p.save(OUT/'selected.json',best)
    assert p.sha(ref.SOURCE)==sha
    p.save(OUT/'verification.json',{'passed':True,'configs':5,'accounts_per_config':summaries[0]['accounts'],'original_first_start_reproduced':True,'source_unchanged':True})
    rows=[]
    for r in sorted(summaries,key=lambda x:-x['median_asset']):
        vals=[r['name'],f"{r['p']}/{r['s']}",f"{r['median_asset']/10000:.2f}",f"{r['p10_asset']/10000:.2f}",f"{r['min_asset']/10000:.2f}",f"{r['median_cagr']:.2%}",f"{r['worst_drawdown']:.2%}",str(r['longest_underwater_sessions'])]
        rows.append('<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in vals)+'</tr>')
    (HERE/'report.html').write_text('<!doctype html><meta charset="utf-8"><style>body{font:16px Microsoft YaHei;margin:32px}td,th{padding:10px;border-bottom:1px solid #ddd}</style><h1>科创3-1：半年逐日起点中位资产微调</h1><p>本金50万元；2020上半年逐交易日启动，至2026-09-30。只比较预设5组，无模型重训。全区间历史选优，不是独立测试。高度重叠账户不能视为独立样本。</p><table><tr>'+''.join('<th>'+x+'</th>' for x in ['方案','上涨/止损门槛','中位资产万元','P10资产万元','最小资产万元','中位年化','最差回撤','最长水下交易日'])+'</tr>'+''.join(rows)+'</table><p>最长水下含截止日仍未恢复的区间。交易、税费、旧静态池与开盘价代理退出沿用旧近似，不是平台实测。等长跨年窗口、真实历史税费及压力测试不在本轮5组内。</p>',encoding='utf-8')
    print('COMPLETE',flush=True)

if __name__=='__main__':main()
