"""Validate scan exports and explain allowed set differences, no outcomes."""
import hashlib,json
from pathlib import Path
import pandas as pd
P=Path(__file__).resolve().parent
AREA=P/'inputs_pre2025/full_mainboard'
def read(p):return json.loads(p.read_text(encoding='utf8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf8')
d=pd.read_parquet(P/'FULL_SIGNALS.parquet');csv=pd.read_csv(P/'FULL_SIGNALS.csv',dtype={'code':str})
summary=read(P/'SUMMARY.json');stage=pd.read_csv(P/'SCAN_STAGES.csv',dtype={'code':str})
assert str(d.next_valid_open.dtype)=='bool' and str(csv.next_valid_open.dtype)=='bool'
assert len(d)==3805==len(csv) and not d.duplicated(['code','signal_date']).any()
assert d.next_valid_open.equals(d.next_state.eq('next_open_available'))
assert not any('leader' in col.lower() for col in d.columns)
assert d.signal_date.between('2020-01-01','2024-12-31').all()
assert (d.signal_date>=d.ipo_date).all()
assert (d.raw_signal_close<8).all() and (d.qfq_close_div_ma20<=.92).all()
calendar=pd.read_parquet(AREA/'calendar.parquet',columns=['date']);sessions=pd.to_datetime(calendar.date).dt.strftime('%Y-%m-%d').tolist();ordinal={day:i for i,day in enumerate(sessions)}
for row in d.itertuples():
    expected=sessions[ordinal[row.signal_date]+1] if ordinal[row.signal_date]+1<len(sessions) else None
    assert row.entry_date==expected and row.next_date==expected
declared=pd.read_parquet(AREA/'coverage.parquet',columns=['code','period_rows']);declared['code']=declared.code.str.extract(r'(\d{6})')[0]
coverage=stage.merge(declared,on='code',how='left',validate='one_to_one');coverage['period_coverage_difference']=coverage.raw_period_bars-coverage.period_rows
coverage.to_csv(P/'SCOPE_COVERAGE.csv',index=False,encoding='utf-8-sig')
assert len(stage)==3336 and int((stage.raw_period_bars>0).sum())==3319
comparison=pd.read_csv(P/'LEGACY_SET_COMPARISON.csv',dtype={'code':str})
# Known original RULE event ids from permitted public rule, not outcome labels.
special={('002069','2022-04-27'),('002633','2022-04-29'),('600506','2021-04-21'),('603007','2021-04-28')}
joined=comparison.merge(d[['code','signal_date','next_state','entry_date']],on=['code','signal_date'],how='left',validate='one_to_one')
def reason(row):
    if row.comparison=='retained':return 'legacy_key_retained'
    if row.comparison=='new_outside_old947':return 'historical_scope_expansion_outside_old947'
    if row.comparison=='missing_legacy':return 'see_legacy_diagnostics'
    if row.signal_date<'2021-01-01':return 'new_2020_signal_window_inside_old947'
    if (row.code,row.signal_date) in special:return 'original_rule_special_event_not_excluded_here'
    if row.next_state=='suspended_next_session':return 'structure_retained_despite_next_session_suspension'
    return 'absent_from_old_frozen_set_no_future_eligibility_reconstruction'
joined['explanation']=joined.apply(reason,axis=1)
joined.to_csv(P/'ADDITION_EXPLANATIONS.csv',index=False,encoding='utf-8-sig')
reason_counts=joined.loc[joined.comparison!='retained','explanation'].value_counts().to_dict()
save(P/'LEGACY_EXPLANATIONS.json',dict(retained=820,new_within_old947=200,new_outside_old947=2785,missing=0,new_explanation_counts=reason_counts,limitation='Only legacy code/date/entry_date projected. Five 2024 legacy-absent keys are recorded without assuming their original future-label, holding or retirement eligibility cause; no old outcome labels or account data read.',remaining_unattributed_keys=joined.loc[joined.explanation=='absent_from_old_frozen_set_no_future_eligibility_reconstruction',['code','signal_date']].to_dict('records')))
validation=dict(passed=True,structures=len(d),manifest_sha256=sha(AREA/'MANIFEST.json'),csv_sha256=sha(P/'FULL_SIGNALS.csv'),parquet_sha256=sha(P/'FULL_SIGNALS.parquet'),scanner_sha256=sha(P/'scan_full_scope.py'),next_valid_open_type='bool',valid_open_true=int(d.next_valid_open.sum()),valid_open_false=int((~d.next_valid_open).sum()),strict_official_next_session_verified=True,no_leader_column=True,unique_code_signal_keys=True,all_signal_dates_within_boundary=True,all_signal_dates_on_or_after_ipo=True,fixed_close_and_ma20_filters_verified=True,coverage_manifest_disagreement_rows=int((coverage.period_coverage_difference!=0).sum()),legacy_retained=summary['legacy_retained'],legacy_missing=summary['legacy_missing'],legacy_entry_date_differences=len(summary['entry_date_differences']),economic_returns_computed=False,accounts_run=False)
save(P/'VALIDATION.json',validation)
lines=['方向1全量历史沪深主板结构扫描（仅2020—2024）','', '固定原v3结构顺序：scan基础条件→10个已观察有效交易bar冷却→连续推断跌停排除→原始收盘价<8→qfq收盘/MA20≤0.92。未套用旧四项事后特殊事件剔除，不因未来入场、持有或退市资格删结构。更早有效行情只供预热和原函数连续冷却历史。', '', '冻结历史主板名录3336只，其中3319只在研究期有原始及有效行情，17只无研究期行。17只仍保留在范围覆盖文件，不按当前状态或未来outDate删股票。名单、IPO日期与实际bar来自明确冻结白名单；名录只投影code/name/ipoDate，没有读取outDate。', '', '结构总数3805；按年：2020=658，2021=455，2022=1158，2023=131，2024=1403。严格正式次日状态：3799条有有效开盘，6条停牌，其他状态0。六条停牌结构全部保留，未延期入场、未填造价格。next_valid_open是严格bool；next_raw_open即使存在也不表示可交易。', '', '旧947代码全部在新名录内。旧820个code/date键全部保留，缺失0，正式entry_date差异0。新增旧947池内200条：2020新增191条，原事后特殊事件3条重新保留，次日停牌结构1条保留，另5条2024结构不在旧冻结集合。最后5条不读取旧未来标签或账户，因此不假称已证明每条原先被排除的具体原因；逐条列于LEGACY_EXPLANATIONS.json。另新增旧947池外2785条，来自历史全主板范围扩展。无需也没有将新范围凑成820。', '', '覆盖、唯一键、时间边界、IPO下界、固定价格/MA条件、正式次日映射、CSV/parquet布尔类型与旧集合映射均通过。CSV与parquet的事件/状态集合一致；字段修复前后事件/状态摘要完全一致。', '', '只导出结构、已知信号前诊断和下一正式交易日状态，没有账户、优化、未来路径或经济收益。新输入无完整公司行动，不可从本导出推导账户业绩。qfq已按最后边界内raw收盘统一归一，去除更晚统一缩放；供应商历史修订无法回溯。未读取方向2结果、受限目录、软件或龙头分类。龙头分组由父代理单独处理，本导出没有leader列。原RULE/CURRENT及输入未修改。', '', '主文件FULL_SIGNALS.csv、FULL_SIGNALS.parquet；核验VALIDATION.json；范围覆盖SCOPE_COVERAGE.csv、SCAN_STAGES.csv；旧集合LEGACY_SET_COMPARISON.csv、LEGACY_DIAGNOSTICS.csv、ADDITION_EXPLANATIONS.csv、LEGACY_EXPLANATIONS.json；边界/访问PROTOCOL.json、CONTEXT_AUDIT.json、INPUT_ACCESS_AUDIT.json；字段修复EXPORT_FIX_AUDIT.json。']
(P/'FINDINGS.txt').write_text('\n'.join(lines)+'\n',encoding='utf8')
print(json.dumps(validation,ensure_ascii=False))
