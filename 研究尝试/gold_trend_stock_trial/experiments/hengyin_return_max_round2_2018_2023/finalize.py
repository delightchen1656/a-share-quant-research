
import sys as _layout_sys
from pathlib import Path as _LayoutPath
_layout_root=next(p for p in _LayoutPath(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
_layout_sys.path.insert(0,str(_layout_root/'tools'))
from workspace_paths import resolve_recorded_path
import json,pathlib,hashlib,ast,math
import pandas as pd,numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
OUT=pathlib.Path(__file__).resolve().parent
summary=json.loads((OUT/'FROZEN_BEST.json').read_text(encoding='utf-8'));plan=json.loads((OUT/'SEARCH_PLAN.json').read_text(encoding='utf-8'))
# Recompute just the single existing structurally diagnosed record; never execute the search module.
w=json.loads((OUT.parents[1]/'inputs_pre2025/hengyin_2018_2023/WHITELIST.json').read_text(encoding='utf-8-sig'));frames=[]
for f in w['files']:
 p=resolve_recorded_path(f['path']);assert hashlib.sha256(p.read_bytes()).hexdigest()==f['sha256'];frames.append(pd.read_parquet(p).sort_values('date').reset_index(drop=True))
q,r=frames;keep=pd.to_numeric(q.tradestatus).eq(1)&pd.to_numeric(r.tradestatus).eq(1);q=q[keep].reset_index(drop=True);r=r[keep].reset_index(drop=True);o=q.open.to_numpy(float);c=q.close.to_numpy(float);n=len(c);dates=pd.to_datetime(q.date);years=(dates.iloc[-1]-dates.iloc[0]).days/365.2425
source=(OUT/'research.py').read_text(encoding='utf-8-sig');node=next(x for x in ast.parse(source).body if isinstance(x,ast.FunctionDef) and x.name=='ledger');exec(compile(ast.Module(body=[node],type_ignores=[]),str(OUT/'research.py'),'exec'),globals())
struct=pd.read_csv(OUT/'structural_diagnostics.csv');row=struct.iloc[0];keys=['fast','slow','entry_buffer','exit_buffer','breakout','stop','cooldown','entry_filter'];cfg=[row[k] for k in keys]
sm,sd,ss=ledger(cfg,'structural_nonnegative');assert abs(sm['cumulative_return']-row.cumulative_return)<1e-10 and abs(sm['max_drawdown']-row.max_drawdown)<1e-10
annual=pd.read_csv(OUT/'annual_comparison.csv');extra=[];prev=1.
for year,part in sd.groupby(pd.to_datetime(sd.date).dt.year):
 a=part.nav.to_numpy();extra.append(dict(label='structural_nonnegative',year=int(year),return_=a[-1]/prev-1,max_drawdown=float(np.max(1-a/np.maximum.accumulate(np.r_[prev,a])[1:]))));prev=a[-1]
annual=pd.concat([annual,pd.DataFrame(extra)],ignore_index=True);annual.to_csv(OUT/'annual_comparison.csv',index=False)
summary['post_search_structural_diagnostic']={'note':'Grouping of existing searched records only, does not change unconstrained primary ranking. Both nonoverlap and nonnegative-buffer groups share this record; fixed ledger recomputed, not an added search stage.','parameters':{k:int(row[k]) if k in ['fast','slow','breakout','cooldown'] else row[k] for k in keys},'result':sm,'ledger_recompute_equal':True}
# Training-only additive log-return attribution by calendar year and overnight/intraday components.
navs={label:pd.read_csv(OUT/f'{label}_daily_nav.csv') for label in ['best','old_training_winner','original_reference','buy_hold','structural_nonnegative']}
yearrows=[]
for year in range(2018,2024):
 a=annual[annual.year.eq(year)].set_index('label');nr=float(a.loc['best','return_']);orr=float(a.loc['old_training_winner','return_']);sr=float(a.loc['structural_nonnegative','return_']);yearrows.append({'year':year,'best_return':nr,'old_return':orr,'structural_nonnegative_return':sr,'best_minus_old_log_return_contribution':float(np.log1p(nr)-np.log1p(orr)),'relative_equity_factor_contribution':(1+nr)/(1+orr)})
pd.DataFrame(yearrows).to_csv(OUT/'training_annual_attribution.csv',index=False)
components=[]
for label,d in navs.items():
 held=d.holding.to_numpy();prevheld=np.r_[0,held[:-1]];overnight=np.log(o/np.r_[o[0],c[:-1]])*prevheld;intraday=np.log(c/o)*held;total=overnight.sum()+intraday.sum();assert abs(total-np.log(float(d.nav.iloc[-1])))<1e-9
 components.append({'label':label,'overnight_log_contribution':float(overnight.sum()),'intraday_log_contribution':float(intraday.sum()),'total_log_return':float(total),'holding_fraction':float(held.mean())})
pd.DataFrame(components).to_csv(OUT/'training_return_components.csv',index=False)
trades=pd.read_csv(OUT/'best_trades.csv');fills=pd.read_csv(OUT/'best_fills.csv');buys=fills[fills.side.eq('BUY')].reset_index(drop=True);sells=fills[fills.side.eq('SELL')].reset_index(drop=True);trades['holding_tradable_bars']=sells.fill_index-buys.fill_index;trades['log_return_contribution']=np.log1p(trades.return_);trades.sort_values('log_return_contribution',ascending=False).to_csv(OUT/'best_trade_return_attribution.csv',index=False)
durations=trades.groupby('holding_tradable_bars').agg(trades=('return_','size'),mean_return=('return_','mean'),log_return_contribution=('log_return_contribution','sum')).reset_index();durations.to_csv(OUT/'best_holding_duration_attribution.csv',index=False)
summary['training_mechanism']={'overlapping_MA_thresholds':'entry MA14>0.98*MA15 and exit MA14<1.005*MA15 overlap; state machine alternates entry/exit, not conventional trend-following confirmation.','one_bar_holding_closed_trades':int(trades.holding_tradable_bars.eq(1).sum()),'mean_holding_tradable_bars':float(trades.holding_tradable_bars.mean()),'holding_fraction':float(navs['best'].holding.mean()),'unfilled_final_signal':'Final-day buy signal has no following quote within authorized interval; no final fill invented.','warmup_and_phase':'All windows must be ready; breakout86 affects first eligible day even when MA branch dominates. Cooldown and warmup can align periodic trade timing in-sample. No date-specific filters used; this does not prove learned causal trends.'}
# Curves: main unconstrained winner remains primary; structural group is explicitly post-search.
fig,axes=plt.subplots(2,1,figsize=(12,8),sharex=True,gridspec_kw={'height_ratios':[2,1]},layout='constrained')
colors={'best':'#c44e30','structural_nonnegative':'#167d9a','old_training_winner':'#d99a1b','original_reference':'#9a76ab','buy_hold':'#888888'}
names={'best':'Round2 gross-return winner (overlapping MA bands)','structural_nonnegative':'Existing nonnegative-buffer group winner','old_training_winner':'Prior frozen winner','original_reference':'Original reference','buy_hold':'Buy and hold'}
for label in colors:
 d=navs[label];a=d.nav.to_numpy();dt=pd.to_datetime(d.date);axes[0].plot(dt,a,color=colors[label],label=names[label],lw=1.4);axes[1].plot(dt,100*(a/np.maximum.accumulate(np.r_[1.,a])[1:]-1),color=colors[label],lw=1.1)
axes[0].set_title('603106 | 2018-2023 observed training only | ideal fractional fills, gross objective');axes[0].set_ylabel('Equity (initial = 1)');axes[1].set_ylabel('Daily-close drawdown (%)');axes[1].set_xlabel('Date');axes[0].legend(loc='upper left',fontsize=8)
for ax in axes:ax.grid(alpha=.18)
fig.savefig(OUT/'equity_comparison.png',dpi=170);plt.close(fig)
# Cost sensitivity stays purely reporting; no re-ranking or additional fitting.
cost=pd.read_csv(OUT/'cost_sensitivity.csv');costs=cost.to_dict('records')
for bp in plan['cost_sensitivity']['one_way_rates_bps']:
 rr,dd,sg=ledger(cfg,'structural_nonnegative',write=False,cost_bps=bp);costs.append(rr)
cost=pd.DataFrame(costs);cost.to_csv(OUT/'cost_sensitivity.csv',index=False)
report=['恒银科技603106：第二轮累计收益最大化训练搜索','', '主结果：在本轮事前声明的两个有限阶段内，最高累计毛收益+646.2446%，超过旧冻结版本+120.6933%，提升525.5512个百分点。全部只用2018—2023白名单，没有期外检验。旧候选保持不变，新结果单独冻结。','这不是全局最优或未来有效性证据。此前已观察整个训练区间，扩大网格与邻域细化有较强拟合风险；本轮不设置回撤限制，年度稳定或费用结果不改变毛收益主排序。','', '搜索：阶段1共820,800组；粗网格最高+243.1810%。严格取该阶段收益领先8个种子，按预声明七维5点邻域和边界裁剪生成阶段2的435,500个阶段内去重配置。合计1,256,300次评估（含跨阶段重复），没有第三阶段。全部记录分阶段CSV保留。','数据：仅WHITELIST列明的前复权与原始价格；SHA256和2018—2023日期通过。1457行中1行停牌，先排除后按1456根可交易报价计算。没有边界前预热。上下文披露沿前两轮保留，不声称全部上下文绝对干净；没有收到本股票期外行情/业绩/选参。','', '最高收益规则（无额外入场门槛）：','fast=14，slow=15，entry_buffer=-0.02，exit_buffer=-0.005，breakout=86，stop=0.07，cooldown=2。','买入：(MA14>MA15*0.98) OR (close>此前86根最高close AND close>MA15)。','退出：(MA14<MA15*1.005) OR (close<从买入信号日起最高close*0.93)。','收盘信号，次根有报价可交易日开盘成交。退出信号i后最早收盘i+2检查再入场，随后次根开盘。100%/0，理想可分割份额，现金收益0。期末持仓只估值，不虚构末日平仓。','', '必须注意：买入与退出均线阈值重叠。在0.98*MA15<MA14<1.005*MA15时，两条MA条件同时成立；状态机按持仓状态分开应用，不在同根开盘往返。该胜出版本主要是高频短持有训练拟合，不能称为传统趋势学习或稳定避跌。','432笔已完成交易、0笔未平仓，432买+432卖=864次成交，完成交易胜率53.7037%。403/432笔仅持有1根交易报价间隔（约93.29%），平均1.169根，收盘持仓占比34.6841%。MA入场主导，没有单独突破分支买入。','所有窗口就绪后才启用：首次可检查/首次信号2018-05-16；最终日还有一个无下根报价的买入信号，未虚构成交。breakout窗口虽很少决定入场，也会影响首个可检查日；冷静期与首始预热可能在训练内对齐交易节奏，因此收益不能解释为因果趋势规律已被学会。','', '总指标（毛收益）：']
for label in ['best','old_training_winner','original_reference']:
 rr=summary[label];report.append(f"{label}: 累计{rr['cumulative_return']*100:+.4f}%，年化{rr['annualized_return']*100:.4f}%，日收盘最大回撤{rr['max_drawdown']*100:.4f}%，完成{rr['closed_trades']}笔/未平仓{rr['open_trades']}笔，胜率{rr['closed_win_rate']*100:.4f}%")
report+=['年化用首末行情日期间隔/365.2425；日收盘最大回撤包含初始资金1，未计日内高低点。旧120.69333171965284%已精确复算。','', '已搜索结果的结构诊断（事后分组，不是新增阶段，不影响646.2446%主排序）：','entry_buffer+exit_buffer>=0（MA阈值不重叠）组，以及entry_buffer>=0且exit_buffer>=0组，最高记录恰好相同：','fast18 slow40 entry0 exit0.025 breakout2 stop0.03 cooldown9，无额外门槛；累计+441.8511%，年化32.6058%，回撤31.5063%，66笔完成/0笔未平仓，32胜，胜率48.4848%。已对这一条现成记录固定参数账本复核，非新搜索。','这一记录更接近原趋势/突破逻辑，也超过旧120.69%，但仍是训练内选择，不能把分组结果改称未经筛选验证。','', '逐年收益及最大回撤（当年峰值从上一年末净值起重置）：']
for year in range(2018,2024):
 vals=[]
 for label in ['best','structural_nonnegative','old_training_winner','original_reference','buy_hold']:
  rr=annual[annual.year.eq(year)&annual.label.eq(label)].iloc[0];vals.append(f"{label} {rr.return_*100:+.3f}%/{rr.max_drawdown*100:.3f}%")
 report.append(str(year)+'  '+'；'.join(vals))
report+=['', '收益提升来源只作训练内归因：较明显的改善在2022（新+96.1754%，旧-6.6926%）、2020（新+42.3052%，旧+8.8840%）、2021（新+17.0666%，旧-4.0563%）；2019新-11.7315%比旧-9.5131%更差。2023新+104.0750%，旧+100.9234%，并非全部提升都来自该年。','training_annual_attribution.csv记录逐年的新增对数收益，能够加总为新旧总对数收益差，避免把各年简单收益直接相加。best_trade_return_attribution.csv给出每笔训练收益与对数贡献；training_return_components.csv按持仓拆分开盘跳空和日内收益，仅为记账，不作新的日期过滤。','', '事前规定费用敏感性（每次买、卖各扣组合净值相应比例；信号不变，仅报告）：']
for bp in plan['cost_sensitivity']['one_way_rates_bps']:
 vals=[]
 for label in ['best','structural_nonnegative','old_training_winner']:
  rr=cost[cost.label.eq(label)&cost.one_way_cost_bps.eq(bp)].iloc[0];vals.append(f"{label} 累计{rr.cumulative_return*100:+.4f}%/回撤{rr.max_drawdown*100:.4f}%")
 report.append(f'单边{bp}bp：'+'；'.join(vals))
report+=['主冠军在单边20bp假设下累计仅+32.3332%，低于旧候选同假设+71.1465%，说明864次换手的代价很大。这里不是实际券商税费、整数手、公司行动或流动性账户，也不据此重排毛收益主目标。','', '涨跌停理想成交：主冠军6次开盘落在按原始preclose/isST、10%/5%估计的涨跌停附近，买入3次、卖出3次，详见best_fills.csv逐笔flag。并未核实交易所官方限价或保证成交；尤其涨停买入/跌停卖出可能不能按假定执行。','前复权仅用于价格比率观察；不是实际分红、送转、股数、到账和整手账户。毛收益未扣成本或滑点。','', '核验：Numba搜索与另写的pandas事件流水一致；每笔收益连乘等于期末净值；成交都在信号的下一可交易报价根；主冠军、旧冻结最优、原参考在300/600/900/1200根截断重算的信号/净值与完整前缀一致。独立代码复算不代表独立样本验证。','', '产物索引：FROZEN_BEST.json新冻结；SEARCH_PLAN.json事前搜索/细化规则；STAGE2_SEEDS.csv事前规则选出的8种子；all_configurations_stage1/2.csv全部配置；TOP_CANDIDATES.csv领先配置；structural_diagnostics.csv事后结构分组；annual_comparison.csv年度；training_annual_attribution.csv年度收益归因；training_return_components.csv开盘/日内归因；best_trade_return_attribution.csv逐笔；best_holding_duration_attribution.csv持有长度；cost_sensitivity.csv成本；各标签daily_nav/trades/fills/signals为净值交易信号；equity_comparison.png曲线；CONTEXT_AUDIT/INPUT_AUDIT审计；research.py/finalize.py复算与报告。']
(OUT/'REPORT.txt').write_text('\n'.join(report),encoding='utf-8')
summary['code_and_plan_hashes']={name:hashlib.sha256((OUT/name).read_bytes()).hexdigest() for name in ['research.py','finalize.py','SEARCH_PLAN.json','STAGE2_SEEDS.csv']}
(OUT/'FROZEN_BEST.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=lambda x:x.item() if isinstance(x,np.generic) else str(x)),encoding='utf-8')
(OUT/'OUTPUT_HASHES.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.is_file() and p.name!='OUTPUT_HASHES.json'},indent=2),encoding='utf-8')
print('Fixed existing structural record verified. Report, curve, attribution and hashes complete.')
print(pd.DataFrame(components).to_string(index=False));print(cost[['label','one_way_cost_bps','cumulative_return','max_drawdown']].to_string(index=False))
