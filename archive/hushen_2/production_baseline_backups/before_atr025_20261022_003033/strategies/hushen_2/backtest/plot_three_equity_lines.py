"""Single-start selected Hushen2 backtest versus two price-index benchmarks."""
from datetime import datetime
import argparse
import hashlib
import json
from pathlib import Path
import sys
import baostock as bs
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.font_manager import FontProperties
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'strategies/hushen_2'
SOURCE=BASE/'results/holdout_restricted/fixed_ioc_atr_price_q1_2020/attempt_20261020_051613'
sys.path.insert(0,str(ROOT/'tools'))
from daily_market_update import install_baostock_socket_safety


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--reuse-output',type=Path);args=parser.parse_args()
    audit=json.loads((ROOT/'data_updates/20261020/audit.json').read_text(encoding='utf-8'))
    assert audit['status']=='ok' and audit['target']=='2026-10-20'
    protocol=json.loads((SOURCE/'PROTOCOL.json').read_text(encoding='utf-8'))
    summary=json.loads((SOURCE/'SUMMARY.json').read_text(encoding='utf-8'))
    assert protocol['atr']=='price' and summary['status']=='complete'
    assert not summary['terminal_open_positions_max'] and not summary['terminal_pending_orders_max']
    curves=pd.read_parquet(SOURCE/'EQUITY_CURVES.parquet')
    selected=curves.loc[curves.start_ordinal.eq(1),['date','equity']].sort_values('date').reset_index(drop=True)
    start=pd.Timestamp(selected.date.iloc[0]);assert start==pd.Timestamp('2020-01-02')
    end=pd.Timestamp(audit['target']);old_end=pd.Timestamp(selected.date.iloc[-1])
    assert old_end==pd.Timestamp('2026-10-19')
    out=args.reuse_output or BASE/'results/holdout_restricted/equity_benchmark_chart'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')
    if args.reuse_output:
        assert out.resolve().parent==(BASE/'results/holdout_restricted/equity_benchmark_chart').resolve()
    else:out.mkdir(parents=True,exist_ok=False)
    install_baostock_socket_safety()
    if not args.reuse_output:
        response=bs.login();assert response.error_code=='0',response.error_msg
    indexes={};receipts=[]
    try:
        for code,name in [('sh.000001','sse'),('sh.000300','csi300')]:
            if args.reuse_output:
                frame=pd.read_parquet(out/f'{name}_price_index.parquet')
                assert frame.date.min()==start and frame.date.max()==end
                indexes[name]=frame
                receipts.append(dict(code=code,rows=len(frame),source='Retained successful BaoStock daily index response',
                    start=str(start.date()),end=str(end.date()),file_sha256=digest(out/f'{name}_price_index.parquet')))
                continue
            response=bs.query_history_k_data_plus(code,'date,code,close',start_date=str(start.date()),end_date=str(end.date()),frequency='d',adjustflag='3')
            assert response.error_code=='0',response.error_msg
            records=[]
            while response.next():records.append(response.get_row_data())
            assert response.error_code=='0' and records
            frame=pd.DataFrame(records,columns=response.fields)
            frame['date']=pd.to_datetime(frame.date);frame['close']=pd.to_numeric(frame.close)
            assert frame.date.min()==start and frame.date.max()==end
            assert frame.close.gt(0).all() and not frame.date.duplicated().any()
            frame=frame.sort_values('date').reset_index(drop=True)
            frame.to_parquet(out/f'{name}_price_index.parquet',index=False)
            indexes[name]=frame
            receipts.append(dict(code=code,rows=len(frame),error_code=response.error_code,source='BaoStock daily price index',
                start=str(start.date()),end=str(end.date()),file_sha256=digest(out/f'{name}_price_index.parquet')))
    finally:
        if not args.reuse_output:bs.logout()
    assert indexes['sse'].date.equals(indexes['csi300'].date)
    dates=indexes['sse'].date
    assert dates.loc[dates.le(old_end)].reset_index(drop=True).equals(selected.date)
    # Oct19 -> Oct20 moves the 37-day cutoff across a weekend only: no new signal session.
    old_cut=pd.Timestamp(protocol['last_signal_cutoff']);new_cut=end-pd.Timedelta(days=37)
    assert dates.loc[dates.gt(old_cut)&dates.le(new_cut)].empty
    tail=dates[dates.gt(old_end)]
    assert len(tail)==1 and tail.iloc[0]==end
    last_equity=float(selected.equity.iloc[-1])
    selected=pd.concat([selected,pd.DataFrame(dict(date=tail,equity=last_equity))],ignore_index=True)
    assert selected.date.equals(dates)
    assert selected.equity.iloc[0]==100000
    data=pd.DataFrame(dict(date=dates,hushen2=selected.equity/100000,
        sse=indexes['sse'].close/indexes['sse'].close.iloc[0],
        csi300=indexes['csi300'].close/indexes['csi300'].close.iloc[0]))
    data.to_parquet(out/'NORMALIZED_DAILY_CURVES.parquet',index=False)
    font=FontProperties(fname='C:/Windows/Fonts/msyh.ttc')
    plt.rcParams.update({'font.family':font.get_name(),'axes.unicode_minus':False,'font.size':11,'axes.spines.top':False,'axes.spines.right':False})
    fig,ax=plt.subplots(figsize=(12.8,6.6),dpi=180)
    fig.patch.set_facecolor('#ffffff');ax.set_facecolor('#ffffff')
    styles=[('sse','基线1 · 上证指数','#64748b','--',1.5),('csi300','基线2 · 沪深300','#d18622','-.',1.5),
            ('hushen2','沪深2 · 全期价格TR（回测）','#2563b4','-',2.)]
    for field,label,color,style,width in styles:
        ax.plot(data.date,data[field],label=label,color=color,linestyle=style,linewidth=width)
    ax.set_title('2020年至今 · 沪深2与指数基线',loc='left',pad=22,fontproperties=font,fontsize=16)
    ax.set_ylabel('归一化净值（起点 = 1）',fontproperties=font)
    ax.set_xlabel('日期',fontproperties=font)
    ticks=[start]+[pd.Timestamp(f'{year}-01-01') for year in range(2021,2027)]+[end]
    ax.set_xticks(ticks,labels=['2020','2021','2022','2023','2024','2025','2026','10-20'])
    ax.set_xlim(start,end)
    ax.grid(axis='y',color='#d8dee8',alpha=.7,linewidth=.6)
    ax.spines['left'].set_color('#a8b1bf');ax.spines['bottom'].set_color('#a8b1bf')
    ax.legend(loc='upper left',frameon=False,prop=font)
    # End values are kept distinct even when benchmark lines converge.
    yspan=float(data[['sse','csi300','hushen2']].max().max()-data[['sse','csi300','hushen2']].min().min())
    labels=sorted([(float(data[field].iloc[-1]),field,label,color) for field,label,color,_,_ in styles])
    floor=-np.inf
    for value,field,label,color in labels:
        y=max(value,floor+yspan*.045);floor=y
        ax.annotate(f'{value:.3f}  ({(value-1)*100:+.2f}%)',xy=(end,value),xytext=(8,(y-value)*ax.bbox.height/max(yspan,1)),
            textcoords='offset points',color=color,fontsize=10,va='center')
    fig.text(.085,.045,f'{start.date()} — {end.date()} ｜ 单一最早起点，10万元；非多起点均值、非实盘收益',fontproperties=font,color='#4b5563',fontsize=10)
    fig.text(.085,.013,'沪深2：固定股数＋五档剩余撤销、到期尾盘退出、扣费；指数：价格指数，不含股息。',fontproperties=font,color='#4b5563',fontsize=10)
    fig.subplots_adjust(left=.085,right=.86,bottom=.16,top=.88)
    fig.savefig(out/'THREE_EQUITY_LINES.png',dpi=180)
    plt.close(fig)
    report=dict(status='verified',start=str(start.date()),end=str(end.date()),start_ordinal=1,
        strategy='Selected uniform price-TR, fixed-quantity IOC, expiry-session close; pending orders occupy slots',
        extension='One extra trading day exact cash carry: no holdings/orders at Oct19, cutoff advances over non-trading weekend only',
        strategy_source=str(SOURCE),source_hashes={p.name:digest(p) for p in [SOURCE/'EQUITY_CURVES.parquet',SOURCE/'PROTOCOL.json',SOURCE/'SUMMARY.json']},
        benchmarks=receipts,initial_equity=100000,ending_values={k:float(data[k].iloc[-1]) for k in ['hushen2','sse','csi300']},
        chart_sha256=digest(out/'THREE_EQUITY_LINES.png'),script_sha256=digest(Path(__file__)),software_account_changed=False)
    (out/'CHART_AUDIT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(out,flush=True);print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
