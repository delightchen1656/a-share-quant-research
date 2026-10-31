"""Evaluate the user's fixed keep rule, without further threshold search or deployment."""
from pathlib import Path
import json,datetime
import numpy as np
import pandas as pd
from research import INPUT,OUT,verify_inputs,sha

RESULT=OUT/'user_positive_base_volume15_v1'

def counts(f):
    bad=f.bad.to_numpy(bool);keep=f.keep_user_rule.to_numpy(bool)
    return dict(total=len(f),bad_total=int(bad.sum()),good_total=int((~bad).sum()),
        bad_removed=int((bad&~keep).sum()),good_removed=int((~bad&~keep).sum()),
        bad_kept=int((bad&keep).sum()),good_kept=int((~bad&keep).sum()),
        retained=int(keep.sum()),
        bad_removal_rate=float((bad&~keep).sum()/bad.sum()) if bad.sum() else None,
        good_false_removal_rate=float((~bad&~keep).sum()/(~bad).sum()) if (~bad).sum() else None,
        good_share_before=float((~bad).mean()) if len(f) else None,
        good_share_after=float((~bad&keep).sum()/keep.sum()) if keep.sum() else None)

def keep_rule(flat_net_change,volume_multiple):
    # Strictly positive base close-to-close change; inclusive 1.5x volume gate.
    return (np.asarray(flat_net_change)>0)&(np.asarray(volume_multiple)>=1.5)

def main():
    verify_inputs();assert not (RESULT/'RESULT.json').exists(),'Preserve this fixed-rule result.'
    RESULT.mkdir(parents=True,exist_ok=True)
    rule=dict(source='explicit_user_parameters',scope='existing_starred_mainboard_box_signals_only',
        keep_all_conditions=[dict(feature='flat_net_change',op='>',threshold=0),
                             dict(feature='volume_multiple',op='>=',threshold=1.5)],
        base_definition='C[t-1]/C[t-15]-1; prior15sessions, excluding signal day',
        signal_volume_definition='raw V[t] / mean raw V[t-15:t-1]',
        target='D+1..D+60maximumadjustedhigh/signalclose-1 <10% vs >=10%',
        incomplete='excluded, never treated as below10%',
        application='filter existing baseline1.2x signals AFTER same-box earliest dedup; no later-signal backfill',
        no_other_parameters_searched=True,production_change=False,nonleaders_unchanged=True,
        boundary='2024-12-31',audit_2024_already_seen_not_claimed_blind=True,
        recorded_at=datetime.datetime.now().isoformat())
    (RESULT/'RULE.json').write_text(json.dumps(rule,ensure_ascii=False,indent=2),encoding='utf-8')
    f=pd.read_parquet(INPUT/'features.parquet')
    label_paths=[INPUT/'labels_trainval.parquet',OUT/'sealed_labels.parquet']
    labels=pd.concat([pd.read_parquet(p) for p in label_paths],ignore_index=True)
    f=f.merge(labels.drop(columns='split'),on='event_id',validate='one_to_one')
    assert f.is_leader.all() and f.signal_date.le('2024-12-31').all() and f.label_end.le('2024-12-31').all()
    assert f[['flat_net_change','volume_multiple']].notna().all().all()
    f['keep_user_rule']=keep_rule(f.flat_net_change,f.volume_multiple)
    f['reject_base_not_rising']=f.flat_net_change.le(0)
    f['reject_volume_below15']=f.volume_multiple.lt(1.5)
    f['classification']=np.select([f.bad&~f.keep_user_rule,~f.bad&~f.keep_user_rule,f.bad&f.keep_user_rule],
        ['removed_below10','false_removed_reached10','kept_below10'],default='kept_reached10')
    result=dict(rule_sha256=sha(RESULT/'RULE.json'),inputs_sha256=sha(INPUT/'manifest.json'),
        label_files_sha256={p.name:sha(p) for p in label_paths},
        all_pre2025=counts(f),by_year=[dict(year=int(y),**counts(g)) for y,g in f.groupby('year')],
        original_37_development_cohort=counts(f[f.split.isin(['train','validation'])]),
        audit2024_historical_recheck=counts(f[f.year.eq(2024)]),
        false_removals=f.loc[(~f.bad)&(~f.keep_user_rule),['event_id','code','name','signal_date','flat_net_change','volume_multiple','peak_return60']].to_dict('records'),
        post2024_labels_not_read=True,viewer_unchanged=True,nonleader_signals_unchanged=True)
    # Reconcile every category and make equality at1.5 explicit.
    assert keep_rule([.01,.01,0,-.01],[1.5,1.4999,2,2]).tolist()==[True,False,False,False]
    c=result['all_pre2025']
    assert c['bad_removed']+c['bad_kept']==c['bad_total']
    assert c['good_removed']+c['good_kept']==c['good_total']
    assert c['total']==c['bad_total']+c['good_total']==58
    f.to_parquet(RESULT/'classified_events.parquet',index=False)
    (RESULT/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    lines=['用户指定规则：横盘上涨 + 信号量至少横盘均量1.5倍','',
        '仅过滤现有同箱去重后的★龙头信号，不补选同箱之后的信号。未搜索其他阈值，未修改软件。',
        '截至2024年底前完成60交易日观察的58次信号；2024此前已查看，本次不称盲测。','',
        '年份 | 原不足10% | 筛掉不足10% | 原达到10% | 误删达到10% | 最后保留']
    for r in result['by_year']:
        lines.append(f"{r['year']} | {r['bad_total']} | {r['bad_removed']} | {r['good_total']} | {r['good_removed']} | {r['retained']}")
    lines+=['',f"合计：筛掉低峰 {c['bad_removed']}/{c['bad_total']}={c['bad_removal_rate']:.2%}；误删达标 {c['good_removed']}/{c['good_total']}={c['good_false_removal_rate']:.2%}。",
        f"保留{c['retained']}次，其中达到10%有{c['good_kept']}次、不足10%有{c['bad_kept']}次。达到10%比例从{c['good_share_before']:.2%}变为{c['good_share_after']:.2%}。",'',
        '误删达到10%的信号（后60日最高涨幅为事后价格观察，不代表实际收益）：']
    for r in result['false_removals']:
        lines.append(f"{r['signal_date']} {r['code']} {r['name']}：最高{r['peak_return60']:.2%}；横盘{r['flat_net_change']:.2%}；信号量{r['volume_multiple']:.3f}倍")
    (RESULT/'结果说明.txt').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
