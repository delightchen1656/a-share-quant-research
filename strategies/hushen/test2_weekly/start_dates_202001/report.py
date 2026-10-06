from pathlib import Path
import json
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
HERE=Path(__file__).resolve().parent
font_manager.fontManager.addfont(r'C:\Windows\Fonts\msyh.ttc');plt.rcParams.update({'font.family':'Microsoft YaHei','axes.unicode_minus':False,'axes.spines.top':False,'axes.spines.right':False})
x=pd.DataFrame(json.loads((HERE/'results.json').read_text(encoding='utf-8')))
summary={k:{'min':float(x[k].min()),'p10':float(x[k].quantile(.1)),'median':float(x[k].median()),'p90':float(x[k].quantile(.9)),'max':float(x[k].max())} for k in ['cagr','total_return','final_equity','max_drawdown']}
summary['first_start']=x.iloc[0].to_dict();summary['best_cagr_start']=x.loc[x.cagr.idxmax(),'start'];summary['worst_cagr_start']=x.loc[x.cagr.idxmin(),'start'];summary['count']=len(x)
(HERE/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
fig,axs=plt.subplots(1,3,figsize=(14,4.8))
for ax,k,scale,label in zip(axs,['cagr','final_equity','max_drawdown'],[100,.0001,100],['复合年化收益（%）','期末资产（万元）','最大回撤（%）']):
    values=x[k]*scale;ax.hist(values,bins=8,color='#3478ad',edgecolor='white');ax.axvline(values.median(),color='#dd8640',ls='--',label=f'中位数 {values.median():.2f}')
    ax.set_xlabel(label);ax.set_ylabel('起点数量');ax.legend(frameon=False);ax.grid(axis='y',alpha=.15)
fig.suptitle(f'D11周调仓：2020年1月{len(x)}个交易日起点分布',fontsize=17)
fig.text(.04,.03,'各10万元空仓起步，统一截至2026-09-30；原权重固定，本地日线近似撮合；起点路径相互重叠。',fontsize=10,color='#536575')
fig.tight_layout(rect=[0,.08,1,.91]);fig.savefig(HERE/'histogram.png',dpi=180);plt.close(fig)
fig,ax=plt.subplots(figsize=(11,4.5));ax.plot(pd.to_datetime(x.start),x.cagr*100,'o-',color='#3478ad');ax.set_ylabel('复合年化收益（%）');ax.set_xlabel('首次入场日');ax.grid(alpha=.2);fig.tight_layout();fig.savefig(HERE/'start_effect.png',dpi=160);plt.close(fig)
view=x.copy()
for k in ['total_return','cagr','max_drawdown','avg_exposure']:view[k]=view[k].map(lambda v:f'{v:.2%}')
for k in ['final_equity','fees','dividend_tax','final_cash','final_market_value']:view[k]=view[k].map(lambda v:f'{v:,.2f}')
view=view.rename(columns={'start':'入场日','end':'终点','final_equity':'期末资产','total_return':'累计收益','cagr':'年化','max_drawdown':'最大回撤','fees':'交易费用','dividend_tax':'已扣红利税','trades':'成交笔数','avg_exposure':'平均仓位','final_cash':'期末现金','final_market_value':'期末持仓','unresolved_actions':'未解释事件','capacity_rejections':'容量拒单'})
doc='''<!doctype html><html lang="zh"><meta charset="utf-8"><title>周调仓入场日分布</title><style>body{max-width:1400px;margin:35px auto;font-family:Microsoft YaHei,sans-serif;line-height:1.8;color:#24364b}img{width:100%}table{border-collapse:collapse;font-size:12px}td,th{padding:7px;border-bottom:1px solid #ddd;text-align:right}th{background:#edf2f7}</style><h1>D11原权重周调仓：2020年1月逐日起投</h1><p>每周首个交易日调仓，首次入场立即建仓，周内继续原目标重试及ST处理。每日频率、5只、98%目标仓位；系数-0.35/-0.20/+0.25/-0.20。</p><p>每个起点独立10万元现金账户，统一截至2026-09-30收盘，不强制卖出期末持仓。费用包含佣金万三最低5元、单边0.1%滑点、历史印花税与过户费、持有期红利税。以分红到账日、红股上市日和T+1管理现金及可卖股数。</p><img src="histogram.png"><img src="start_effect.png"><h2>逐起点数据</h2>'''+view.to_html(index=False)+'''<h2>结果边界</h2><p>日线开盘撮合不能等同SuperMind服务器或实盘成交；送转零股和部分税务分类为近似，历史股票池完整性未证明。原始价/当期前收盘链用于特征，实际公司行动用于记账。无参数优化；本次是既定策略的历史回放，非训练隔离测试。多个起点共享绝大多数后续行情，不是独立统计样本。无法仅由本图判断周调仓优于20日调仓，需另做同口径对照。</p></html>'''
(HERE/'report.html').write_text(doc,encoding='utf-8');print(json.dumps(summary,ensure_ascii=False,indent=2))
