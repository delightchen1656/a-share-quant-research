"""Archive verified evidence and explicitly flag incomplete independent parity."""
import ast,hashlib,json,re,shutil
import pandas as pd
from align_platform_exports import HERE,OUT,metrics

s=json.loads((OUT/'summary.json').read_text(encoding='utf-8'))
eq=pd.read_csv(OUT/'platform_daily_equity.csv',parse_dates=['date'])
local=pd.read_csv(HERE/'pending_1_snapshot/defensive_bear_8_equity.csv',parse_dates=['date'])
lm=metrics(local,'2020-01-02','2026-09-11',100000)
platform=s['stages']['common_full']
lines=['# 沪深基准2：平台对账归档（独立本地复现未完成）','',
 '来源是2026-09-22提供的同一次SuperMind运行的三份文件，不是三个不同平台：detal.csv、dailyposition.csv、outlog.txt。策略日志标识“沪深基准2 顺势防守8”，初始10万元。平台到2026-09-18，本地冻结结果到2026-09-11。原文件保留，归档复制并附SHA256校验。', '',
 '## 共同区间比较','', '|口径|截至日期|期末资产元|年化|最大回撤|Sharpe|','|---|---|---:|---:|---:|---:|']
for label,z in [('平台导出',platform),('本地冻结策略',lm)]:lines.append(f"|{label}|{z['end']}|{z['final']:.2f}|{z['annualized']:.2%}|{abs(z['max_drawdown']):.2%}|{z['sharpe']:.3f}|")
lines+=['','本表统一计算：阶段起点包含期初资产、252日年化波动、无风险收益0。因此Sharpe与旧报告未纳入首日收益的算法可能略有差别。没有用9月18日平台结果对比9月11日本地结果。', '',
 '## 对账完成的部分','',
 f"平台{ s['platform_rows']}笔成交，本地{s['local_rows']}笔。同日期、同股票、同买卖方向匹配{s['matched_date_symbol_side']}笔（{s['platform_match_rate']:.2%}）；数量也匹配{s['matched_quantity']}笔（{s['quantity_match_rate']:.2%}）。不能称为成交对齐。", '',
 'CSV每日总资产与日志完全一致；总资产=现金+持仓市值，误差小于0.01元。平台卖出金额原文件为负，已在标准化明细转换为金额绝对值，再按买卖方向计算现金流。成交价仅显示3位，实际金额按金额/股数还原，不用显示成交价反算现金。', '',
 f"平台持仓与本地日行情共同覆盖的{s['price_rows']}条收盘价记录全部一致。平台353笔佣金合计2409.70元、印花税3559.40元；导出成交的卖出税率实测约0.1%，不是使用当前法规反向更改历史导出。", '',
 f"另识别{s['unattributed_cash_events']}个大于3分钱的非交易现金变动日，合计{s['unattributed_cash_total']:.2f}元，以及{s['share_change_events']}个非交易股数变动。这些单列为待归因事件，不能未经验证全部叫分红。原始精度导致的微小残差也保留。", '',
 '## 已定位但尚未解决的原因','',
 '1. 选股输入不同：首日平台1351只合格候选，本地1341只。把发布的SuperMind因子函数直接用于本地原始行情，六个因子与本地缓存最大差异均为0，但仍不能得到平台首日选股。因此“相同本地因子下27次评分一致”只验证计算逻辑，并未验证平台实际数据输入一致。', '',
 '2. 成交基价不同：以平台金额/股数还原实际价格，再除去本地假设的单边0.2%滑点，600377首日基价约11.27，本地日开盘11.30；603608约9.63，本地日开盘9.30。日志时间09:31，证明日开盘代理不吻合，现有文件无法确定平台内部分钟撮合或其他定价公式。', '',
 '3. 本地公司行动算法忽略2%以内价格调整，且用近似送转比例；平台存在未由交易解释的现金和股数变动。不能强行把这些残差当作未来策略可预知的收益。', '',
 '## 本地回放的定义','',
 'platform_daily_equity.csv 内 replay_cash/replay_equity 使用平台已实现成交、观察到的非交易现金变动与平台持仓市值重建账户，仅用于账务核对。由于用了观察到的账户残差，余额一致是会计重建结果，不是独立策略回测成功。没有用平台选股日志、成交或每日余额替换本地策略信号。', '',
 '## 平台三个阶段','', '|阶段|起止|年化|最大回撤|Sharpe|期末资产元|','|---|---|---:|---:|---:|---:|']
for tag,label in [('dev','2020—2023'),('2024','2024'),('2025plus','2025以后')]:
 z=s['stages'][tag];lines.append(f"|{label}|{z['start']}至{z['end']}|{z['annualized']:.2%}|{abs(z['max_drawdown']):.2%}|{z['sharpe']:.3f}|{z['final']:.2f}|")
lines+=['','## 继续独立对齐所缺的数据','',
 '需要平台首个强市及弱市调仓日的逐股因子输入、历史行情口径，以及实际撮合基价/分钟行情与分红送转明细。已提供只增加日志、不改变交易规则的诊断版，可用同样设置重新运行并导出日志。', '',
 '归档状态：账务核对完成、差异定位完成、独立策略复现未完成。基准2待定1冻结结果和原引擎未覆盖，不把平台24.43%年化冒充成本地新回测结果。']
(OUT/'对齐与归档说明.md').write_text('\n'.join(lines),encoding='utf-8')
log=(OUT/'originals/outlog.txt').read_text(encoding='utf-8-sig')
dates=[]
for regime in ['STRONG','WEAK']:
 hit=re.search(r'(\d{4}-\d{2}-\d{2}) 09:00:00INFOBASELINE2 regime='+regime,log)
 if hit:dates.append(hit.group(1))
src=(HERE/'supermind_mainboard_baseline_2_pending1.py').read_text(encoding='utf-8')
marker='    if not strong and frame.float_cap_proxy.notna().mean() < .95:'
assert marker in src
extra='''    if str(get_datetime().date()) in %s:
        for record in frame.to_dict("records"):
            log.info("HSB2_FACTOR " + str(get_datetime().date()) + " " + json.dumps(record, ensure_ascii=False))
        log.info("HSB2_BENCH " + str(get_datetime().date()) + " " + json.dumps(bc.tolist()))
''' % repr(tuple(dates))
src=src.replace(marker,extra+marker);ast.parse(src)
(OUT/'supermind_baseline2_alignment_diagnostic.py').write_text(src,encoding='utf-8')
for name in ['align_platform_exports.py','check_platform_factor_inputs.py','finalize_platform_alignment_archive.py']:
 shutil.copy2(HERE/name,OUT/name)
manifest={str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.rglob('*') if p.is_file() and p.name!='sha256.json'}
(OUT/'sha256.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print('LOCAL_UNIFIED',lm);print('ARCHIVED',OUT);print('DIAGNOSTIC_DATES',dates)
