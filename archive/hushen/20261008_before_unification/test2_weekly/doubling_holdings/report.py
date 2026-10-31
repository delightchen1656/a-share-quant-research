from pathlib import Path
import json
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties

HERE = Path(__file__).resolve().parent
font = FontProperties(fname='C:/Windows/Fonts/msyh.ttc')
plt.rcParams['font.family'] = font.get_name()
plt.rcParams['axes.unicode_minus'] = False
names = {'fixed5':'原版固定5只', 'growth50':'每增5万元加1只', 'growth100':'每增10万元加1只', 'doubling':'资产每翻倍加1只'}
results = json.loads((HERE/'results.json').read_text(encoding='utf-8'))
previous = HERE.parent/'dynamic_holdings'
results += [r for r in json.loads((previous/'results.json').read_text(encoding='utf-8')) if r['scenario'] != 'fixed5']
curves = pd.concat([pd.read_parquet(HERE/'daily_equity.parquet'), pd.read_parquet(previous/'daily_equity.parquet').query("scenario != 'fixed5'")], ignore_index=True)
# Annualized arithmetic daily-return Sharpe, rf=0, 252 sessions/year.
# Include the first trading session return relative to the 100000 initial cash.
metrics = {}
for key, x in curves.groupby('scenario', sort=False):
    x = x.sort_values('date')
    assert not x.date.duplicated().any()
    nav = x.equity.reset_index(drop=True)
    lag = nav.shift(1)
    lag.iloc[0] = 100000.
    daily = nav / lag - 1.
    assert daily.notna().all() and len(daily) == len(nav)
    assert abs((1 + daily).prod() - nav.iloc[-1]/100000.) < 1e-9
    metrics[key] = dict(sharpe=float(daily.mean()/daily.std(ddof=1)*252**.5),
        annualized_volatility=float(daily.std(ddof=1)*252**.5),
        daily_mean=float(daily.mean()), observations=len(daily), risk_free_annual=0., annual_sessions=252)
for r in results:
    r.update(metrics[r['scenario']])
(HERE/'sharpe_metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
fig, axes = plt.subplots(3, 1, figsize=(13, 10), sharex=True, gridspec_kw={'height_ratios':[2,1,1]})
for key, x in curves.groupby('scenario', sort=False):
    axes[0].plot(x.date, x.equity/10000, label=names[key], linewidth=1.3)
    peaks = x.equity.cummax().clip(lower=100000)
    axes[1].plot(x.date, (x.equity/peaks-1)*100, linewidth=1)
    axes[2].step(x.date, x.holdings_limit, where='post', linewidth=1)
axes[0].set_title('原版20交易日调仓：逐次翻倍扩容对照\n2020-01-02—2026-09-30，初始10万元')
axes[0].set_ylabel('账户总资产（万元）')
axes[0].legend()
axes[1].set_ylabel('回撤（%）')
axes[2].set_ylabel('目标持股上限（只）')
for ax in axes: ax.grid(alpha=.2)
fig.tight_layout()
fig.savefig(HERE/'comparison.png', dpi=150)
rows = []
for r in results:
    rows.append('<tr>'+''.join('<td>'+v+'</td>' for v in [names[r['scenario']], f"{r['final_equity']/10000:.2f}",
        f"{r['total_return']:.2%}", f"{r['cagr']:.2%}", f"{r['max_drawdown']:.2%}", f"{r['sharpe']:.3f}", str(r['trades']),
        f"{r['fees']+r['dividend_tax']:.2f}", str(r['final_limit']), str(r['final_holdings'])])+'</tr>')
html = '''<!doctype html><meta charset="utf-8"><title>D11资产增长扩容对照</title>
<style>body{font:16px 'Microsoft YaHei',sans-serif;max-width:1200px;margin:36px auto;line-height:1.7;color:#183047}table{border-collapse:collapse;width:100%}td,th{padding:9px;border:1px solid #ddd;text-align:right}img{width:100%}</style>
<h1>D11原版：资产增长扩容回测</h1>
<p>2020-01-02至2026-09-30，独立10万元空仓起步。新增逐次翻倍方案：10万元5只、20万元6只、40万元7只、80万元8只、160万元9只，最多15只。对照此前固定5只、每增5万元和每增10万元扩容方案。仅在原定20交易日调仓时，按前一交易日收盘总资产（现金、持仓与应收分红）定档；回落允许降档，无缓冲。98%目标仓位、原因子与排序、原保留排名缓冲及执行规则均保留，无训练或选参。</p>
<table><tr><th>方案</th><th>期末资产/万元</th><th>累计收益</th><th>年化收益</th><th>最大回撤</th><th>Sharpe</th><th>成交笔数</th><th>费用含分红税/元</th><th>期末目标上限</th><th>期末实际只数</th></tr>'''+''.join(rows)+'''</table>
<p>Sharpe口径：扣费每日简单收益均值÷样本标准差（ddof=1）×√252，无风险利率0%；首日收益相对初始10万元计算。不是用复合年化收益除以波动率，未对齐SuperMind默认无风险利率与算法。</p><img src="comparison.png"><p>停牌、跌停或未完成卖出可能使实际持股数量暂时超过新目标上限；不能为满足上限虚构卖出。每次目标组合正股数均不超过当期上限。</p>
<p>固定5只控制组重新运行，逐日净值与此前原版回放完全一致。完整明细保存在daily_equity.parquet、trades.parquet、schedules.parquet；验证见validation.json。</p>
<p>这是已知历史区间的规则比较，不是新训练或独立盲测。沿用本地日线开盘撮合近似、万三最低5元及历史印花税/过户费、T+1和整手限制、公司行动与分红税。每日高低价约束等执行近似不能替代SuperMind服务器或真实成交；不强制期末平仓，未扣未来平仓费用与未实现的分红税。历史股票池完整性与供应商数据仍有局限。不得用本区间表现自动晋升策略。</p>'''
(HERE/'report.html').write_text(html, encoding='utf-8')
print('REPORT', HERE/'report.html')
