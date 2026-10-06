from pathlib import Path
import json, html
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pipeline as p

plt.rcParams['font.family']='Microsoft YaHei';plt.rcParams['axes.unicode_minus']=False
NAMES=dict(buffer='老持仓保留范围',interval='调仓间隔',smooth='得分平滑',count='初始持股数',expansion='资产扩容',weights='四因子权重',windows='因子观察窗口',filters='股票池过滤')
def metrics(r):return [f"{r['final_equity']/10000:.2f}",f"{r['cagr']:.2%}",f"{r['max_drawdown']:.2%}",f"{r['sharpe']:.3f}",str(r['trades'])]
def table(headers,rows):return '<table><thead><tr>'+''.join('<th>'+html.escape(str(v))+'</th>' for v in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table>'
def changes(c):return json.dumps({k:v for k,v in c.items() if v!=p.Q['base'][k]},ensure_ascii=False)

def main():
    f=p.read(p.HERE/'frozen.json');gs=p.read(p.HERE/'group_selection.json');cs=p.read(p.HERE/'combined_selection.json')
    gt=p.read(p.HERE/'group_training.json');ct=p.read(p.HERE/'combined_training.json')
    confirmation=p.read(p.HERE/'confirmation/evaluation.json');held=p.read(p.HERE/'heldout/evaluation.json')
    selected=f['winner'];train=p.read(p.HERE/'training/runs'/(p.signature(selected['config'])+'.json'))
    periods=[('2019—2022开发',gt['baseline'],train),('2023选择',cs['baseline'],selected),('2024确认至11月29日',confirmation['baseline'],confirmation['winner']),('2025—2026-09-30隔离测试',held['baseline'],held['winner'])]
    periodrows=[]
    for label,base,win in periods:
        periodrows += [[label,'原版固定5只']+metrics(base),[label,'冻结综合候选']+metrics(win)]
    grouprows=[]
    for g,w in gs['winners'].items():
        gtrow=next((r for r in gt['results'] if r['id']==w['id']),gt['baseline'])
        later=next(r for r in held['groups'] if r['group']==g)
        grouprows.append([NAMES[g],w['id'],changes(w['config']),f"{gtrow['cagr']:.2%}",f"{w['cagr']:.2%}",f"{w['max_drawdown']:.2%}",f"{w['sharpe']:.3f}",f"{later['cagr']:.2%}",f"{later['max_drawdown']:.2%}",f"{later['sharpe']:.3f}"])
    trialrows=[]
    for r in gt['results']+ct['results']:
        sr=next((s for s in gs['results']+cs['results'] if s['id']==r['id']),None)
        trialrows.append([r['id'],NAMES.get(r['group'],'综合'),changes(r['config']),f"{r['cagr']:.2%}",f"{r['max_drawdown']:.2%}",f"{r['sharpe']:.3f}",str(r['trades']), '有效' if p.valid(r,gt['baseline'],'training') else '未通过训练约束',f"{sr['cagr']:.2%}" if sr else '未入围',len(r['issues'])+len(r['reference_differences'])])
    fig,axes=plt.subplots(2,2,figsize=(14,8))
    for ax,(stage,label) in zip(axes.flat,[('training','2019—2022开发'),('selection','2023选择'),('confirmation','2024确认'),('heldout','2025后隔离测试')]):
        for config,title in [(p.Q['base'],'原版固定5只'),(selected['config'],'冻结综合候选')]:
            curve=pd.read_parquet(p.HERE/stage/'runs'/(p.signature(config)+'_equity.parquet'))
            ax.plot(curve.date,curve.equity/100000,label=title)
        ax.set_title(label+'：独立10万元起步');ax.set_ylabel('净值');ax.grid(alpha=.2);ax.legend(fontsize=9)
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3,maxticks=5))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    fig.tight_layout();fig.savefig(p.HERE/'comparison.png',dpi=140);plt.close(fig)
    validation=p.read(p.HERE/'validation.json')
    flagged=[dict(id=r['id'],issues=r['issues'],reference_differences=r['reference_differences']) for r in gt['results'] if r['issues'] or r['reference_differences']]
    p.dump(p.HERE/'data_quality_exclusions.json',flagged)
    summary=dict(group_trials=160,data_flagged_group_trials=len(flagged),combined_templates=20,combined_unique=f['combined_unique'],unique_account_runs=validation['unique_account_runs'],
        winner=selected,confirmation_passed=confirmation['confirmation_passed'],periods=[dict(period=n,baseline=b,winner=w) for n,b,w in periods],validation=validation)
    p.dump(p.HERE/'summary.json',summary)
    document='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>D11控制变量160组与综合回测</title>
<style>body{font:15px 'Microsoft YaHei',sans-serif;line-height:1.7;color:#20344a;margin:30px auto;max-width:1450px;padding:0 20px}table{border-collapse:collapse;width:100%;font-size:13px}td,th{border:1px solid #ccd5df;padding:7px;text-align:right}td:first-child,td:nth-child(3){text-align:left}th{background:#edf3f8}img{max-width:100%}.wide{overflow:auto}code{white-space:pre-wrap}</style>
<h1>D11控制变量研究：8类×20组，再综合</h1>
<p>原上传D11固定5只为控制组，独立10万元账户，98%目标仓位。全部候选在运行前登记；每批只改变该类参数，费用、税费、T+1、停牌、涨跌停、整手与资金约束保持。160组各自完成2019—2022开发回放；每类最多3组进入2023选择，同时保留原版回退。各批获选参数按预登记的20个子集组合，再独立检验相互作用。</p>
<p>选择标准：开发至少40笔成交、平均仓位≥15%、最大回撤不超过同期原版2个百分点；2023至少10笔成交、同样仓位和回撤条件。合格方案按扣费年化收益、夏普、较低回撤和固定编号排序。2024仅确认，2025后仅展示；本阶段未据后段重新选择。当前是在此前已暴露历史上的隔离研究，不是真正未见的前瞻盲测。</p>'''
    document+=f"<p><b>冻结综合候选：{html.escape(selected['id'])}；变化：{html.escape(changes(selected['config']))}。</b>2024确认：{'通过' if confirmation['confirmation_passed'] else '未通过，保留研究候选，不替换原版'}。20个综合模板实际形成{f['combined_unique']}个不同配置，重复配置复用同一账本，没有伪称独立试验。160个开发配置中{len(flagged)}个有公司行动/除权参考价异常，记录但排除选优，不能视为有效绩效；详见data_quality_exclusions.json。</p>"
    document+='<h2>冻结候选与原版分段比较</h2>'+table(['阶段','版本','期末万元','年化收益','最大回撤','Sharpe','成交笔数'],periodrows)+'<img src="comparison.png">'
    document+='<h2>每类选择结果</h2><p>下面的2025后表现只用于评价既定赢家，不用于在各类之间重新选优。{}代表该类退回原参数。</p><div class="wide">'+table(['类别','选择编号','参数变化','开发年化','2023年化','2023回撤','2023夏普','2025后年化','2025后回撤','2025后夏普'],grouprows)+'</div>'
    document+='<h2>全部180个登记试验记录</h2><p>不同配置可能产生相同交易路径；未入围者没有在2023、2024或2025后追加择优评价。原版控制另计。市场回报的相互重叠意味着这些并非独立统计样本。</p><div class="wide">'+table(['编号','类别','相对原版变化','开发年化','开发回撤','开发夏普','成交笔数','开发约束','2023年化','异常数'],trialrows)+'</div>'
    document+=f"<h2>验证与限制</h2><p>{len(validation['checks'])}项检查通过；保存{validation['unique_account_runs']}次唯一分段账户回放。独立原函数核对5个特征配置，原版2020—2022逐日净值与既有账本一致。所有排名只用执行日前已完成行情；各阶段价格输入有日期边界和哈希清单。首次建仓额外触发，其后使用2018起交易日历固定相位，而非从首次入场重新计满间隔。</p>"
    document+='''<p>夏普＝扣费日简单收益均值÷样本标准差×√252，无风险利率0%，包含第一日相对初始现金的收益。年化收益使用实际日历天数。各段独立空仓10万元起步，不拼接为资金连续运行收益；2024-11-30至12-31不参与确认或选参。股息及送转股等公司行动由本地账本处理；未成交卖出不假设成交，实际只数可能暂时超过目标。</p>
<p>这是日线开盘撮合近似，不是SuperMind服务器成交；无强制期末清仓，未扣未来平仓费用和未实现分红税。股票池和供应商历史数据仍有完整性局限。新增160组加综合阶段的选择存在多重尝试过拟合风险，后段不得继续反馈调参。没有生成或验证新的平台入口，原策略未覆盖。</p></html>'''
    (p.HERE/'report.html').write_text(document,encoding='utf-8')
    print(json.dumps(dict(winner=selected['id'],config=selected['config'],confirmation=confirmation['confirmation_passed'],periods=[dict(period=n,baseline={k:b[k] for k in ['cagr','max_drawdown','sharpe']},winner={k:w[k] for k in ['cagr','max_drawdown','sharpe']}) for n,b,w in periods]),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
