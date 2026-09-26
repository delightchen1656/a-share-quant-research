"""Revalue saved daily curves; no new selection, trading, or RF calibration."""
import json
import pandas as pd
from pathlib import Path
from supermind_performance import measure,screenshot_rf_bounds

HERE=Path(__file__).resolve().parent;OUT=HERE/'supermind_metrics_20260925'

def main():
    OUT.mkdir(exist_ok=True)
    paths=[('平台已导出净值（非新截图完整对应）',HERE/'monthly_A_alignment_20260924/platform_nav.json'),
        ('原月初A 本地修正',HERE/'monthly_A_structure_20260925/B00_curve.json'),
        ('严格6只',HERE/'monthly_A_structure_20260925/S01_curve.json'),
        ('等权S02',HERE/'monthly_A_structure_20260925/S02_curve.json'),
        ('周防守R069',HERE/'monthly_A_100_rounds_existing_history/R069_full_curve.json')]
    rows=[];rf0,rf1=screenshot_rf_bounds()
    for label,path in paths:
        curve=pd.read_json(path);curve['date']=pd.to_datetime(curve.date)
        m=measure(curve)
        m.update(name=label,source=str(path),start=str(curve.date.min().date()),end=str(curve.date.max().date()),
            sharpe_rf2pct_sensitivity=measure(curve,risk_free_annual=.02)['sharpe'],
            sharpe_screenshot_rf_sensitivity_low=measure(curve,risk_free_annual=rf1)['sharpe'],
            sharpe_screenshot_rf_sensitivity_high=measure(curve,risk_free_annual=rf0)['sharpe'])
        rows.append(m)
    payload=dict(source='https://quant.10jqka.com.cn/view/help/12',trading_year=250,volatility_ddof=0,
        risk_free_status='Not provided by platform export; official text says contemporary ten-year Treasury yield mean, exact value/averaging not resolved.',
        screenshot_implied_rf_bounds=[rf0,rf1],screenshot_bounds_note='Only algebraic sensitivity bounds assuming display rounding, not observed risk-free rates. Screenshot total return121.06% differs from exported124.44016%, so not the same verified run.',rows=rows)
    (OUT/'metrics.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# SuperMind统计公式重算','','只改统计计算，不改变净值、选股和成交。正式Sharpe因平台实际无风险利率缺失而留空；2%列仅为敏感性示例，不是已复现的平台值。','',
        '|版本|截止日|交易日数|累计收益|平台公式年化|最大回撤|年化波动|Sharpe（假设Rf=2%，非确认值）|','|---|---|---:|---:|---:|---:|---:|---:|']
    for z in rows:lines.append('|%s|%s|%d|%.2f%%|%.2f%%|%.2f%%|%.2f%%|%.3f|'%(z['name'],z['end'],z['trading_days'],z['total_return']*100,z['annualized']*100,-z['drawdown']*100,z['volatility']*100,z['sharpe_rf2pct_sensitivity']))
    lines+=['','规则：年化=(期末/初始)^(250/交易日数)-1；波动=每日收益总体标准差×√250；Sharpe=(上述年化-Rf)/波动；回撤按每日总资产历史高点计算，包含初始资金。',
        '每行按净值覆盖的交易日计数，包含首日相对初始资金的收益。缺失净值日期不能视作非交易日，源数据应完整；平台输出的首日/估值记录边界仍需同一次运行验证。',
        '截图12.91%、Sharpe0.61、波动0.18按显示精度只能约束Rf在1.5275%—2.3275%，不能确定恰好2%。',
        '平台导出累计收益124.44%，新截图121.06%；不能混用它们反推精确参数。',
        '原100组及十方向旧报告保留作为历史记录，其旧Sharpe不再标作平台口径；本页尚未重算所有滚动窗口，也没有按新口径重新选优。',
        '官方来源：https://quant.10jqka.com.cn/view/help/12']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(rows,ensure_ascii=True,indent=2))

if __name__=='__main__':main()
