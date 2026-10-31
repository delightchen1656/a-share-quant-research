import json,pathlib,hashlib
import numpy as np,pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
P=pathlib.Path(__file__).resolve().parent
s=json.loads((P/'FROZEN_CANDIDATES.json').read_text(encoding='utf-8'))
labels=['original_reference','prior_frozen_best','cap30','cap35','split_cap30','buy_hold']
navs={label:pd.read_csv(P/f'{label}_daily_nav.csv') for label in labels}
b=navs['buy_hold'];bv=b.nav.to_numpy();stocklog=np.log(bv/np.r_[1.,bv[:-1]]);up=b.causal_up_regime.astype(bool).to_numpy();down=b.causal_down_regime.astype(bool).to_numpy();pos=stocklog>0
diags=[]
for label,d in navs.items():
 a=d.nav.to_numpy();log=np.log(a/np.r_[1.,a[:-1]]);row={'label':label,'up_regime_days':int(up.sum()),'up_regime_stock_log_return':float(stocklog[up].sum()),'up_regime_stock_compounded_return':float(np.exp(stocklog[up].sum())-1),'up_regime_strategy_log_return':float(log[up].sum()),'up_regime_strategy_compounded_return':float(np.exp(log[up].sum())-1),'up_regime_log_capture':None,'up_regime_capture_valid':False,'positive_stock_days_log_capture':float(log[pos].sum()/stocklog[pos].sum()),'down_regime_strategy_compounded_return':float(np.exp(log[down].sum())-1),'down_regime_stock_compounded_return':float(np.exp(stocklog[down].sum())-1),'down_regime_exposure':float(d.loc[down,'holding'].mean())}
 if stocklog[up].sum()>0:row['up_regime_log_capture']=float(log[up].sum()/stocklog[up].sum());row['up_regime_capture_valid']=True
 diags.append(row)
pd.DataFrame(diags).to_csv(P/'regime_and_capture_diagnostics.csv',index=False)
# Curves requested by parent: common initial equity1, same dates and execution.
fig,ax=plt.subplots(2,1,figsize=(12,8),sharex=True,gridspec_kw={'height_ratios':[2,1]},layout='constrained')
colors={'original_reference':'#9a76ab','prior_frozen_best':'#d97706','cap35':'#167d9a','buy_hold':'#888888'}
names={'original_reference':'Original reference','prior_frozen_best':'Prior frozen training winner','cap35':'New adaptive cap35 training candidate','buy_hold':'Buy and hold'}
for label in colors:
 d=navs[label];a=d.nav.to_numpy();dt=pd.to_datetime(d.date);ax[0].plot(dt,a,label=names[label],color=colors[label],lw=1.5);ax[1].plot(dt,100*(a/np.maximum.accumulate(np.r_[1.,a])[1:]-1),color=colors[label],lw=1.1)
ax[0].axvline(pd.Timestamp('2022-01-01'),color='#444',ls='--',lw=.8);ax[1].axvline(pd.Timestamp('2022-01-01'),color='#444',ls='--',lw=.8)
ax[0].set_ylabel('Gross qfq equity (initial = 1)');ax[1].set_ylabel('Drawdown (%)');ax[0].set_title('603106 | 2018-2023 observed training interval | next-bar open, ideal fractional fills');ax[0].legend(loc='upper left',fontsize=8);ax[1].set_xlabel('Date (2022 split is an observed-interval diagnostic)')
for a in ax:a.grid(alpha=.18)
fig.savefig(P/'equity_comparison.png',dpi=170);plt.close(fig)
allc=pd.read_csv(P/'all_configurations.csv');front=pd.read_csv(P/'pareto_frontier.csv');fig,ax=plt.subplots(figsize=(10,6),layout='constrained')
for fam,color in [('adaptive','#167d9a'),('trend','#ba7d32'),('recovery','#996bb0')]:
 d=allc[allc.family==fam];ax.scatter(100*d.max_drawdown,100*d.cumulative_return,s=2,alpha=.08,label=fam,color=color,rasterized=True)
ax.plot(100*front.max_drawdown,100*front.cumulative_return,color='#333',lw=1.5,label='Training Pareto frontier')
for cap in [30,35]:ax.axvline(cap,color='#555',ls='--',lw=.7)
for label,marker in [('cap30','o'),('cap35','*')]:
 r=s['selected_results'][label];ax.scatter(r['max_drawdown']*100,r['cumulative_return']*100,s=100,marker=marker,edgecolors='black',label=label,zorder=5)
ax.set(xlabel='Maximum daily-close drawdown (%)',ylabel='Cumulative gross return (%)',title='Finite adaptive search: 96,768 observed-training configurations');ax.legend(markerscale=2,fontsize=8);ax.grid(alpha=.2);fig.savefig(P/'return_drawdown_frontier.png',dpi=160);plt.close(fig)
sources={'parameter_origins':'All new grid values, feature windows, floors/caps, family definitions, split and objectives were fixed in SEARCH_PLAN before adaptive results; not inferred from later market results. Grid anchors are explanatory round-number hypotheses, not independently validated economic constants.','user_intent':'volatility adaptation, avoid causal downtrends and buy recovery; test against original OR MA/breakout family.','observed_original_comparators':'reference20/120/.02/.02/90/.08/5 and earlier full-training winner30/40/0/.02/10/.06/5, recomputed here with fixed parameters.','causal_volatility':'ATR14 or RV20, current signal-close data and past data only; vol floor.005 cap.15; stop fraction clip(multiplier*vol,.03,.35).','trend':'close>MAslow and MAslow >= its value slope5/10/20 bars ago.','recovery':'past60-close-peak drawdown, previous20-bar maximum >=2*currentvol, close above previous5-close maximum.','diagnostic_regimes':'previous close/MA60 and previous MA60 versus20 bars earlier; fixed before adaptive results; not trading filters except separately specified family rules.','supplemental_reporting_metric':'positive_stock_days_log_capture added only to reporting after discovering that predeclared up-regime stock return denominator was negative; contemporaneous realized positive days, never used for strategy selection or trade filters, not a win rate.','selection_status':'all training selections are finite-grid in-sample; chronological split uses already observed data and carries portfolio state.'}
(P/'PARAMETER_SOURCES.json').write_text(json.dumps(sources,ensure_ascii=False,indent=2),encoding='utf-8')
annual=pd.read_csv(P/'annual_comparison.csv');split=pd.read_csv(P/'chronological_diagnostic.csv');fam=pd.read_csv(P/'family_champions.csv')
text=['恒银科技603106：波动自适应与避跌恢复买入有限搜索','', '结论：本轮没有证明稳定学习成功。新候选可降低训练内回撤与历史下跌状态持仓暴露，但牺牲收益；按时间先拟合后固定参数诊断表现更弱。保留上轮冻结候选不变，本轮cap35只是训练内风险折中候选。','', '范围与隔离：仅白名单2018-01-01至2023-12-31两份parquet。两份SHA256和日期校验通过；1457行中1行停牌，先排除后按1456根交易报价计算。公共上下文含无关方向1的范围计数且本代理已看过同一区间上轮结果，所以不声称全部上下文绝对干净，也不声称新盲测；没有读取本股2023年后数据或结果。','', 'SEARCH_PLAN在结果前固定96,768组有限网格。七个主要交易参数均变化，新增ATR14/RV20波动尺度与三族：基础自适应、慢均线斜率/价格门槛、过去回调后的恢复突破。原MA入场OR突破入场结构保留，退出仍为MA条件OR追踪止损。波动及回调特征只用当根收盘已知及过去信息。全部窗口、上下限、参数来源见SEARCH_PLAN和PARAMETER_SOURCES。','主目标：全观察区间累计收益最大且日收盘最大回撤不超过30%；另给35%约束与无约束冠军。平手先低回撤，再按配置字典序。没有扩网格，没有期外试参。','', '候选与原规则同口径对比（累计毛收益 / 日收盘最大回撤 / 历史下跌状态持仓暴露 / 买入+卖出次数）：']
for label in ['original_reference','prior_frozen_best','cap30','cap35','buy_hold']:
 r=s['selected_results'][label];fills=f"{r.get('buy_fills',1)}+{r.get('sell_fills',0)}";text.append(f"{label}: {r['cumulative_return']*100:+.4f}% / {r['max_drawdown']*100:.4f}% / {r['down_regime_exposure']*100:.4f}% / {fills}")
text+=['', 'cap30参数：'+json.dumps(s['selected_parameters']['cap30'],ensure_ascii=False),'cap35参数：'+json.dumps(s['selected_parameters']['cap35'],ensure_ascii=False),'无约束冠军与cap35相同。cap30累计-10.1826%，虽然满足训练内30%回撤约束，不能把它称为有吸引力的盈利策略。cap35累计+52.0939%，相对买持累计超额+86.1836个百分点，回撤34.0403%，低于上轮最高收益候选的120.6933%收益、49.9303%回撤。','cap35使用RV20，入场缓冲2*波动率、退出缓冲1*波动率、追踪止损clip(3*波动率,3%,35%)；fast10/slow90，前20根收盘突破，冷静20根。它不另加慢均线斜率门槛。','cap35首次可检查2018-05-21，首次买入信号2018-05-22；cap30首次可检查/首次信号均为2018-05-28。全部没有更早预热行情。','', '三个规则族的同网格冠军：']
for _,r in fam.iterrows():text.append(f"{r.family}/{r.constraint}: 累计{r.cumulative_return*100:+.4f}%，回撤{r.max_drawdown*100:.4f}%")
text+=['adaptive族没有满足30%全期回撤约束的配置。恢复族没有在本轮证明更优；不追加规则挽救该假设。','', '已观察区间内时间切分诊断：2018—2021选参，参数固定后连续延伸至2022—2023，持仓/信号连续。上轮已经观察过完整区间，所以这不是未见样本或盲测。30%、35%约束与无约束的拟合期冠军恰好相同。','拟合期参数：'+json.dumps(s['selected_parameters']['split_cap30'],ensure_ascii=False)]
for _,r in split[split.label.eq('split_cap30')].iterrows():text.append(f"{r.period}: 累计{r.return_*100:+.4f}%，期内回撤{r.max_drawdown*100:.4f}%，下跌状态暴露{r.down_regime_exposure*100:.4f}%")
text+=['拟合期最大回撤28.6993%没有维持到后半段：后半段回撤60.6196%，收益-31.0781%。训练内回撤约束不能解释成未来风险上限。','', '逐年收益/期内回撤（前一年末净值作当年起始，首年从1开始，峰值每年重置）：']
for year in range(2018,2024):
 vals=[]
 for label in ['original_reference','prior_frozen_best','cap30','cap35','buy_hold']:
  r=annual[annual.label.eq(label)&annual.year.eq(year)].iloc[0];vals.append(f"{label} {r.return_*100:+.3f}%/{r.max_drawdown*100:.3f}%")
 text.append(str(year)+'  '+'；'.join(vals))
text+=['', '状态与上涨捕获的解释：下跌状态使用前一天close<MA60且MA60比20根前低；上涨状态反向，其他中性。共574个下跌状态日、422个上涨状态日、460个中性日；用于报告的日状态只用前日信息。','下跌状态持仓暴露只是该状态日收盘持仓占比，不等于下跌损失捕获，也不能证明避开所有损失；滞后均线可能把跌势早期或上涨回撤记为其他状态。','预声明的上涨状态对数收益捕获比，因标的在这些状态日的对数收益合计为-0.87294688（复合-58.2281%），分母非正，统一记为不可解释/空值；它不是胜率，不能作为有效上涨捕获率。原始状态收益已保存。','为解释漏涨而补充的“标的正收益日对数收益捕获”只作事后记账：标的当日收盘收益为正的日子，策略对数收益总和除以标的对应对数收益总和；不用于任何搜索、交易过滤或选参，也不是胜率。']
for r in diags:text.append(f"{r['label']}: 正收益日对数捕获{r['positive_stock_days_log_capture']*100:.3f}%；历史上涨状态策略复合收益{r['up_regime_strategy_compounded_return']*100:+.3f}%（标的同状态-58.228%）")
text+=['', '执行与代价：收盘信号后次根有报价交易日开盘，100%/0持仓，理想可分割份额，现金收益0。退出信号i后最早收盘i+cool检查。未扣费用或滑点；买卖次数给出满仓单边换手代价代理，不能当作已扣费收益。期末未平仓只按末日收盘估值。','cap35有21次买入、20次卖出、末日仍持仓；1次成交落在估计涨停开盘，详见cap35_fills.csv。其他候选也逐笔标记。限价由原始preclose/isST按10%/5%估算，未验证官方限价，不保证可成交。','前复权只是价格比例观察，未构建实际公司行动股数、分红和到账账户。回撤仅用日收盘净值，未计日内高低点。','', '核验：两份输入哈希/截止通过；搜索Numba实现与独立编写的pandas交易流水实现逐项相符；每笔收益连乘与日净值末值相符；全部成交为下一可交易报价根；每个冻结新候选在300/600/900/1200根截断重算的此前信号和净值与完整序列前缀一致。这里的“独立代码”不是独立样本验证。','', '产物：FROZEN_CANDIDATES.json冻结；all_configurations.csv全部配置；annual_comparison.csv逐年；chronological_diagnostic.csv时间切分；selected_comparison.csv同口径总表；family_champions.csv分族；pareto_frontier.csv前沿；regime_and_capture_diagnostics.csv状态/捕获原始量；各标签daily_nav/trades/fills/signals为曲线和明细；equity_comparison.png净值与回撤图；return_drawdown_frontier.png完整网格散点；SEARCH_PLAN.json事前计划；PARAMETER_SOURCES.json来源；CONTEXT_AUDIT.json上下文；INPUT_AUDIT.json数据；research.py与finalize.py复算和报告代码。']
(P/'REPORT.txt').write_text('\n'.join(text),encoding='utf-8')
s['reporting_metrics_caveat']='Predeclared up-regime ratio is invalid because underlying up-regime log return sum<=0; retain null, never a win rate. Supplemental positive-day metric is reporting-only and not used in selection.'
s['artifact_hashes']={f:hashlib.sha256((P/f).read_bytes()).hexdigest() for f in ['SEARCH_PLAN.json','research.py','finalize.py','PARAMETER_SOURCES.json','all_configurations.csv']}
(P/'FROZEN_CANDIDATES.json').write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
(P/'OUTPUT_HASHES.json').write_text(json.dumps({x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in P.iterdir() if x.is_file() and x.name!='OUTPUT_HASHES.json'},indent=2),encoding='utf-8')
print('Final report, diagnostics, two plots and hashes saved.')
