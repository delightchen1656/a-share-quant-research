"""Audit frozen outputs and format reports; does not choose or run candidates."""
import hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
P=Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text(encoding='utf8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
protocol=read(P/'PROTOCOL.json');frozen=read(P/'ALL_SELECTIONS_FROZEN.json');stability=read(P/'STABILITY.json');training=read(P/'TRAINING_SUMMARY.json')['results']
assert sha(P/'PROTOCOL.json')==frozen['protocol_sha256']
assert sha(P/'ALL_SELECTIONS_FROZEN.json')==stability['all_selection_sha256']
for r in frozen['rounds']:
    folder=P/f'round_{r["round"]:02d}'
    assert sha(folder/'SELECTION_FROZEN.json')==r['selection_sha256']
    selected=read(folder/'SELECTION_FROZEN.json')
    assert sha(folder/'CANDIDATES_FROZEN.json')==selected['candidate_register_sha256']
signals=pd.read_parquet(P/'signals_rescanned.parquet')
calendar=pd.read_parquet(P.parents[1]/'inputs_pre2025/calendar.parquet')
dates=pd.to_datetime(calendar.date).dt.strftime('%Y-%m-%d').tolist();ordinal={d:i for i,d in enumerate(dates)}
audits=[]
for stage in ['training_runs','stability_runs']:
    for folder in sorted((P/stage).iterdir()):
        config=read(folder/'CONFIG.json')['config'];result=read(folder/'RESULT.json');output=next(folder.glob('*/daily_nav.parquet')).parent
        nav=pd.read_parquet(output/'daily_nav.parquet');trades=pd.read_parquet(output/'trades.parquet');ledger=pd.read_parquet(output/'ledger.parquet')
        identity=float((nav.equity-nav.cash-nav.stock_value-nav.receivable).abs().max())
        last=nav.iloc[-1];unrealized=sum(h['sale_net']+h['div_net']+(h['available']+sum(v['qty'] for v in h['locked']))*h['last_price']-h['cost'] for h in result['open_positions'])
        residual=float(last.equity-100000-trades.pnl.sum()-unrealized)
        t1=int((trades.sell_date<=trades.buy_date).sum());minimum_cash=float(min(nav.cash.min(),ledger.cash.min()))
        timing_errors=[];cash_errors=[];cash=100000.;inventory={};max_inventory=0;negative_inventory=[]
        for day,rows in ledger.groupby('date',sort=False):
            seen_buy=False
            for row in rows.itertuples():
                if row.kind=='buy':
                    seen_buy=True;cash-=row.gross+row.fee;inventory[row.code]=inventory.get(row.code,0)+row.qty
                elif row.kind=='sell':
                    if seen_buy and row.reason in ['take_profit_open','stop_loss_open','forced_delayed_open']:timing_errors.append(day)
                    cash+=row.gross-row.fee;inventory[row.code]=inventory.get(row.code,0)-row.qty
                    if inventory[row.code]<0:negative_inventory.append((day,row.code))
                    if inventory[row.code]==0:del inventory[row.code]
                elif row.kind=='dividend_payment':cash+=row.net
                max_inventory=max(max_inventory,len(inventory))
                if abs(cash-row.cash)>.01:cash_errors.append(day)
            if abs(float(nav.loc[nav.date==day,'cash'].iloc[0])-cash)>.01:cash_errors.append(day)
        if result['summary']['corporate_events']:raise ValueError('Explicit action-aware inventory audit required')
        buys=ledger.loc[ledger.kind=='buy'];lot_errors=int((buys.qty%100!=0).sum())
        max_daily_new=int(buys.groupby('date').size().max()) if len(buys) else 0
        cap=config['max_new_entries'];cap_errors=0 if cap is None else int((buys.groupby('date').size()>cap).sum())
        pool=signals.loc[signals.date<=('2023-12-31' if stage=='training_runs' else '2024-12-31')].copy()
        for f in config['filters']:
            z=pd.to_numeric(pool[f['feature']],errors='coerce');v=f['value']
            pool=pool.loc[(z>=v if f['op']=='>=' else z<=v if f['op']=='<=' else z<v).fillna(False)]
        pool['entry_date']=[dates[ordinal[d]+1] if ordinal[d]+1<len(dates) else None for d in pool.date]
        priority=config['priority'];ordering_errors=[]
        for day,group in buys.groupby('date',sort=False):
            expected=pool.loc[pool.entry_date==day]
            if priority=='code':expected=expected.sort_values('code')
            else:
                feature,direction=priority.rsplit('_',1)
                expected=expected.sort_values([feature,'code'],ascending=[direction=='ascending',True],na_position='last')
            ranks={c:i for i,c in enumerate(expected.code)}
            actual=[ranks.get(c,-1) for c in group.code]
            if -1 in actual or actual!=sorted(actual):ordering_errors.append(day)
        assert identity<1e-7 and abs(residual)<.01 and minimum_cash>=-1e-6
        assert not any([t1,len(timing_errors),len(cash_errors),lot_errors,cap_errors,len(ordering_errors),len(negative_inventory)])
        assert max_inventory<=config['slots'] and int(nav.positions.max())<=config['slots']
        audits.append(dict(stage=stage,candidate=folder.name,daily_nav_identity_max_abs=identity,terminal_pnl_identity_residual=residual,minimum_cash=minimum_cash,t1_violations=t1,opening_cash_timing_errors=len(timing_errors),ledger_cash_errors=len(cash_errors),buy_round_lot_errors=lot_errors,daily_entry_cap=cap,actual_max_daily_entries=max_daily_new,daily_cap_errors=cap_errors,priority_ordering_errors=len(ordering_errors),max_concurrent_positions=max_inventory,configured_slots=config['slots'],negative_inventory_errors=len(negative_inventory),closed_trade_pnl=float(trades.pnl.sum()),open_marked_pnl=float(unrealized),terminal_cash=float(last.cash),terminal_stock_value=float(last.stock_value),terminal_receivable=float(last.receivable),terminal_equity=float(last.equity),open_positions=len(result['open_positions']),corporate_events=result['summary']['corporate_events']))
save(P/'ACCOUNT_AUDIT.json',dict(passed=True,account_count=len(audits),checks=audits,selection_hash_verified=stability['all_selection_sha256']))
previous=read(P.parent/'clean_2020_2024/STABILITY.json')['results']
for new,old in [('anchor_v3','baseline'),('anchor_prior','priority_oversold')]:
    a=stability['results'][new];b=previous[old]
    assert a['yearly']==b['yearly'] and a['summary']['final_equity']==b['summary']['final_equity']
save(P/'ANCHOR_REPRODUCTION.json',dict(passed=True,previous_allowed_source='../clean_2020_2024/STABILITY.json',anchors=['anchor_v3','anchor_prior'],all_five_annual_returns_and_drawdowns_exactly_equal=True,terminal_equity_exactly_equal=True))
round_rows=[];annual=[]
for record in frozen['rounds']:
    r=read(P/f'round_{record["round"]:02d}'/'SELECTION_FROZEN.json');cid=r['selected'];best=max(r['attempts'],key=lambda a:a['score'])
    row=dict(round=r['round'],question=r['question'],new_candidates=r['candidate_count'],selected=cid,promoted=r['promoted'],score=r['training_statistics']['score'],best_attempt=best['candidate'],best_attempt_score=best['score'],best_attempt_rejection=';'.join(best['rejection_reasons']))
    for y in stability['results'][cid]['yearly']:
        annual.append(dict(round=r['round'],candidate=cid,**y));row[f'return_{y["year"]}']=y['return_pct'];row[f'drawdown_{y["year"]}']=y['max_drawdown']
    round_rows.append(row)
pd.DataFrame(round_rows).to_csv(P/'round_summary.csv',index=False,encoding='utf-8-sig')
pd.DataFrame(annual).to_csv(P/'round_annual_comparison.csv',index=False,encoding='utf-8-sig')
pd.DataFrame([dict(candidate=cid,**y) for cid,r in stability['results'].items() for y in r['yearly']]).to_csv(P/'anchor_final_annual.csv',index=False,encoding='utf-8-sig')
pd.DataFrame([dict(candidate=cid,**r['summary']) for cid,r in stability['results'].items()]).to_csv(P/'anchor_final_totals.csv',index=False,encoding='utf-8-sig')
pd.DataFrame([dict(candidate=cid,**y) for cid,r in training.items() for y in r['yearly']]).to_csv(P/'all_training_annual.csv',index=False,encoding='utf-8-sig')
inputs=read(P/'INPUT_AUDIT.json');issues=[r for r in inputs['actions'] if r['unresolved_fields']]
save(P/'DATA_LIMITATIONS.json',dict(universe=947,retrospective_pool=True,rule_ex_post_exclusions=4,base_signal_count=inputs['signals'],supplier_response_pairs=inputs['supplier_response_pairs'],action_records_audited=len(inputs['actions']),unresolved_reference_records=len(issues),unresolved_actions=issues,unresolved_held_actions=0,corporate_events_all_accounts=sum(r['corporate_events'] for r in audits),entry_availability=read(P/'ENTRY_AVAILABILITY.json'),prior_2024_seen=True,inspection_is_new_blind_test=False,adaptive_new_attempts=53,tail_marking='Last raw close + receivables, open PnL included; future exit prices and future exit costs not fabricated',execution_assumptions=protocol['execution']))
save(P/'INPUT_ACCESS_AUDIT.json',dict(boundary_version='public-pre2025-v2',type='Agent-declared source record and program path/hash guards; not an OS security boundary or OS access trace',initial_context_audit='CONTEXT_AUDIT.json',same_clean_agent=True,prior_2024_seen=True,allowed_prior_experiment_reads=['clean_2020_2024/run_research.py','clean_2020_2024/account.py','clean_2020_2024/STABILITY.json'],allowed_project_reads=['AGENTS.md','研究尝试/方向1_超跌反弹/AGENTS.md','研究尝试/方向1_超跌反弹/RULE.json','研究尝试/方向1_超跌反弹/structure.py'],inputs_root='研究尝试/方向1_超跌反弹/inputs_pre2025',final_manifest_sha256=protocol['data_manifest_sha256'],hash_checked_files=4749,response_pairs=2848,parsed_groups=['RESEARCH_2020_2024_MANIFEST.json','RESEARCH_QUERY_PLAN.json','MANIFEST.json','calendar.parquet','947 raw/qfq price pairs','company_actions_research_2020_2024.json'],max_price_date='2024-12-31',all_results_read='Own ten_rounds_2020_2024 outputs and explicitly allowed previous own experiment only',other_experiments_read=False,restricted_inputs_read=False,post2024_market_or_results_read=False,current_classification_read=False,production_selection_read=False,other_threads_read=False,subagents_spawned=False,inputs_modified=False,rule_or_current_modified=False,writes_root='研究尝试/方向1_超跌反弹/experiments/ten_rounds_2020_2024'))
final=frozen['final_candidate'];rr=training[final]['statistics'];vv=training['anchor_v3']['statistics'];last=stability['results'][final]
lines=['方向1新增十轮研究结果（2020—2024，无后验）','',f'实际完成10轮、53个新候选尝试，另保留2固定锚；此前13候选实验不计入。55个选择期账户与3个冻结后的完整期账户全部完成，共58个账户核验通过。',f'最终预注册风险调整候选与训练期最高连续收益候选同为{final}：20日超跌优先，5槽、固定每槽2万元、15%止盈、B3退出、无额外止损、无新增因子过滤或每日入场上限。研究候选冻结，未登记替换当前v3。','', '十轮（括号内为该轮新增候选数）：']
for r in round_rows:
    decision='晋级' if r['promoted'] else '无晋级，沿用前轮'
    lines.append(f'{r["round"]}. {r["question"]}（{r["new_candidates"]}）：{decision}，冻结{r["selected"]}；训练评分{r["score"]:.8f}。本轮最高评分尝试{r["best_attempt"]}，评分{r["best_attempt_score"]:.8f}，未晋级原因：{r["best_attempt_rejection"] or "通过并晋级"}。')
lines+=['','逐年收益率 / 年内最大回撤幅度：','年份      原v3锚          前轮锚          十轮最终']
for i,year in enumerate(range(2020,2025)):
    cells=[]
    for cid in ['anchor_v3','anchor_prior',final]:
        y=stability['results'][cid]['yearly'][i];cells.append(f'{y["return_pct"]*100:.2f}% / {abs(y["max_drawdown"])*100:.2f}%')
    lines.append(str(year)+'    '+'    '.join(cells))
lines+=['','完整期连续总收益 / 年化 / 最大回撤 / 期末权益：']
for cid in ['anchor_v3','anchor_prior',final]:
    s=stability['results'][cid]['summary'];lines.append(f'{cid}: {s["total_return"]*100:.2f}% / {s["annualized_return"]*100:.2f}% / {abs(s["max_drawdown"])*100:.2f}% / {s["final_equity"]:.2f}元。')
lines+=['',f'晋级理由：选择仅用2020—2023；最终评分{rr["score"]:.8f}高于前轮0.08039428。最终最差年度收益{rr["worst_annual_return"]*100:.2f}%，高于固定v3最差年{vv["worst_annual_return"]*100:.2f}%减2个百分点，且{rr["improved_years_vs_v3"]}个年度收益高于v3。拒绝高分但触及年度底线的尝试，完整淘汰原因见all_attempts.csv及各轮SELECTION_FROZEN.json。', '十轮每轮都是不同研究问题和实际新回测；没有将相同回测拆成十轮。第1—6轮冻结结果相同，第7—10轮冻结结果相同，因为注册规则允许无改进沿用；2024仅按唯一规则去重计算3次，round_annual_comparison.csv仍给足10轮×5年对应结果。', '所有十轮选择和训练期最高收益候选都冻结并保存哈希后，才运行本批2024。当前代理已见前轮实验2024，必须披露；2024不是新盲测，不宣称排除了研究者预期影响。53个顺序适应尝试存在多重试验风险，未作统计显著性或未来能力承诺。', '最终相对前轮：训练期收益改善，但2022收益下降；2024收益4.86%低于前轮6.27%和v3的6.01%，2024回撤6.45%小于前轮7.60%和v3的9.74%。不得因2024收益较低撤回或改选。不是逐年收益回撤同时全面改善。', f'实际数据：947回看池、1017基础信号、2848计划股票年度供应商响应、2065条公司行动。20条参考价异常均保留，不与任何58次账户的实际持仓重叠，实际公司行动处理次数为0；因此没有实证验证复杂送转/支付场景。实际持仓未解决行动和未知报价缺口仍严格阻断。本批无新数据阻断。', '002157在2023-05-04由冻结raw明确停牌，信号保留并统一不入场、不延期，不虚构保证成交；因子/每日上限/槽位已挡住的信号可能先记其他skip，完整证据见ENTRY_AVAILABILITY.json。', '2024末三条冻结规则都保留002513、002694两笔持仓，市值36698元，合计未实现损益-2716.21462元已计入权益，应收为0。不读取未来报价，不为标签成熟删尾部信号，不扣未实际发生的未来卖出费用。', '账目：每日现金+股票市值+应收=NAV，终点初始资金+已实现+未实现=NAV；现金非负，T+1、买入100股整手、持仓槽位、同日开盘资金时点全部通过；实际每日新开仓数与cap一致，实际买入顺序是已过滤信号按注册优先级排序的子序列。固定锚与前轮输出逐年完全复现。', '范围限制：947池为回看选择，RULE保留4项事后排除；日线和保证开盘成交假设没有盘口排队、冲击成本及官方历史限价完整校验。十万元初始资金，槽预算固定，不随权益放大。未读后验，不更改原输入或RULE/CURRENT，不授权实盘。', '', '文件入口：FINAL_CANDIDATE_FROZEN.json、ALL_SELECTIONS_FROZEN.json、PROTOCOL.json、round_summary.csv、round_annual_comparison.csv、anchor_final_annual.csv、anchor_final_totals.csv、all_attempts.csv、all_training_annual.csv、ACCOUNT_AUDIT.json、ANCHOR_REPRODUCTION.json、INPUT_ACCESS_AUDIT.json、DATA_LIMITATIONS.json；各round_XX保存候选及选择冻结文件，training_runs/和stability_runs/保存逐笔/NAV/跳过/流水。']
(P/'FINDINGS.txt').write_text('\n'.join(lines)+'\n',encoding='utf8')
print(json.dumps(dict(passed=True,accounts=len(audits),rounds=len(round_rows),new_attempts=frozen['candidate_attempts'],final=final,max_terminal_residual=max(abs(r['terminal_pnl_identity_residual']) for r in audits)),ensure_ascii=False))
