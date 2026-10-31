"""Plot frozen top-ten excess results; no backtest or strategy mutation."""
from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection,PolyCollection
from matplotlib.font_manager import FontProperties,fontManager
from matplotlib.backends.backend_pdf import PdfPages

ROOT=Path(__file__).resolve().parent/'holdout_restricted/leaders_fixed_20261031'
OUT=ROOT/'charts_top10_excess'
UP='#d94b57';DOWN='#138976';STRATEGY='#2161c4';HOLD='#e3952c'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def panel(ax,nav,q,t,price=True,small=False):
    x=np.arange(len(q));lookup={day:i for i,day in enumerate(q.date)}
    if price:
        colors=np.where(q.close.ge(q.open),UP,DOWN)
        ax.add_collection(LineCollection([[(i,l),(i,h)] for i,l,h in zip(x,q.low,q.high)],colors=colors,linewidths=.45 if small else .6))
        verts=[[(i-.34,o),(i-.34,c),(i+.34,c),(i+.34,o)] for i,o,c in zip(x,q.open,q.close)]
        ax.add_collection(PolyCollection(verts,facecolors=colors,edgecolors=colors,linewidths=.25))
        for side,col,marker in [('buy',UP,'^'),('sell',DOWN,'v')]:
            indices=[lookup[z] for z in t[side+'_date'] if z in lookup]
            prices=[float(q.iloc[i].low)*.98 if side=='buy' else float(q.iloc[i].high)*1.02 for i in indices]
            ax.scatter(indices,prices,s=12 if small else 24,marker=marker,c=col,label='买入' if side=='buy' else '卖出',zorder=4)
        ax.set_ylim(float(q.low.min())*.9,float(q.high.max())*1.08);ax.set_ylabel('前复权价格（元）')
    else:
        ax.plot(x,nav.nav,color=STRATEGY,lw=1.25 if small else 1.7,label='策略净值')
        ax.plot(x,nav.buyhold_nav,color=HOLD,lw=1.1 if small else 1.5,label='买入持有',alpha=.9)
        ax.axhline(1,color='#7b8795',lw=.6,ls='--');ax.set_ylabel('净值（初始=1）')
        ax.set_ylim(bottom=0)
    idx=[0]+[i for i in range(1,len(q)) if q.date.iloc[i][:4]!=q.date.iloc[i-1][:4]]
    ax.set_xticks(idx);ax.set_xticklabels([q.date.iloc[i][:4] for i in idx],fontsize=8 if small else 10)
    ax.set_xlim(-10,len(q)+10);ax.grid(axis='y',color='#e4e9f0',lw=.6);ax.set_axisbelow(True)
    ax.spines[['top','right']].set_visible(False);ax.spines[['left','bottom']].set_color('#c5cdd8')
    ax.tick_params(colors='#516070',labelsize=8 if small else 10)
    ax.legend(loc='upper left',frameon=False,ncol=2,fontsize=8 if small else 10)

def main():
    OUT.mkdir(exist_ok=True)
    font=Path('C:/Windows/Fonts/msyh.ttc');assert font.exists();fontManager.addfont(str(font));plt.rcParams.update({'font.family':FontProperties(fname=font).get_name(),'axes.unicode_minus':False,'figure.facecolor':'white','axes.titlesize':11})
    m=json.loads((ROOT/'MANIFEST.json').read_text(encoding='utf8'))
    rank=pd.read_csv(ROOT/'top10_excess.csv',dtype={'code':str});assert sha(ROOT/'top10_excess.csv')==m['outputs']['top10_excess.csv']
    allseries=[];checks=[]
    for number,r in enumerate(rank.itertuples(),1):
        p=ROOT/'inputs'/f'{r.code}_qfq.parquet';item=next(x for x in m['inputs'] if x['code']==r.code and x['kind']=='qfq');assert sha(p)==item['sha256']
        for file in [f'details/{r.code}_nav.csv',f'details/{r.code}_trades.csv']:assert (ROOT/file).exists()
        nav=pd.read_csv(ROOT/'details'/f'{r.code}_nav.csv');q=pd.read_parquet(p);q['date']=pd.to_datetime(q.date).dt.strftime('%Y-%m-%d');q=q[q.date.isin(nav.date)&pd.to_numeric(q.tradestatus).eq(1)&pd.to_numeric(q.volume).gt(0)].reset_index(drop=True)
        t=pd.read_csv(ROOT/'details'/f'{r.code}_trades.csv');assert q.date.tolist()==nav.date.tolist();assert np.isclose((nav.nav.iloc[-1]-1)*100,r.total_return_pct)
        checks.append(dict(code=r.code,nav_sha256=sha(ROOT/'details'/f'{r.code}_nav.csv'),trades_sha256=sha(ROOT/'details'/f'{r.code}_trades.csv'),bars=len(q),ending_nav_verified=True));allseries.append((number,r,nav,q,t))
    with PdfPages(OUT/'超额前10_K线与策略净值.pdf') as pdf:
        for number,r,nav,q,t in allseries:
            fig,axes=plt.subplots(2,1,figsize=(15,8.5),gridspec_kw={'height_ratios':[1.1,1]},layout='constrained')
            fig.suptitle(f'{number:02d}  {r.name}（{r.code}）｜K线与策略净值',fontsize=18,fontweight='bold')
            panel(axes[0],nav,q,t,True);panel(axes[1],nav,q,t,False)
            axes[0].set_title('实际交易日等距 · 红涨绿跌 · 三角标记为策略成交日',loc='left',color='#516070')
            axes[1].set_title(f'累计收益 {r.total_return_pct:+.2f}%    持有 {r.buyhold_return_pct:+.2f}%    超额 {r.excess_return_pp:+.2f}个百分点    最大回撤 {r.max_drawdown_pct:.2f}%',loc='left')
            fig.supxlabel('2020-01-02—2026-10-30｜前复权毛收益、理想开盘成交，未扣费；当前分类事后筛选，非独立后验。',fontsize=9,color='#657184')
            fig.savefig(OUT/f'{number:02d}_{r.code}.png',dpi=140);pdf.savefig(fig);plt.close(fig)
    for page in range(2):
        fig,axes=plt.subplots(5,2,figsize=(17,16),layout='constrained')
        fig.suptitle(f'超额收益前10｜第{page*5+1}—{page*5+5}名    左：K线与买卖点    右：策略/持有净值',fontsize=19,fontweight='bold')
        for row,(number,r,nav,q,t) in enumerate(allseries[page*5:(page+1)*5]):
            panel(axes[row,0],nav,q,t,True,True);panel(axes[row,1],nav,q,t,False,True)
            axes[row,0].set_title(f'{number}. {r.name} {r.code}',loc='left',fontweight='bold')
            axes[row,1].set_title(f'策略 {r.total_return_pct:+.1f}%｜持有 {r.buyhold_return_pct:+.1f}%｜超额 {r.excess_return_pp:+.1f}点｜回撤 {r.max_drawdown_pct:.1f}%',loc='left',fontsize=10)
        fig.supxlabel('2020-01-02—2026-10-30｜各股纵轴独立，净值初始=1。前复权毛收益、理想成交、未扣费；事后筛选。',fontsize=10,color='#657184')
        fig.savefig(OUT/f'overview_{page+1}.png',dpi=140);plt.close(fig)
    save=dict(source_rank_sha256=sha(ROOT/'top10_excess.csv'),source_checks=checks,script_sha256=sha(Path(__file__)),outputs={p.name:sha(p) for p in OUT.iterdir() if p.suffix in ['.png','.pdf']})
    (OUT/'CHART_MANIFEST.json').write_text(json.dumps(save,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps({'charts':10,'overviews':2,'pdf_pages':10,'path':str(OUT)},ensure_ascii=False))

if __name__=='__main__':main()
