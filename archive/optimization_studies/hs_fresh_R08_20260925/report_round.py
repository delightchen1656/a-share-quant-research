"""Read-only QA of saved simulations, then generate a research report."""
import json,sys
import pandas as pd
import research as r

def main(name):
    out=r.HERE/name;s=json.loads((out/'summary.json').read_text(encoding='utf-8'))
    rows=json.loads((out/'windows.json').read_text(encoding='utf-8'))
    assert len(rows)==s['windows']
    assert len({(x['id'],x['start'],x['split']) for x in rows})==len(rows)
    assert all(x['risk_free_annual']==.02 for x in rows)
    cfgs={c['id']:c for c in s['configs']}
    lines=['# 沪深从零研究：'+name,'','状态：尚未通过完整目标门槛。','',
        '10万元；共同截止2026-09-11；250日年化，Sharpe=(复利年化-2%)/日收益年化波动；当前结果仅本地近似，不是平台实测。','',
        '|版本|信号|市值组|持股数|交易日间隔|开发年化中位数|开发Sharpe中位数|最差回撤|最低窗口平均仓位|','|---|---|---|---:|---:|---:|---:|---:|---:|']
    for cid,z in sorted(s['development'].items(),key=lambda item:item[1]['sharpe_median'],reverse=True):
        c=cfgs[cid]
        lines.append('|%s|%s|%s|%d|%s|%.2f%%|%.3f|%.2f%%|%.2f%%|'%(cid,c.get('family',c.get('route')),c.get('size','regime'),c['count'],str(c.get('cadence',c.get('interval'))),100*z['annual_median'],z['sharpe_median'],-100*z['worst_dd'],100*z['min_exposure']))
    if any('risk_mode' in c for c in s['configs']):
        lines+=['','仓位规则：fixed85/95为固定仓位；trend60/65为前收盘高于前120日均线时95%，否则60%/65%；vol12/16为目标波动除以前60日CSI500波动，限制60%—95%。仅正常调仓日更新。','',
            '|版本|仓位规则|','|---|---|']
        lines += ['|%s|%s|'%(c['id'],c['risk_mode']) for c in s['configs']]
    if any('affordable' in c for c in s['configs']):
        lines+=['','整手可买性对照（候选池60，保留旧持仓缓冲仍为2倍持股数）：','',
            '|版本|预算可买性筛选|目标权重|','|---|---|---|']
        lines += ['|%s|%s|等权|'%(c['id'],'开启' if c.get('affordable') else '关闭') for c in s['configs']]
    if any('strength' in c for c in s['configs']):
        lines+=['','相关性选择配置（0为原始不分散对照，持仓权重均为等权目标）：','',
            '|版本|相关性惩罚强度|历史交易日数|候选/缓冲数|','|---|---:|---:|---:|']
        lines += ['|%s|%s|%s|%s|'%(c['id'],c.get('strength'),c.get('lookback'),c['buffer']) for c in s['configs']]
    lines+=['','开发只用于筛选，开发窗口Sharpe>1不代表全期或不同起点达标。','',
        '|冻结候选|全期终值|年化|最大回撤|Sharpe|平均仓位|退市核销|未知大额公司行动|','|---|---:|---:|---:|---:|---:|---:|---:|']
    for cid,z in s['full'].items():
        curve=pd.read_json(out/(cid+'_curve.json'));curve.date=pd.to_datetime(curve.date)
        check=r.measure(curve,risk_free_annual=.02)
        for key in ('annualized','drawdown','sharpe','final_equity'):assert abs(check[key]-z[key])<1e-7
        assert curve.cash.min()>=-.01
        lines.append('|%s|%.2f|%.2f%%|%.2f%%|%.3f|%.2f%%|%d|%d|'%(cid,z['final_equity'],100*z['annualized'],-100*z['drawdown'],z['sharpe'],100*z['mean_exposure'],z['delisting_writeoffs'],z['unresolved_actions']))
    lines+=['','开发窗口数：'+str(len(rows)),'滚动窗口内退市核销累计次数（重叠窗口重复计数）：'+str(sum(x['delisting_writeoffs'] for x in rows)),
        '含未知大额公司行动的开发窗口数：'+str(sum(x['unresolved_actions']>0 for x in rows)),
        '原始历史股票池3394只，包含199只后来退市股票；非ST/上市历史/流动性/波动资格按当时数据判断，不按最终存续状态排除。尚未解决的公司行动不可作为成功验收依据。',
        '不同起点、成本压力和相邻参数的完整验收见PROTOCOL.md；未运行部分不能视为通过。历史反复使用，重叠窗口不是独立样本外。']
    (out/'SCREENING_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(round=name,windows=len(rows),full=s['full'],full_necessary_pass=[cid for cid,z in s['full'].items() if z['sharpe']>1 and z['annualized']>.12 and z['mean_exposure']>.5]),ensure_ascii=False))

if __name__=='__main__':main(sys.argv[1])
