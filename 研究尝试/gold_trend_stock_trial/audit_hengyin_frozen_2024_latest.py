"""One-way audit of frozen Hengyin candidates. Outputs only to restricted directory."""

import sys as _layout_sys
from pathlib import Path as _LayoutPath
_layout_root=next(p for p in _LayoutPath(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
_layout_sys.path.insert(0,str(_layout_root/'tools'))
from workspace_paths import resolve_recorded_path
from pathlib import Path
from datetime import datetime,timezone
import json,shutil,math
import numpy as np
import pandas as pd
from run_woer_fixed import sha,save,metrics

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
PACKAGE=Path(__file__).resolve().parent
FREEZE=PACKAGE/'experiments/hengyin_return_max_round2_2018_2023/FROZEN_BEST.json'
OUT=PACKAGE/'holdout_restricted/hengyin_round2_audit_2024_latest'
KEYS=['fast','slow','entry_buffer','exit_buffer','breakout','stop','cooldown','entry_filter']

def run(q,r,cfg,rate=0.,fresh=False):
    f,s,eb,xb,b,stop,cool,flt=[cfg[k] for k in KEYS];assert flt=='none'
    c=q.close;fa=c.rolling(f).mean();sl=c.rolling(s).mean();hi=c.shift(1).rolling(b).max()
    warm=max(f,s,b+1)-1;start=int(q.date.lt('2024-01-01').sum()) if fresh else 0
    cash=1.;qty=0.;peak=0.;exit_i=-100000;pending=None;rows=[];fills=[];trades=[];live=None
    for i in range(start,len(q)):
        price=float(c.iloc[i]);op=float(q.open.iloc[i]);date=q.date.iloc[i]
        if pending:
            side,si=pending;rr=r.iloc[i];pc=float(rr.preclose);width=.05 if int(rr.isST) else .1
            upper=math.floor(pc*(1+width)*100+.5000001)/100;lower=math.floor(pc*(1-width)*100+.5000001)/100
            flag='UP_LIMIT_ESTIMATE' if rr.open>=upper-.005 else ('DOWN_LIMIT_ESTIMATE' if rr.open<=lower+.005 else '')
            fills.append(dict(side=side,signal_date=q.date.iloc[si],fill_date=date,fill_index=i,signal_index=si,qfq_open=op,raw_open=float(rr.open),limit_flag=flag,cost_bps=rate*10000))
            if side=='BUY':qty=cash*(1-rate)/op;cash=0.;live=dict(buy_date=date,buy_signal=q.date.iloc[si],buy_qfq=op,buy_index=i)
            else:
                cash=qty*op*(1-rate);qty=0.
                trades.append(dict(**live,sell_date=date,sell_signal=q.date.iloc[si],sell_qfq=op,return_=op/live['buy_qfq']*(1-rate)**2-1,status='CLOSED'));live=None
            pending=None
        nav=cash+qty*price
        rows.append(dict(date=date,nav=nav,holding=int(qty>0),qfq_close=price,cost_bps=rate*10000))
        if i<warm:continue
        if qty>0:
            peak=max(peak,price)
            if fa.iloc[i]<sl.iloc[i]*(1-xb) or price<peak*(1-stop):pending=('SELL',i);exit_i=i
        elif i>=exit_i+cool and (fa.iloc[i]>sl.iloc[i]*(1+eb) or (price>hi.iloc[i] and price>sl.iloc[i])):
            pending=('BUY',i);peak=price
    assert all(x['fill_index']==x['signal_index']+1 for x in fills)
    return pd.DataFrame(rows),fills,trades,live,pending

def evaluate(df,fills,trades,live,fresh):
    mask=df.date.ge('2024-01-01');loc=int(np.flatnonzero(mask.to_numpy())[0]);base=1. if fresh else float(df.nav.iloc[loc-1]);post=df.loc[mask].copy();post.nav/=base
    ann=[];prev=1.
    for y,g in post.groupby(post.date.str[:4]):
        a=metrics(g.nav,g.date,prev);ann.append(dict(year=int(y),return_pct=a['total_return_pct'],max_drawdown_pct=a['max_drawdown_pct']));prev=float(g.nav.iloc[-1])
    pf=[x for x in fills if x['fill_date']>='2024-01-01'];pt=[x for x in trades if x['sell_date']>='2024-01-01']
    result=dict(**metrics(post.nav,post.date,1.),first=post.date.iloc[0],last=post.date.iloc[-1],annual=ann,buy_fills=sum(x['side']=='BUY' for x in pf),sell_fills=sum(x['side']=='SELL' for x in pf),completed_trades=len(pt),win_rate_pct=float(np.mean([x['return_']>0 for x in pt])*100) if pt else None,open_position=live is not None,exposure_pct=float(post.holding.mean()*100),limit_flags=[x for x in pf if x['limit_flag']],start_mode='fresh cash; prior prices only for indicators' if fresh else 'carry frozen training-end position, pending order and cooldown; normalize prior close NAV to 1')
    return result,post,pf,pt

def main():
    OUT.mkdir(parents=True,exist_ok=True);freeze_hash=sha(FREEZE);frozen=json.loads(FREEZE.read_text(encoding='utf8'))
    candidates={'highest_gross':frozen['best_parameters'],'original_structure':frozen['post_search_structural_diagnostic']['parameters']}
    save(OUT/'AUDIT_PLAN.json',dict(frozen_file=str(FREEZE),frozen_sha256=freeze_hash,candidates=candidates,start='2024-01-01',cutoff='2026-10-30',primary='continuous frozen state; NAV normalized at final training close',secondary='independent flat start at first holdout open; first new signal at first holdout close',costs_bps=[0,5,10,20],parameter_search=False,send_results_to_development=False,price_basis='qfq gross fractional-share theoretical returns; not actual corporate-action accounting'))
    shutil.copyfile(FREEZE,OUT/'FROZEN_INPUT.json')
    audit=ROOT/'K线数据/更新备份与审计/20261030/audit.json';a=json.loads(audit.read_text(encoding='utf8'));assert a['status']=='ok' and a['target']=='2026-10-30'
    commit=json.loads((audit.parent/'commit_manifest.json').read_text(encoding='utf8'));frames=[];sources=[]
    for kind in ['qfq','raw']:
        src=ROOT/f'K线数据/沪深/{kind}/SH/603106.SH.parquet';dest=OUT/f'603106_{kind}.parquet'
        assert any(x['destination']==str(src.relative_to(ROOT)).replace('\\','/') for x in commit['files'])
        before=sha(src);shutil.copyfile(src,dest);assert sha(src)==sha(dest)==before;sources.append(dict(source=str(src),snapshot=str(dest),sha256=before))
        z=pd.read_parquet(dest);z['date']=pd.to_datetime(z.date).dt.strftime('%Y-%m-%d')
        for col in ['open','high','low','close','preclose','volume','tradestatus','isST']:z[col]=pd.to_numeric(z[col],errors='raise')
        assert z.date.is_unique and z.date.is_monotonic_increasing and z.date.max()=='2026-10-30';frames.append(z)
    q,r=frames;assert q.date.tolist()==r.date.tolist()
    white=PACKAGE/'inputs_pre2025/hengyin_2018_2023/WHITELIST.json';w=json.loads(white.read_text(encoding='utf8'));wp=resolve_recorded_path(w['files'][0]['path']);assert sha(wp)==w['files'][0]['sha256'];old=pd.read_parquet(wp);old['date']=pd.to_datetime(old.date).dt.strftime('%Y-%m-%d')
    # A uniform price-unit conversion eliminates later qfq scaling from the
    # training state; only ratios and scale-invariant indicators are evaluated.
    common=q[q.date.le('2023-12-31')].reset_index(drop=True);assert common.date.tolist()==old.date.tolist()
    scale=float(old.close.iloc[-1]/common.close.iloc[-1]);cols=['open','high','low','close']
    assert np.allclose(common[cols].to_numpy()*scale,old[cols].to_numpy(),rtol=1e-10,atol=1e-8)
    for col in cols+['preclose']:q[col]*=scale
    good=q.tradestatus.eq(1)&q.volume.gt(0);q=q[good].reset_index(drop=True);r=r[good].reset_index(drop=True)
    summaries={};costrows=[];allannual=[]
    for label,cfg in candidates.items():
        for fresh in [False,True]:
            mode='fresh' if fresh else 'carry';key=label+'_'+mode
            for bps in [0,5,10,20]:
                df,ff,tt,live,pending=run(q,r,cfg,bps/10000,fresh)
                if bps==0 and not fresh:
                    training_end=float(df.loc[df.date.le('2023-12-31'),'nav'].iloc[-1]);expected=frozen['best']['cumulative_return'] if label=='highest_gross' else frozen['post_search_structural_diagnostic']['result']['cumulative_return'];assert np.isclose(training_end-1,expected,rtol=1e-11,atol=1e-11)
                result,post,pf,pt=evaluate(df,ff,tt,live,fresh)
                if bps==0:
                    summaries[key]=result;post.to_csv(OUT/f'{key}_nav.csv',index=False,encoding='utf-8-sig');pd.DataFrame(pf).to_csv(OUT/f'{key}_fills.csv',index=False,encoding='utf-8-sig');pd.DataFrame(pt).to_csv(OUT/f'{key}_trades.csv',index=False,encoding='utf-8-sig')
                    for row in result['annual']:allannual.append(dict(version=label,start_mode=mode,**row))
                costrows.append(dict(version=label,start_mode=mode,one_way_bps=bps,total_return_pct=result['total_return_pct'],cagr_pct=result['cagr_pct'],max_drawdown_pct=result['max_drawdown_pct']))
    # Same previous-close normalization as the continuous strategies.
    idx=int(q.date.lt('2024-01-01').sum());dates=q.date.iloc[idx:].reset_index(drop=True)
    bh=pd.DataFrame(dict(date=dates,nav=q.close.iloc[idx:].to_numpy()/q.close.iloc[idx-1]));b=metrics(bh.nav,bh.date,1.);ann=[];prev=1.
    for y,g in bh.groupby(bh.date.str[:4]):
        v=metrics(g.nav,g.date,prev);ann.append(dict(year=int(y),return_pct=v['total_return_pct'],max_drawdown_pct=v['max_drawdown_pct']));prev=float(g.nav.iloc[-1])
    summaries['buyhold_carry']=dict(**b,annual=ann);bh.to_csv(OUT/'buyhold_nav.csv',index=False,encoding='utf-8-sig')
    assert sha(FREEZE)==freeze_hash
    save(OUT/'RESULT.json',summaries);pd.DataFrame(allannual).to_csv(OUT/'annual.csv',index=False,encoding='utf-8-sig');pd.DataFrame(costrows).to_csv(OUT/'cost_sensitivity.csv',index=False,encoding='utf-8-sig')
    save(OUT/'VALIDATION.json',dict(passed=True,frozen_unchanged=True,training_prefix_reconciled=True,uniform_qfq_scale=scale,training_ohlc_consistency=True,strict_next_quoted_bar_fills=True,no_optimization=True,cutoff='2026-10-30'))
    save(OUT/'MANIFEST.json',dict(created_at=datetime.now(timezone.utc).isoformat(),inputs=sources,frozen_sha256=freeze_hash,market_audit_sha256=sha(audit),script_sha256=sha(Path(__file__)),outputs={p.name:sha(p) for p in OUT.iterdir() if p.suffix in ['.csv','.json'] and p.name!='MANIFEST.json'}))
    print(json.dumps(summaries,ensure_ascii=False,indent=2));print(pd.DataFrame(costrows).to_string(index=False))

if __name__=='__main__':main()
