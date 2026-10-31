"""Plot equal-weight mean assets, retaining cash before each account's start."""
from pathlib import Path
import argparse
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.ticker import FuncFormatter


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('result_dir',type=Path)
    args=parser.parse_args()
    out=args.result_dir.resolve()
    font=FontProperties(fname='C:/Windows/Fonts/msyh.ttc')
    plt.rcParams['font.family']=font.get_name()
    plt.rcParams['axes.unicode_minus']=False
    frame=pd.read_csv(out/'all_starts.csv')
    calendar=pd.DatetimeIndex(pd.to_datetime(pd.read_parquet(out/'runtime_inputs/calendar.parquet').date))
    calendar=calendar[(calendar>=pd.to_datetime(frame.actual_start).min()) & (calendar<=pd.to_datetime(frame.end).max())]
    curves=pd.DataFrame(index=calendar)
    for mode in ['same_day','next_session']:
        group=frame.loc[frame.cash_mode.eq(mode)]
        paths=[]
        for r in group.itertuples():
            f=out/'runtime_inputs/runs'/(mode+'_'+r.actual_start+'_equity.parquet')
            q=pd.read_parquet(f).set_index('date').equity
            q.index=pd.to_datetime(q.index)
            assert abs(q.iloc[-1]-r.final_equity)<1e-7
            s=q.reindex(calendar)
            s.loc[s.index<pd.Timestamp(r.actual_start)]=100000.
            assert not s.isna().any()
            paths.append(s.to_numpy())
        curves[mode]=np.mean(paths,axis=0)
        assert abs(curves[mode].iloc[-1]-group.final_equity.mean())<1e-7
    curves.index.name='date'
    curves.to_csv(out/'mean_asset_curves.csv',encoding='utf-8-sig')
    colors={'same_day':'#1976b8','next_session':'#e48628'}
    labels={'same_day':'卖出款当天可用','next_session':'卖出款下一交易日可用'}
    fig,ax=plt.subplots(figsize=(12.8,6.8),dpi=180)
    fig.patch.set_facecolor('#fafbfc');ax.set_facecolor('white')
    for mode in curves:
        y=curves[mode]/10000
        ax.plot(curves.index,y,lw=1.8,color=colors[mode],label=labels[mode])
        ax.scatter(curves.index[-1],y.iloc[-1],color=colors[mode],s=22,zorder=4)
        ax.annotate(f'{y.iloc[-1]:.2f}万元',(curves.index[-1],y.iloc[-1]),xytext=(9,0),
                    textcoords='offset points',va='center',color=colors[mode],fontsize=11,fontweight='bold')
    ax.set_title('沪深1：卖出款可用时间对平均资产的影响',loc='left',fontsize=17,pad=39,fontweight='bold')
    ax.text(0,1.035,'2020年一季度58个独立起点 · 每户10万元 · 统一至2026年10月28日',
            transform=ax.transAxes,fontsize=10.5,color='#566273')
    ax.set_ylabel('平均账户总资产（万元）',fontsize=11)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v,p:f'{v:,.0f}'))
    ax.grid(axis='y',color='#dfe5ec',lw=.7)
    ax.spines[['top','right']].set_visible(False)
    ax.spines[['left','bottom']].set_color('#c5cdd8')
    ax.legend(loc='upper left',frameon=False,fontsize=11)
    ax.set_xlim(curves.index[0],curves.index[-1]+pd.Timedelta(days=290))
    ax.set_ylim(bottom=0)
    fig.text(.08,.067,'两组均为单边滑点0.2%、佣金万三最低5元、卖出印花税0.1%、无单列过户费；仅现金可用时间不同。',fontsize=9,color='#566273')
    fig.text(.08,.035,'曲线为58个账户每日总资产的算术平均，未入场账户按10万元现金计入；不是单一账户，也不是平均年化曲线。',fontsize=9,color='#566273')
    fig.subplots_adjust(left=.08,right=.94,bottom=.15,top=.83)
    fig.savefig(out/'mean_asset_comparison.png',facecolor=fig.get_facecolor(),dpi=180)
    fig.savefig(out/'mean_asset_comparison.svg',facecolor=fig.get_facecolor())
    plt.close(fig)
    print(out/'mean_asset_comparison.png')


if __name__=='__main__':main()
