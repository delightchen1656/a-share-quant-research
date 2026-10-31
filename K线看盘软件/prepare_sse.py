"""Export already-audited research evidence; no downloads or strategy imports."""
from pathlib import Path
import hashlib
import json
import pandas as pd
from sse_data import reversals

HERE=Path(__file__).resolve().parent;ROOT=next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
SOURCE=ROOT/'沪深1研究/results/holdout_restricted/q1_2019_to_20261029_open005_guaranteed'


def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):
    tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');tmp.replace(p)


def main():
    source=SOURCE/'sse_reversal10_first5/sse_2016_to_20261029.json'
    expected=read(SOURCE/'sse_reversal10_first5/PROTOCOL.json')['sse_input_sha256'];assert sha(source)==expected
    rows=read(source)['rows'];frame=pd.DataFrame(rows)
    assert set(frame.code)=={'sh.000001'} and frame.date.is_unique
    frame=frame.sort_values('date')
    for c in ['open','high','low','close']:frame[c]=pd.to_numeric(frame[c],errors='raise');assert frame[c].gt(0).all()
    assert (frame.high>=frame[['open','close']].max(axis=1)).all() and (frame.low<=frame[['open','close']].min(axis=1)).all()
    assert frame.date.iloc[-1]=='2026-10-29'
    simple=frame[['date','close']].to_dict('records');events=reversals(simple)
    assert events==read(SOURCE/'sse_reversal10_first5/REVERSALS.json'),'Export classifier differs from audited research'
    stats_path=SOURCE/'continuous_sse_stages/ANNUALIZED_STAGE_SUMMARY.json';stats=read(stats_path)
    risk={(r['period_start'],r['period_end']):r for r in stats}
    phases=[]
    for i,event in enumerate(events):
        end=events[i+1]['pivot'] if i+1<len(events) else frame.date.iloc[-1]
        phase=dict(id=i+1,state=event['mode'],start=event['pivot'],end=end,
            confirmed=event['confirmed'],pivot_close=event['pivot_close'],confirm_close=event['confirm_close'],
            marker_price=event['pivot_close'],marker_basis='收盘价峰谷',
            unfinished=i+1==len(events),stats=risk.get((event['pivot'],end)))
        phases.append(phase)
    for n in [5,10,20,60]:frame['ma'+str(n)]=frame.close.rolling(n,min_periods=n).mean()
    frame['change']=frame.close.pct_change()
    fields=['date','open','high','low','close','change','ma5','ma10','ma20','ma60']
    bars=[]
    for record in frame[fields].to_dict('records'):
        bars.append([None if pd.isna(record[k]) else record[k] for k in fields])
    data=dict(code='000001.SH',name='上证指数',threshold=.10,first=frame.date.iloc[0],last=frame.date.iloc[-1],
        bars=bars,fields=fields,events=events,phases=phases,source='BaoStock · 上证价格指数 · 日OHLC',
        source_sha256=sha(source),annual_stats_sha256=sha(stats_path),
        group_stats=read(SOURCE/'continuous_sse_stages/TIME_WEIGHTED_REGIME_SUMMARY.json'),
        model_note='沪深1 · 2019Q1全部58个起点 · 各10万元连续账户 · 单边0.5%理想化成交 · 未按阶段重开',
        rule='仅按收盘价：从最高收盘反向下跌10%确认熊市，从最低收盘反向上涨10%确认牛市。',
        interpretation='阴影按事后确认的峰谷划分。橙色虚线是之后才出现的反转确认日。峰谷当日不能预知未来标签。最后一段进行中。',
        chart_volume='Not included in the audited index export; no volume inferred.')
    visual_root=SOURCE/'continuous_sse_stages/manual_visual_validation'
    visual_protocol=read(visual_root/'MANUAL_VISUAL_PROTOCOL.json')
    assert visual_protocol['usage']=='historical_visual_validation_only'
    assert not visual_protocol['future_trading_use'] and not visual_protocol['future_parameter_selection_use'] and not visual_protocol['automatic_extension']
    assert visual_protocol['source_index_sha256']==sha(source)
    visual_stats=read(visual_root/'ANNUALIZED_STAGE_SUMMARY.json')
    stats_by_id={r['id']:r for r in visual_stats};visual_phases=[]
    for i,stage in enumerate(visual_protocol['stages']):
        point=visual_protocol['points'][i]
        assert point['date']==stage['period_start']
        original=frame.loc[frame.date.eq(point['date'])].iloc[0]
        field='low' if point['kind']=='bottom' else 'high'
        assert float(original[field])==point['price'],'Visual marker must be an actual candle high/low'
        visual_phases.append(dict(id=stage['id'],state=stage['state'],start=stage['period_start'],end=stage['period_end'],
            confirmed=None,marker_price=point['price'],marker_basis='盘中低点' if field=='low' else '盘中高点',
            reason=point['reason'],unfinished=stage['unfinished'],stats=stats_by_id[stage['id']]))
    data['default_method']='visual_validation'
    data['visual_validation']=dict(usage='historical_visual_validation_only',cutoff=visual_protocol['cutoff'],
        rule='事后目测主要K线波段顶底；使用所选日期的盘中高低点，不使用固定反转百分比。',
        future_trading_use=False,future_parameter_selection_use=False,automatic_extension=False,
        protocol_sha256=sha(visual_root/'MANUAL_VISUAL_PROTOCOL.json'),stats_sha256=sha(visual_root/'ANNUALIZED_STAGE_SUMMARY.json'),
        phases=visual_phases,group_stats=read(visual_root/'TIME_WEIGHTED_REGIME_SUMMARY.json'))
    destination=HERE.parent/'K线数据/指数/上证看盘';destination.mkdir(exist_ok=True);snapshots=destination/'snapshots';snapshots.mkdir(exist_ok=True)
    encoded=json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8');digest=hashlib.sha256(encoded).hexdigest()
    name='sse_'+data['last'].replace('-','')+'_'+digest[:12]+'.json';path=snapshots/name
    if path.exists():assert path.read_bytes()==encoded
    else:path.write_bytes(encoded)
    write(destination/'CURRENT.json',dict(path='snapshots/'+name,sha256=digest,cutoff=data['last']))
    write(HERE/'runtime/SSE_EXPORT_VALIDATION.json',dict(bars=len(bars),phases=len(phases),research_phases=len(stats),
        original_events_exact_match=True,all_ohlc_valid=True,source_sha256=sha(source),export_sha256=digest,read_only_export=True))
    print('SSE_READY',len(bars),'bars',len(phases),'phases',len(stats),'model stages',data['last'])


if __name__=='__main__':main()
