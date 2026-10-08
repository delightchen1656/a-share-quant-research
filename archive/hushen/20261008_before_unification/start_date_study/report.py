from pathlib import Path
import json, html
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
HERE=Path(__file__).resolve().parent
font_manager.fontManager.addfont(r'C:\Windows\Fonts\msyh.ttc')
plt.rcParams.update({'font.family':'Microsoft YaHei','axes.unicode_minus':False,'font.size':11,'axes.spines.top':False,'axes.spines.right':False})
x=pd.read_csv(HERE/'start_results.csv',parse_dates=['start','end'])
assert len(x)==116 and x.groupby('model').size().eq(58).all()
names={'R08':'基准1 · R08 截止版','D11':'测试2 · D11 提速截止版'}
colors={'R08':'#3267b2','D11':'#df8542'}
summary={};rows=[]
for k,q in x.groupby('model',sort=False):
    best=q.loc[q.cagr.idxmax()];worst=q.loc[q.cagr.idxmin()]
    summary[k]={'count':len(q),'cagr_min':q.cagr.min(),'cagr_p10':q.cagr.quantile(.1),'cagr_median':q.cagr.median(),'cagr_p90':q.cagr.quantile(.9),'cagr_max':q.cagr.max(),
      'cagr_range_pp':100*(q.cagr.max()-q.cagr.min()),'cagr_p90_p10_pp':100*(q.cagr.quantile(.9)-q.cagr.quantile(.1)),
      'final_min':q.final_equity.min(),'final_median':q.final_equity.median(),'final_max':q.final_equity.max(),
      'final_max_min_ratio':q.final_equity.max()/q.final_equity.min(),
      'best_cagr_start':str(best.start.date()),'worst_cagr_start':str(worst.start.date()),
      'drawdown_median':q.max_drawdown.median(),'drawdown_worst':q.max_drawdown.min(),'drawdown_best':q.max_drawdown.max(),
      'unresolved_actions_max':int(q.unresolved_actions.max()),'capacity_rejections_max':int(q.capacity_rejections.max())}
    z=summary[k];rows.append([names[k],f'{z["cagr_min"]:.2%}',f'{z["cagr_median"]:.2%}',f'{z["cagr_max"]:.2%}',f'{z["cagr_range_pp"]:.2f}',f'{z["final_min"]/1e4:.2f}',f'{z["final_median"]/1e4:.2f}',f'{z["final_max"]/1e4:.2f}',f'{-z["drawdown_worst"]:.2%}'])
(HERE/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
fig,axs=plt.subplots(2,2,figsize=(13.2,8.4),sharey='row')
bins=np.arange(np.floor(x.cagr.min()*400)/4,np.ceil(x.cagr.max()*400)/4+.26,.25)
ebins=np.arange(np.floor(x.final_equity.min()/5000)/2,np.ceil(x.final_equity.max()/5000)/2+.51,.5)
for col,k in enumerate(['R08','D11']):
    q=x[x.model==k]
    for row,values,bb,label in [(0,q.cagr*100,bins,'复合年化收益率（%）'),(1,q.final_equity/1e4,ebins,'期末总资产（万元）')]:
        ax=axs[row,col];ax.hist(values,bins=bb,color=colors[k],alpha=.88,edgecolor='white')
        ax.set_xlim(values.min()-(.25 if row==0 else .5),values.max()+(.25 if row==0 else .5))
        ax.axvline(values.median(),color='#263646',ls='--',lw=1.5,label=f'中位数 {values.median():.2f}')
        ax.set_xlabel(label);ax.set_ylabel('起点数量（共58个）');ax.grid(axis='y',alpha=.15);ax.legend(frameon=False)
        ax.set_title(names[k] if row==0 else '同一终点的资金分布',loc='left',fontweight='bold')
fig.suptitle('入场日期敏感性：2021年一季度每日起投10万元',fontsize=18,fontweight='bold',x=.07,ha='left')
fig.text(.07,.91,'58个交易日起点 × 2个冻结策略 ｜ 统一截至2026-09-30收盘 ｜ 本地扣费日线近似回测',color='#506070')
fig.text(.07,.052,'各列横轴按自身范围放大；年化组距均为0.25个百分点，资产组距均为0.5万元。',fontsize=10,color='#65707a')
fig.text(.07,.023,'基准1的09:31成交以日开盘近似；并非SuperMind复现。训练期重叠，起点样本相互重叠，不代表独立样本外。',fontsize=10,color='#65707a')
fig.tight_layout(rect=[.02,.08,.99,.89]);fig.savefig(HERE/'histogram.png',dpi=180);plt.close(fig)
fig,axs=plt.subplots(2,1,figsize=(12.8,7.5),sharex=True)
for k in ['R08','D11']:
    q=x[x.model==k].sort_values('start')
    axs[0].plot(q.start,q.cagr*100,'o-',ms=3,color=colors[k],label=names[k]);axs[1].plot(q.start,q.final_equity/1e4,'o-',ms=3,color=colors[k])
axs[0].set_ylabel('复合年化（%）');axs[1].set_ylabel('期末资产（万元）');axs[1].set_xlabel('2021年首次入场日')
for ax in axs:ax.grid(alpha=.15)
axs[0].legend(frameon=False);fig.suptitle('同一策略，仅改变首次入场日',fontsize=17);fig.tight_layout();fig.savefig(HERE/'start_date_effect.png',dpi=180);plt.close(fig)
table=pd.DataFrame(rows,columns=['策略','最低年化','中位年化','最高年化','年化极差(百分点)','最少资产(万元)','中位资产(万元)','最多资产(万元)','最坏最大回撤']).to_html(index=False)
detail=x.copy();detail['策略']=detail.model.map(names)
detail=detail[['策略','start','final_equity','total_return','cagr','max_drawdown','fees','dividend_tax','final_cash','final_market_value']]
detail.columns=['策略','起点','期末资产','累计收益','年化收益','最大回撤','交易费用','已扣红利税','期末现金','期末持仓金额']
for c in ['累计收益','年化收益','最大回撤']:detail[c]=detail[c].map(lambda v:f'{v:.2%}')
for c in ['期末资产','交易费用','已扣红利税','期末现金','期末持仓金额']:detail[c]=detail[c].map(lambda v:f'{v:,.2f}')
protocol=json.loads((HERE/'protocol.json').read_text(encoding='utf-8'))
methods=''.join(f'<li><b>{html.escape(k)}：</b>{html.escape(str(v))}</li>' for k,v in protocol.items() if k!='sources')
issues=json.loads((HERE/'unresolved_actions.json').read_text(encoding='utf-8'))
warning=f'<p class="warning">未解释的持仓公司行动/退市事件：{len(issues)}。'+('存在未解决项目，结果为待核验近似值。' if issues else '本次持仓期间参考价变更均有公司行动记录。')+'</p>'
warning += '<p><b>结论：</b>本次样本中基准1对入场日更稳定：年化极差2.51个百分点、期末资产最高比最低高14.54%；测试2分别为6.52个百分点、38.35%。测试2的中间80%起点年化为32.68%—35.65%，高收益端少数起点把极差拉大。基准1对应为15.67%—17.21%。</p><p>最大回撤对起点的敏感性很小：基准1为14.85%—15.48%，测试2为41.13%—41.77%。基准1所有路径的最大回撤谷底在2022-03-15，测试2均在2024-02-07。换一个起点并没有避开测试2的深回撤。这里只评价2021年一季度入场的历史结果，不外推其他年份或未来入场。</p>'
doc=f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>沪深入场日期敏感性</title><style>body{{font-family:Microsoft YaHei,sans-serif;max-width:1300px;margin:40px auto;color:#203247;line-height:1.65}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{padding:8px;border-bottom:1px solid #dce2e8;text-align:right}}th{{background:#edf2f7}}img{{width:100%}}li{{margin:8px 0}}.warning{{background:#fff3d7;padding:12px}}summary{{cursor:pointer;font-size:20px}}</style><h1>沪深基准1 / 测试2：不同入场日的影响</h1><p>本金各10万元；2021-01-04至2021-03-31的58个交易日分别空仓起步，统一结束于2026-09-30。固定20241130截止权重，不重新拟合。</p>{warning}{table}<img src="histogram.png"><img src="start_date_effect.png"><h2>口径与边界</h2><ul>{methods}</ul><p>佣金与税费已计入。期末含未卖出持仓与应收红利，不扣假设未来卖出费用；尚未卖出的递延红利税不预扣。公司行动参考价差异另见reference_differences.json，差异可能来自差异化分红虚拟除权。</p><details><summary>116条逐起点结果</summary>{detail.to_html(index=False)}</details><h2>规则来源</h2><ul>{''.join('<li><a href="'+u+'">'+u+'</a></li>' for u in protocol['sources'])}</ul></html>'''
(HERE/'report.html').write_text(doc,encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
