import hashlib,json
import pandas as pd
from moderate_tuning import OUT,DEFAULT,VARIANTS

labels={'count':'目标持股数','buffer':'保留排名范围','exposure':'目标仓位','minimum':'小额调仓门槛（元）','cap':'单股权重上限倍数','ma':'市场均线天数','band':'流通市值分位区间','bull':'强市评分权重','defense':'弱市评分权重','risk_floor':'下行波动下限','risk_power':'风险倒数配权指数','cadence':'调仓间隔（月）','amount_floor':'20日成交额下限（元）','vol_ceiling':'20日波动率上限','weight_window':'下行风险窗口（日）','high_window':'强市高点窗口（日）','turn_window':'换手窗口（日）'}
r=pd.read_csv(OUT/'results.csv');stress=pd.read_csv(OUT/'stress.csv');selection=json.loads((OUT/'selection.json').read_text())
checks=[]
for name in r.name:
 c=pd.read_csv(OUT/(name+'_equity.csv'),parse_dates=['date']);t=pd.read_csv(OUT/(name+'_trades.csv'),parse_dates=['date'])
 assert not c.date.duplicated().any() and c.equity.notna().all() and (c.cash>=-.01).all()
 assert (t[t.side=='BUY'].quantity%100==0).all() and (t.commission>=5-.00001).all()
 assert t[t.side=='BUY'].merge(t[t.side=='SELL'],on=['date','symbol']).empty
 checks.append(dict(name=name,checks_passed=True))
lines=['# 沪深基准2：有限调参与稳健性检查','', '本轮仅研究本地模型。原本地与SuperMind尚未独立对齐，不能把本轮收益当作平台改善。初始10万元，2020-01-02至2026-09-11。基准2待定1与平台代码保持不变。', '',
 '## 结论','', '17组参数、34个变体加1个对照；无组合穷举、无再次细化、无最佳参数拼接。原版净值逐日复现到0.01元内。唯一通过预设开发期相邻取值筛选的方向为波动率上限，选出6%作为研究观察项，但没有替换基准。', '',
 '|方案|年化|最大回撤|Sharpe|2020—2021年化|2022—2023年化|2024年化|2025后年化|','|---|---:|---:|---:|---:|---:|---:|---:|']
for n,label in [('control','基准2待定1'),('vol_ceiling_2','波动上限6%（筛选候选）'),('band_2','市值40%—60%（未通过稳定性）'),('exposure_2','90%仓位（未通过稳定性）')]:
 z=r[r.name==n].iloc[0];lines.append(f'|{label}|{z.full_annualized_return:.2%}|{abs(z.full_max_drawdown):.2%}|{z.full_sharpe:.3f}|{z.early_annualized_return:.2%}|{z.late_annualized_return:.2%}|{z.year2024_annualized_return:.2%}|{z.recent_annualized_return:.2%}|')
lines+=['','## 预先确定的筛选办法','',
 '2020—2023分成两个两年段，用较差一段年化＋0.05×开发期Sharpe－0.5×开发期最大回撤绝对值评分。同一参数的两个测试取值都不得低于原版评分，且两个两年段均盈利。候选开发期年化至少为原版95%，开发期回撤不恶化。2024及2025后只展示，不用来重新选参。该方法是保守筛选，不是显著性检验，也不能消除此前观察历史带来的偏差。', '',
 '## 加倍费用压力','', '|方案|年化|最大回撤|Sharpe|','|---|---:|---:|---:|']
for z in stress.itertuples():lines.append(f'|{z.name}|{z.full_annualized_return:.2%}|{abs(z.full_max_drawdown):.2%}|{z.full_sharpe:.3f}|')
lines+=['','佣金从万三最低5元变为万六最低10元，双边滑点从0.2%变为0.4%，税率假设不变。候选优势进一步缩小。', '',
 '## 参数覆盖','', '|参数|原值|两个测试值|','|---|---|---|']
for k,vs in VARIANTS.items():lines.append(f'|{labels[k]}|{DEFAULT[k]}|{vs}|')
lines+=['','强市权重依次对应低成交额、接近历史高点、分红代理；弱市权重依次对应分红代理、低下行风险、低换手。风险窗口变化同时影响弱市评分和配权。持股数量单独改变时保留24名缓冲，不同时改成持股数三倍。波动率上限为日收益标准差，不是年化波动。', '',
 '并非机械优化所有数字：上市满250个有效交易日、20日最低波动0.4%、三年分红代理定义等结构项保留；费用、T+1、整数手、封板及成交量约束不作为收益优化参数。沿用当前已合格股票池，只测试收紧成交额/波动门槛，未测试放宽股票池，因此不能推断放宽门槛的效果。', '',
 '## 限制与留档','',
 '历史已反复研究，没有真正未见的样本外区间，未进行统计显著性证明。固定股票池、代理市值/分红、近似公司行动和平台差异继续存在。不能通过更多调参替代数据与撮合校准。本轮不继续围绕全期赢家细化，待取得平台诊断数据或新增未观察数据再验证。', '',
 '原始费用口径为万三最低5元、双边0.2%滑点、卖出固定0.1%税率，未单列过户费。35个配置均通过现金非负、整数手买入、最低佣金和无同日往返检查。', '',
 'protocol.json保存运行前方案，results.csv保存全部结果，family_stability.csv保存参数组稳定性，selection.json保存按规则选出的研究候选。每个配置的净值与成交明细保留，可复核而非只展示优胜者。']
(OUT/'调参结论.md').write_text('\n'.join(lines),encoding='utf-8')
(OUT/'audit.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.is_file() and p.name!='sha256.json'}
(OUT/'sha256.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print('REVIEW COMPLETE',len(checks))
