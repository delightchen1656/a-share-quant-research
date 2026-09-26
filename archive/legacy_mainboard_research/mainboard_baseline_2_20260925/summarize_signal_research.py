"""Verify and summarize completed signal studies; never reselect candidates."""
import json
from pathlib import Path
import pandas as pd
from supermind_performance import measure
HERE=Path(__file__).resolve().parent

def main():
    studies=[];count=0
    for name in ('monthly_A_signal_blend_20260925','monthly_A_signal_refine_20260925'):
        root=HERE/name
        s=json.loads((root/'summary.json').read_text(encoding='utf-8'))
        rows=json.loads((root/'windows.json').read_text(encoding='utf-8'))
        assert len(rows)==s['windows']
        assert len({(r['id'],r['split'],r['start']) for r in rows})==len(rows)
        assert all(r['risk_free_annual']==.02 and r['unresolved_actions']==0 for r in rows)
        assert abs(s['full']['BASE']['final_equity']-245749.27)<1e-7
        for cid,stat in s['full'].items():
            curve=pd.read_json(root/(cid+'_curve.json'))
            curve.date=pd.to_datetime(curve.date)
            actual=measure(curve,risk_free_annual=.02)
            for key in ('annualized','drawdown','sharpe','final_equity'):assert abs(actual[key]-stat[key])<1e-7
            assert not curve.date.duplicated().any()
            assert curve.cash.min()>=-.01
            assert abs(float((curve.stock_value/curve.equity).clip(0,1).mean())-stat['mean_exposure'])<1e-8
        count+=len(rows);studies.append((root,s,rows))
    root,s,rows=studies[-1]
    lines=['# 保持持仓：选股信号两轮研究','','本轮18个初筛组合+12个开发阶段细调组合，共30个候选。完成%d次滚动窗口及%d次全期模拟（含重复对照）。'%(count,sum(len(t[1]['full']) for t in studies)),
        '目标仓位固定80%，月度调仓、6只股票、原交易费用及现金/整手/成交限制；没有空仓择时或净值暂停。所有候选均如实记录实际仓位，低仓位不合格者不入选。','',
        '## 全期结果','','初始10万元，2020-01-02至2026-09-11，平台公式近似（250交易日年化、无风险利率暂固定2%），不是SuperMind实测。','',
        '|版本|期末资金|年化|最大回撤|Sharpe|实际平均仓位|低于50%仓位天数|','|---|---:|---:|---:|---:|---:|---:|']
    for cid,z in s['full'].items():
        if cid=='STRICT':continue
        lines.append('|%s|%.2f|%.2f%%|%.2f%%|%.3f|%.2f%%|%d|'%(cid,z['final_equity'],100*z['annualized'],-100*z['drawdown'],z['sharpe'],100*z['mean_exposure'],z['low_exposure_days']))
    lines+=['','BASE原月初A；L04全时段混入12%的252日至21日前动量排名；L12仅弱市混入同样动量，强市保持原规则。动量占比是排名信号权重，不是股票仓位。','',
        '## 滚动验证','','|版本|阶段|年化中位数|Sharpe中位数|最差窗口回撤|最低窗口平均仓位|','|---|---|---:|---:|---:|---:|']
    for cid in s['full']:
        if cid=='STRICT':continue
        for split,z in dict(dev=s['development'][cid],**s['validation'][cid]).items():
            lines.append('|%s|%s|%.2f%%|%.3f|%.2f%%|%.2f%%|'%(cid,split,100*z['median'],z['sharpe'],-100*z['drawdown'],100*z['worst_mean_exposure']))
    lines+=['','dev为24个2020/21起点，bridge为8个2022/23起点，audit为24个2024起点；每个窗口24个月。stress为audit起点下佣金、最低佣金、滑点翻倍，税率不变。窗口重叠且已见历史，不能视为独立样本外。','',
        '## 配对窗口比较','','下面按相同起点配对，计数是窗口数量，不代表独立胜率。','',
        '|候选|阶段|Sharpe优于BASE窗口|年化优于BASE窗口|窗口数|','|---|---|---:|---:|---:|']
    for c in s['winners']:
        for split in ('dev','bridge','audit','stress'):
            base={r['start']:r for r in rows if r['id']=='BASE' and r['split']==split}
            batch=[r for r in rows if r['id']==c['id'] and r['split']==split]
            lines.append('|%s|%s|%d|%d|%d|'%(c['id'],split,sum(r['sharpe']>base[r['start']]['sharpe'] for r in batch),sum(r['annualized']>base[r['start']]['annualized'] for r in batch),len(batch)))
    lines+=['','## 升级检查','']
    for cid,z in s['goals'].items():lines.append('- %s：%s'%(cid,json.dumps(z,ensure_ascii=False)))
    lines+=['','首轮N04开发Sharpe中位数1.228，但P10年化7.31%和最差回撤21.91%未通过门槛，未对它执行后段验证或以它宣称升级。第二轮仅依据开发结果缩小权重、区分强弱市；筛选后冻结L04/L12，再验证，不根据后段表现改选参数。',
        '邻近参数差异仍明显：全时段动量权重9%开发Sharpe0.889、12%为1.050、15%为1.228，但15%的回撤/P10不合格。不能认为继续提高动量权重一定改善策略。',
        '数据边界：原缓存复权数据和早期历史覆盖限制仍在；日线成交代理及部分公司行动日期近似未消除。无风险利率2%只是近似平台口径；原SuperMind策略未覆盖。',
        'QA：逐窗口唯一性、固定Rf、未解决公司行动、原版终值、全期指标重算、现金非负、实际仓位复核通过。信号计算的前缀不变性、跳过最近21个价格观察值、原缺失因子处理等单元测试通过。']
    path=HERE/'保持持仓_选股信号研究汇总.md';path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(windows=count,full=s['full'],goals=s['goals'],report=str(path)),ensure_ascii=False))

if __name__=='__main__':main()
