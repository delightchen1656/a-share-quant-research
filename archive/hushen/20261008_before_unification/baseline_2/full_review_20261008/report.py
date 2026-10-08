"""Assemble a reviewable daily research deliverable with explicit unverified gates."""
import json, html
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import research as r

HERE=r.HERE
def read(name):return json.loads((HERE/name).read_text(encoding='utf-8'))
def pct(x):return f'{x:.2%}'
def number(x):return f'{x:,.2f}'
def table(headers,rows):return '<table><thead><tr>'+''.join('<th>'+html.escape(str(x))+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table>'

def main():
    rows=read('halfyear_results.json');stress=read('stress_results.json');controls=read('control_results.json');neighbors=read('neighborhood_results.json');equal=read('equal_horizon_results.json')
    checks=read('validation.json');stats=read('statistical_diagnostics.json');audit=read('data_audit.json');compare=read('old_new_reconciliation.json')
    assert len(rows)==14 and len(stress)==8 and len(controls)==36 and len(neighbors)==6 and len(equal)==12 and all(checks.values())
    invalid=[x for x in controls if x['unresolved_actions'] or x['reference_differences']]
    workflow=[
      ('1 目标与风险预算','已明确','10万元、沪深主板、扣费收益；用户不设额外回撤门槛，风险客观报告。'),
      ('2 假设与核心','已冻结','小市值/低波动/隔夜强/日内弱的组合；不把机制解释当因果证明。'),
      ('3 数据时序协议','已检查，有历史边界','2018预热、2019—2022开发、2023选择段、2024确认、2025后隔离历史检验。本次零调参，原框架已有后段接触。'),
      ('4 数据与公司行动','主策略通过，仍有边界',f'{audit["symbols"]}只、{audit["rows"]:,}条日线，基础检查无错误；历史上市/退市日期约束已核对。历史证券池完全性未由交易所独立证明；11只已知复权异常未擅改。'),
      ('5 简单对照','已完成','4单因子、4删因子、原组合；另看中证500。基准指数不是含成本ETF账户。'),
      ('6 因子有效性','已完成描述检验','9组因子IC及五分组20日标签检验；缺失标签计数保留，不能当实际组合收益。'),
      ('7 训练与调参','固定规则，无新拟合','保留用户指定权重；6组开发段邻域只诊断，不选择冠军。本轮不把规则策略假称机器学习重训。'),
      ('8 真实交易账本','日线近似通过','现金、T+1、整手、日历、历史税费、公司行动、限价核对；盘口排队、价格笼子实时基准、滑点和盘中延迟无法由日线复原。'),
      ('9 留出/起点/压力','已完成，周期敏感','4个独立分段、14共同终点账户、12个252交易日账户、8个成本/容量/延迟场景。15/25日周期明显弱于20日。'),
      ('10 工程审查','本地通过',f'{len(checks)}项检查通过，旧版逐日净值重现、各股贡献及费用可对账。两个对照场景公司行动参考价不一致，明确标记，不当成干净证据。'),
      ('11 平台前向模拟','未完成','已解析旧日志并修复可控代码问题；未在SuperMind服务器运行D7，不能宣称五只未成交的根因已被实际消除。'),
      ('12 小资金实盘','未开始','未执行真实券商交易。未来需要新版本真实回报及账户核对。'),
      ('13 实盘盈利评估','历史归因完成，实盘待证','已做股票贡献、年度收益、回撤期、基准回归和分块抽样；没有实际收益证据。'),
      ('14 扩容与维护','本地容量检查及流程完成','50万/100万日线压力已做；真实容量、历史行业中性与多重搜索修正仍未证明。')]
    r.dump('workflow_checklist.json',[dict(stage=a,status=b,evidence=c) for a,b,c in workflow])
    trial_count=dict(named_account_runs=14+8+36+6+12,halfyear=14,stress=8,stage_controls=36,development_neighborhood=6,equal252=12,
                     signal_controls=9,new_optimization_trials=0,invalid_control_runs=len(invalid),note='76 run labels include repeated baseline configurations and overlapping histories; not 76 independent tests. No winner selected.')
    r.dump('trial_register.json',trial_count)
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','DejaVu Sans'];plt.rcParams['axes.unicode_minus']=False
    q=pd.read_parquet(HERE/'runs/start_2020-01-01_equity.parquet');old=pd.read_parquet(HERE/'runs/stress_original_daily_reference_equity.parquet')
    fig,axes=plt.subplots(3,1,figsize=(12,10),gridspec_kw={'height_ratios':[2,1,1.4]},constrained_layout=True)
    axes[0].plot(q.date,q.equity/10000,label='D7 审计后日线近似',color='#165c9b');axes[0].plot(old.date,old.equity/10000,label='v5 原口径复现',alpha=.65,color='#969caa')
    axes[0].set_ylabel('账户资产（万元）');axes[0].legend();axes[0].set_title('沪深基准2：冻结因子，执行审计后的历史结果（非平台实测）')
    dd=1-q.equity.to_numpy()/np.maximum.accumulate(np.r_[100000.,q.equity.to_numpy()])[1:]
    axes[1].fill_between(q.date,-dd*100,0,color='#b95043',alpha=.65);axes[1].set_ylabel('回撤（%）')
    labels=[x['requested_start'][:7] for x in rows]
    axes[2].bar(labels,[x['cagr']*100 for x in rows],color='#3f8e91');axes[2].set_ylabel('至共同终点年化（%）');axes[2].tick_params(axis='x',rotation=45)
    for ax in axes:ax.grid(alpha=.15)
    fig.savefig(HERE/'overview.png',dpi=160);plt.close(fig)
    table_rows=[[x['requested_start'],x['actual_start'],number(x['final_equity']),pct(x['total_return']),pct(x['cagr']),pct(x['max_drawdown']),f"{x['sharpe']:.3f}",x['trades'],number(x['commission']),number(x['transaction_fees']),number(x['dividend_tax']),number(x['total_cost'])] for x in rows]
    metric=lambda x:[pct(x['cagr']),pct(x['max_drawdown']),f"{x['sharpe']:.3f}",x['trades']]
    names={'original_daily_reference':'原v5口径','strict_daily_limits':'D7日线审计口径','double_commission':'佣金费率/最低收费翻倍','one_session_order_delay':'调仓订单延迟一交易日','capacity_10pct':'日成交量容量降到10%','capital_500k':'50万元','capital_1m':'100万元','exclude_vendor_anomaly_symbols':'排除11只复权异常股票'}
    core=[x for x in controls if x['control']=='original']
    example=compare['first_fill_difference']
    html_doc='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>沪深基准2全流程日线审计</title><style>body{font:15px/1.75 Microsoft YaHei,Arial;color:#203448;max-width:1500px;margin:28px auto;padding:0 24px}h1,h2{color:#154e75}table{border-collapse:collapse;width:100%;margin:18px 0}th,td{border:1px solid #d8e1e8;padding:8px;text-align:right;vertical-align:top}th{background:#eaf1f6}td:first-child{text-align:left}tr:nth-child(even){background:#f7fafc}.note{background:#fff4dc;border-left:5px solid #c9912f;padding:14px}img{max-width:100%}a{color:#1266a3}code{background:#eef2f4;padding:2px 5px}details{margin:18px 0}summary{font-weight:bold;cursor:pointer}.scroll{overflow:auto}</style>'''
    html_doc+='<h1>沪深基准2：全流程日线审计与重建</h1><p>2026-10-08｜原四因子、5只、98%目标仓位、20交易日相位、缓冲1.5冻结｜用户确认不设额外回撤阈值，并使用日线。</p>'
    html_doc+='<p class="note"><b>结论：完成可用日线支持的研究、账本和本地工程检验；不是所有环节通过。</b>周期邻域敏感，历史行业中性未证实，平台新版前向模拟及未来真实盈利仍待验证。以下为日线近似，不能称为V6分钟收益或SuperMind实测；限价未成交不会被代码保证消除。</p>'
    html_doc+='<p>平台文件：<a href="supermind_baseline2_D7_daily.py">D7 每日频率基础版</a>；本地：<a href="backtest.py">回测入口</a>；<a href="README.md">运行说明</a>；<a href="validation.json">检查结果</a>。</p><img src="overview.png" alt="净值、回撤与起点年化">'
    html_doc+='<h2>14个独立10万元账户，到2026-09-30</h2><p>节假日顺延到首个交易日。首次建仓额外触发，之后保持原2018起交易日历相位，不从每个起点重新计满20日。净值已扣费用，不应重复扣减。</p><div class="scroll">'+table(['指定起点','实际起点','最终资产（元）','累计','年化','最大回撤','Sharpe','成交笔数','佣金','交易费用含税','分红税','费用合计'],table_rows)+'</div>'
    html_doc+='<p>交易费用＝佣金＋过户费＋卖出印花税；费用合计再加已实现分红税。未强制期末平仓，未扣未来卖出成本和潜在未实现分红税。成交笔数为成交记录数，不是买卖往返数。Sharpe无风险利率0，日简单收益、样本标准差、252日年化。年化按实际自然日，2026年7月的短期年化尤其不宜外推。</p>'
    html_doc+='<h2>全流程逐项结论</h2>'+table(['阶段','状态','证据/边界'],workflow)
    html_doc+='<h2>独立分段</h2>'+table(['阶段','起始','截止','年化','回撤','Sharpe','成交'],[[x['stage'],x['actual_start'],x['end']]+metric(x) for x in core])
    html_doc+='<p>这些分段每段重新以10万元空仓开始，不能与一个持续账户的逐年收益混淆。隔离历史评价不等于真正从未看过的样本外。</p>'
    html_doc+='<h2>成本、延迟与容量压力</h2>'+table(['场景','年化','回撤','Sharpe','成交'],[[names[x['scenario']]]+metric(x) for x in stress])
    html_doc+='<p>50万/100万只是日线量约束下的容量检查，不证明盘口真实容量。提高容量限制仍可能不能覆盖滑点、队列和实时价格笼子。</p>'
    html_doc+='<h2>开发段参数邻域：没有自动选优</h2>'+table(['唯一变更','年化','回撤','Sharpe','成交'],[[str(x['params'])]+metric(x) for x in neighbors])
    html_doc+='<p class="note">20交易日原配置在开发段明显优于15/25日，调仓周期稳健性不足以给出“邻域都稳定”的结论。本轮没有据此挑选新周期，也没有利用后段反馈重搜。</p>'
    html_doc+='<details><summary>展开全部因子对照与数据异常</summary>'+table(['阶段','对照','年化','回撤','Sharpe','成交','公司行动异常'],[[x['stage'],x['control']]+metric(x)+[x['unresolved_actions']+x['reference_differences']] for x in controls])
    html_doc+='<p>两项对照存在除权参考价与公司行动账本不一致：开发段去隔夜因子涉及603319.SH/2019-04-16；后段单隔夜因子涉及001212.SZ/2025-05-29。保留异常，不当作干净的收益证据；主策略14起点无此异常。</p></details>'
    html_doc+='<details><summary>展开因子IC与五分组</summary>'+table(['因子配置','阶段','期数','均值IC','正IC比例','最高组减最低组20日收益','缺失标签'],[[x['control'],x['stage'],x['periods'],f"{x['mean_ic']:.4f}",pct(x['positive_fraction']),pct(x['top_minus_bottom']),x['missing_labels']] for x in read('factor_summary.json')])+'</details>'
    html_doc+='<h2>相同252交易日持有期</h2>'+table(['起始','截止','累计','年化','回撤','Sharpe'],[[x['actual_start'],x['end'],pct(x['total_return']),pct(x['cagr']),pct(x['max_drawdown']),f"{x['sharpe']:.3f}"] for x in equal])
    html_doc+='<p>共同终点会混入持有期差异。252日对照仍显示明显入场差异，包括亏损窗口；这些历史区间高度重叠，不是12次独立实验。</p>'
    html_doc+='<h2>风险、贡献与统计不确定性</h2><p>最长未创新高持续'+str(stats['max_underwater_sessions'])+'个交易日；最大回撤日期'+stats['max_drawdown_date']+'。20交易日分块重采样的Sharpe描述区间为'+str([round(v,3) for v in stats['sharpe_20session_block_bootstrap_95pct']])+'，未修正原历史多重搜索，不能当作盈利显著性证明。</p>'
    html_doc+=table(['股票','净利润贡献（元）'],[[s,number(v)] for s,v in stats['profit_concentration']['top10']])
    html_doc+='<p>各股贡献包括买卖现金流、费用、分红及期末市值，合计与总利润相符。只有当前行业映射，未使用它冒充历史行业中性归因。全部统计见statistical_diagnostics.json。</p>'
    html_doc+='<h2>与旧版结果为何不同</h2><p>重新计算的信号通过平台函数核对；旧v5账本逐日净值可完整复现。D7变化集中在限价取整、开盘成交约束及一分报价的现金预留。第一笔差异：'+str(example['new']['symbol'])+'，旧成交'+str(example['old']['price'])+'元，新成交'+str(example['new']['price'])+'元，之后现金与整手数量产生路径差异。不能把回测差异归咎于换了因子。</p>'
    html_doc+='<h2>两份模拟日志的处理</h2><p>严格重训版五笔零成交与v4的一买一卖已去重分别归档，不混成同一账户。D7保留日频：买价向上、卖价向下按分取整，平台额外滑点设0，重复回报去重，终态不倒退，未成交不生成持仓或可用现金，次日只补剩余股数；墙钟与策略时间分别记录。</p><p>税费仍由平台账户记账：D7对不符合预期印花税或穿越限价的回报告警，不调用未经核实的税费API或修改账户净值。没有新平台回报，不能把这两类告警的根因称为已实测修复；日线也无法判断当天盘口为何未成交。</p>'
    html_doc+='<h2>前向验证与维护约定</h2><p>新建独立空仓、每日频率、10万元的D7平台回测/模拟；记录每个交易日的版本、信号日期、委托ID、成交ID、费用、目标残差和执行耗时。需要跨多个调仓事件检查重复下单、资金/股数对账、限价和税费告警。工程异常先停止新增委托并核对；不因几笔盈亏随意调参。之后才考虑用户另行授权的小资金实盘，实盘账户收益需剔除外部资金流并与冻结目标组合逐笔归因。</p>'
    html_doc+='<p>本次76个命名账户回放包含重复基准及重叠历史，0次新选优；完整计数见trial_register.json。未来实盘盈利、队列成交、实时价格笼子、券商实际费率、历史行业中性及严格多重搜索校正仍未得到证据。</p>'
    html_doc+='<p>官方依据：<a href="https://quant.10jqka.com.cn/view/help/4?from=ifind">SuperMind API</a>、<a href="https://quant.10jqka.com.cn/view/help/10">模拟/仿真说明</a>、<a href="https://fgk.chinatax.gov.cn/zcfgk/c102416/c5211343/content.html">证券交易印花税减半公告</a>、<a href="https://www.szse.cn/www/investor/institute/rules/t20230713_601728.html">主板价格笼子与拒单机制</a>。</p></html>'
    (HERE/'report.html').write_text(html_doc,encoding='utf-8')
    # Convenient copyable table without asking the user to parse JSON.
    headers=['指定起点','实际起点','最终资产','累计','年化','最大回撤','Sharpe','成交笔数','佣金','交易费用含税','分红税','费用合计']
    text='| '+' | '.join(headers)+' |\n| '+' | '.join(['---']*len(headers))+' |\n'
    text+='\n'.join('| '+' | '.join(map(str,v))+' |' for v in table_rows)
    (HERE/'result_table.txt').write_text(text,encoding='utf-8')
    print('REPORT',HERE/'report.html','runs',trial_count['named_account_runs'],'checks',len(checks))

if __name__=='__main__':main()
