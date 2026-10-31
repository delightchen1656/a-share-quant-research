"""User-requested exclusion, applied to the fixed v1 signals without backfilling."""
import json
from decimal import Decimal, ROUND_HALF_UP

import numpy as np
import pandas as pd

from study import SOURCE, ROOT, digest, summarize

OUT=ROOT/'results_v2_no_limit_streaks'


def limit_flags(raw):
    """Conservative inferred historical limits, not exchange official limit-price data.

    Only 2018-2024 mainboard data: regular 10%, historical ST 5%.
    Exemptions/relisting periods cannot be exhaustively identified in this snapshot.
    Below-theoretical-limit bars are also flagged conservatively rather than allowed.
    """
    r=raw.copy()
    good=(pd.to_numeric(r.tradestatus)==1)&(r.volume>0)&(r.open>0)&(r.preclose>0)
    r=r.loc[good].reset_index(drop=True)
    st=pd.to_numeric(r.isST,errors='coerce')
    if st.isna().any():raise ValueError('Unknown historical ST state')
    prices=np.array([float((Decimal(str(p))*(Decimal('.95') if s==1 else Decimal('.90'))).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)) for p,s in zip(r.preclose,st)])
    down=(r.close.to_numpy()<=prices+.005)
    one_price=down & ((r.high-r.low).to_numpy()<=.005)
    f=pd.DataFrame({'date':r.date.astype(str),'inferred_down_close':down,'one_price_down':one_price})
    # Prior 20 observed trading bars plus D0. A pair must be wholly inside it.
    pair=pd.Series(down & np.r_[False,down[:-1]])
    f['reject_consecutive2']=pair.rolling(20,min_periods=1).max().astype(bool)
    f['down_count21']=pd.Series(down).rolling(21,min_periods=1).sum().astype(int)
    f['one_price_count21']=pd.Series(one_price).rolling(21,min_periods=1).sum().astype(int)
    return f


def verify():
    def bars(closes,st=0):
        return pd.DataFrame(dict(date=[f'd{i}' for i in range(len(closes))],close=closes,
             open=closes,high=closes,low=closes,preclose=[10]*len(closes),volume=[100]*len(closes),tradestatus=['1']*len(closes),isST=[st]*len(closes)))
    assert limit_flags(bars([9,9,10])).reject_consecutive2.tolist()==[False,True,True]
    assert not limit_flags(bars([9,10,9])).reject_consecutive2.any()
    assert limit_flags(bars([9.5,9.5],1)).reject_consecutive2.iloc[-1]
    assert not limit_flags(bars([9.5,9.5],0)).reject_consecutive2.any()
    r=bars([9,9]+[10]*21)
    assert limit_flags(r).reject_consecutive2.iloc[20]
    assert not limit_flags(r).reject_consecutive2.iloc[21]
    a=limit_flags(r.iloc[:10]);b=limit_flags(r)
    pd.testing.assert_frame_equal(a,b.iloc[:10])


def main():
    verify();OUT.mkdir(exist_ok=True)
    d=pd.read_parquet(ROOT/'results_v1/events.parquet')
    m=json.loads((SOURCE/'MANIFEST.json').read_text(encoding='utf8'))
    hashes={x['relative_path'].replace('\\','/'):x['sha256'] for x in m['files']}
    frames=[]
    for code in sorted(d.code.unique()):
        p=SOURCE/'raw'/(code+'.parquet')
        assert digest(p)==hashes['raw/'+code+'.parquet']
        raw=pd.read_parquet(p).sort_values('date').reset_index(drop=True)
        assert raw.date.astype(str).max()<='2024-12-31'
        f=limit_flags(raw);f['code']=code;frames.append(f)
    flags=pd.concat(frames,ignore_index=True)
    d=d.merge(flags,on=['code','date'],how='left',validate='one_to_one')
    assert d.reject_consecutive2.notna().all()
    d.to_parquet(OUT/'events.parquet',index=False)
    variants={'基础超跌转阳':pd.Series(True,index=d.index),
              '低于MA20至少10%':d.below_ma20<=-.10,
              '信号量≥前20日均量1.2倍':d.volume_ratio>=1.2,
              '信号量≥前20日均量1.5倍':d.volume_ratio>=1.5,
              '前3日缩量':d.last3_volume_ratio<=.8}
    rows=[];years=[]
    for pool,pm in [('样本池',pd.Series(True,index=d.index)),('龙头子样本',d.is_leader)]:
        for rule,rm in variants.items():
            orig=d.loc[pm&rm];kept=orig.loc[~orig.reject_consecutive2];removed=orig.loc[orig.reject_consecutive2]
            row=dict(pool=pool,rule=rule,before=summarize(orig),after=summarize(kept),removed=summarize(removed))
            rows.append(row)
            for y,g in kept.groupby('year'):years.append(dict(pool=pool,rule=rule,year=int(y),**summarize(g)))
    result=dict(boundary='2024-12-31',rows=rows,yearly=years,
        exclusion='Any consecutive >=2 inferred close-down-limit bars wholly within prior20 observed sessions plus D0; no future exclusions, no backfilled signals.',
        limit_basis='Raw preclose and historical isST, 10% regular / 5% ST, half-up cents. Inferred only: exemptions and delisting not fully auditable.',
        verification='Synthetic normal/ST/nonconsecutive/window expiry/prefix invariance tests passed.',
        unchanged='v1 signal rules and next-official-session to D60 price-path labels retained.')
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    lines=['方向2：触及+10%与剔除连续跌停形态',
        '范围：原有白名单947只主板股票，研发截止2024年底；当前龙头归属回看，仅描述性研究，非盲测。',
        '新增硬排除：信号日前20个有效交易日加信号日本身，存在连续至少2日疑似收盘跌停即剔除。不只剔除一字跌停；不使用信号之后跌停作为过滤条件。',
        '没有官方历史涨跌停价字段。用原始preclose、当日isST及历史普通10%/ST5%规则按分四舍五入推定，收盘低于推定限价也保守剔除。',
        '存在例外日期/退市整理/ST切换等误识别风险，因此称疑似跌停而非官方精确跌停。停牌后相邻有效K线保守视作相邻。',
        '下列数量均为D60完整的样本；完整标签口径不变；固定原信号清单上删除，不补入新信号。',
        '指标仍为信号次一正式交易日开盘起D1至D60前复权价格路径，不是账户收益或成交胜率。',
        '不按未来极值删除任何连续跌停样本；未剔除涨超100%的极端值。']
    for pool in ['样本池','龙头子样本']:
        lines+=['',pool,'条件 | 原数量 | 剔除 | 保留 | +10%触及前→后 | 跌超30%前→后 | 保留组平均最大涨幅/跌幅']
        for x in rows:
            if x['pool']!=pool:continue
            a,b,z=x['before'],x['after'],x['removed']
            lines.append(f"{x['rule']} | {a['complete60']} | {z['complete60']} | {b['complete60']} | {a['touch10']:.2%}→{b['touch10']:.2%} | {a['fall30']:.2%}→{b['fall30']:.2%} | {b['mean_max_up60']:.2%}/{b['mean_max_down60']:.2%}")
    lines+=['','龙头低于MA20至少10%、剔除后逐年','年份 | 完整数 | +10%触及率 | 跌超30%率']
    for x in years:
        if x['pool']=='龙头子样本' and x['rule']=='低于MA20至少10%':lines.append(f"{x['year']} | {x['complete60']} | {x['touch10']:.2%} | {x['fall30']:.2%}")
    lines+=['','使用的历史规则参考：',
      'https://big5.sse.com.cn/site/cht/www.sse.com.cn/lawandrules/sselawsrules/repeal/rules/c/c_20230418_5720136.shtml',
      'https://www.szse.cn/www/investor/knowledge/stock/deal/t20210127_584469.html',
      'https://investor.szse.cn/knowledge/stock/deal/t20180801_553961.html']
    (OUT/'研究说明.txt').write_text('\n'.join(lines),encoding='utf8')
    print('\n'.join(lines));print('Verification passed')


if __name__=='__main__':main()
