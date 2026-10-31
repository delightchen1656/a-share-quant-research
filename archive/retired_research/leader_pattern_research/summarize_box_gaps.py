"""Describe frozen 60-session price extremes by gap type, without changing selection."""
from pathlib import Path
import json,hashlib,argparse
import numpy as np
import pandas as pd
from box_gap_scan import CURRENT,read_or_scan,sha,report_dir

def pct(x):return '—' if x is None else f'{x:+.2%}'

def main(exclude_gain_ge=None):
    if exclude_gain_ge is not None:assert np.isfinite(exclude_gain_ge) and exclude_gain_ge>0
    before=CURRENT.read_bytes();bundle=json.loads(before)
    assert bundle.get('return_basis')=='next_session_open','Refuse to mix signal-close and next-open observations'
    assert sha(bundle['events'])==bundle['events_sha256']
    events=pd.read_parquet(bundle['events'])
    gaps=pd.DataFrame(read_or_scan(bundle))
    features=['event_id','gap_count','gap_up_count','gap_down_count','gap_unfilled_count']
    merged=events.merge(gaps[features],on='event_id',validate='one_to_one',how='left')
    assert len(merged)==len(events) and merged.gap_count.notna().all()
    assert (merged.peak_complete60==merged.trough_complete60).all()
    valid=merged.peak_complete60&merged.trough_complete60&np.isfinite(merged.peak_return60)&np.isfinite(merged.max_drop60)
    assert valid.sum()==merged.peak_complete60.sum()
    assert (merged.loc[valid,'max_drop60']>=0).all()
    extreme=valid&merged.peak_return60.ge(exclude_gain_ge) if exclude_gain_ge is not None else pd.Series(False,index=merged.index)
    retained=valid&~extreme
    masks=[('全部箱体',pd.Series(True,index=merged.index)),
        ('无确认跳空',merged.gap_count.eq(0)),
        ('仅向上跳空',merged.gap_up_count.gt(0)&merged.gap_down_count.eq(0)),
        ('仅向下跳空',merged.gap_down_count.gt(0)&merged.gap_up_count.eq(0)),
        ('上下都有',merged.gap_up_count.gt(0)&merged.gap_down_count.gt(0)),
        ('有跳空合计',merged.gap_count.gt(0)),
        ('含向上跳空（含双向）',merged.gap_up_count.gt(0)),
        ('含向下跳空（含双向）',merged.gap_down_count.gt(0)),
        ('仍有未补缺口',merged.gap_unfilled_count.gt(0)),
        ('所有缺口均已补',merged.gap_count.gt(0)&merged.gap_unfilled_count.eq(0))]
    rows=[]
    for scope,scope_mask in [('沪深主板全部',pd.Series(True,index=merged.index)),('★合并龙头',merged.is_leader.astype(bool))]:
        for name,mask in masks:
            group=merged[mask&scope_mask];full=merged[mask&scope_mask&retained]
            row=dict(scope=scope,condition=name,signals=len(group),stocks=int(group.code.nunique()),
                valid60=int((mask&scope_mask&valid).sum()),valid_stocks60=int(merged.loc[mask&scope_mask&valid,'code'].nunique()),
                excluded_extreme60=int((mask&scope_mask&extreme).sum()),retained60=len(full),
                retained_stocks60=int(full.code.nunique()),
                unfinished=int((~group.peak_complete60&group.peak_status60.eq('未满60日')).sum()),
                missing=int((~group.peak_complete60&group.peak_status60.eq('观察期缺价')).sum()),
                mean_max_gain60=float(full.peak_return60.mean()) if len(full) else None,
                mean_max_drop60=-float(full.max_drop60.mean()) if len(full) else None)
            assert row['signals']==row['valid60']+row['unfinished']+row['missing']
            assert row['valid60']==row['excluded_extreme60']+row['retained60']
            if exclude_gain_ge is not None:assert full.peak_return60.lt(exclude_gain_ge).all()
            rows.append(row)
        group_rows={r['condition']:r for r in rows if r['scope']==scope}
        for col in ['signals','valid60','excluded_extreme60','retained60']:
            assert sum(group_rows[n][col] for n in ['无确认跳空','仅向上跳空','仅向下跳空','上下都有'])==group_rows['全部箱体'][col]
            assert sum(group_rows[n][col] for n in ['仅向上跳空','仅向下跳空','上下都有'])==group_rows['有跳空合计'][col]
        for metric in ['mean_max_gain60','mean_max_drop60']:
            parts=[group_rows[n] for n in ['无确认跳空','仅向上跳空','仅向下跳空','上下都有']]
            weighted=sum(p[metric]*p['retained60'] for p in parts if p['retained60'])/group_rows['全部箱体']['retained60']
            assert np.isclose(weighted,group_rows['全部箱体'][metric],rtol=0,atol=1e-12)
    variant='extremes_summary_v1' if exclude_gain_ge is None else f'extremes_summary_exclude_gain_ge{exclude_gain_ge*100:g}_v1'
    out=report_dir(bundle)/variant;out.mkdir(exist_ok=True)
    spec=dict(cutoff=bundle['cutoff'],generation=bundle['generation'],source_events_sha256=bundle['events_sha256'],
        source_gap_cache_sha256=sha(report_dir(bundle)/'events.json'),
        window='D+1..D+60, excluding signal day; same complete paired cohort for both means',
        return_basis='next_session_open',
        mean_gain='arithmetic mean per signal of max(adjusted high)/strict D1 open - 1; negative observed highs retained',
        mean_drop='negative arithmetic mean per signal of max(0,1-min(adjusted low)/strict D1 open)',
        incomplete='unfinished or any missing quote excluded from both means; no imputation',
        weighting='each deduplicated box signal counts once; not equal-stock-weighted',
        exclude_gain_ge=exclude_gain_ge,exclude_rule='Remove entire paired observation when unrounded max gain >= threshold; recompute BOTH means on retained cohort.',
        current_pool_retrospective=True,no_account_performance=True,no_fees=True,
        descriptive_only=True,no_strategy_rule_or_model_changes=True)
    for name,data in [('SPEC.json',spec),('rows.json',rows)]:
        (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    text=[f"箱体跳空分类：60交易日价格极值，行情截至{bundle['cutoff']}",
        '均以信号次一交易日开盘为基准；最大跌幅显示负号，不是从区间最高点回落的最大回撤。',
        '按信号等权平均，涨跌采用同一完整60日样本；未到期或缺价剔除。',
        '仅描述现有名单回看历史的价格极值，不是可实现账户收益，不据此修改筛选。','']
    if exclude_gain_ge is not None:
        text.insert(1,f'剔除未四舍五入的60日最大涨幅≥{exclude_gain_ge:.0%}的完整信号；整条样本从涨幅和跌幅均值中同时移除，非截断为100%。')
    for scope in ['沪深主板全部','★合并龙头']:
        text.append(scope)
        text.append('情况 | 全部信号 | 原完整60日 | 极端剔除 | 剩余有效 | 未满60日 | 缺价 | 平均最大涨幅 | 平均最大跌幅')
        for r in rows:
            if r['scope']==scope:
                text.append(f"{r['condition']} | {r['signals']} | {r['valid60']} | {r['excluded_extreme60']} | {r['retained60']} | {r['unfinished']} | {r['missing']} | {pct(r['mean_max_gain60'])} | {pct(r['mean_max_drop60'])}")
        text.append('')
    text.append('无确认跳空、仅向上、仅向下、上下都有四类互斥；其余为合计或交叠子集，请勿重复相加。')
    (out/'箱体跳空分类平均涨跌幅.txt').write_text('\n'.join(text),encoding='utf-8')
    removed=merged.loc[extreme,['event_id','code','name','signal_date','is_leader','peak_return60','max_drop60','gap_count','gap_up_count','gap_down_count','gap_unfilled_count']].sort_values('peak_return60',ascending=False)
    (out/'excluded_signals.json').write_text(removed.to_json(orient='records',force_ascii=False,indent=2),encoding='utf-8')
    assert CURRENT.read_bytes()==before,'Viewer generation changed while summarizing'
    audit=dict(status='ok',signals=len(merged),paired_complete60=int(valid.sum()),excluded_extremes=int(extreme.sum()),retained60=int(retained.sum()),
        exactly_threshold=int((valid&merged.peak_return60.eq(exclude_gain_ge)).sum()) if exclude_gain_ge is not None else 0,source_unchanged=True,
        one_to_one_join=True,disjoint_group_counts_reconciled=True,weighted_means_reconciled=True,
        rows_sha256=sha(out/'rows.json'),spec_sha256=sha(out/'SPEC.json'),current_sha256=hashlib.sha256(before).hexdigest())
    (out/'AUDIT.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print('\n'.join(text),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--exclude-gain-ge',type=float,default=None)
    main(parser.parse_args().exclude_gain_ge)
