# Sharpe突破1：本轮汇总

## 结论：尚未达到，不替换正式基准

本轮共72个候选配置试验（包括重复控制与邻域复测，不宣称全部独立或全新配置）、2336个窗口回测；所有统计统一平台公开公式，Rf固定暂按2%。
基准全期Sharpe为0.756；进入后段验证的候选中，全期最好为D4的0.859，未突破1。D4后段Sharpe中位数虽为1.027，但最差窗口回撤25.11%，未通过风险要求。

|全期版本|年化|最大回撤|Sharpe|10万元终值|
|---|---:|---:|---:|---:|
|原月初A|14.85%|16.44%|0.756|245749.27|
|D4：10%回撤触发/20交易日冷静期|15.81%|16.15%|0.859|259418.42|

全期均为2020-01-02至2026-09-11；不是平台端实测。

|后段24个入场窗口|年化中位数|最差回撤|Sharpe中位数|
|---|---:|---:|---:|
|BASE|18.54%|14.15%|0.966|
|D4|18.95%|25.11%|1.027|

## 四条路线及结果

- 48组选股/仓位/分散度：未突破目标。强化低风险或扩大股票数往往同时损失收益。
- 6组分批调仓：真实拆分10万元、逐份扣最低佣金后，开发期收益损失过大，没有候选进入验证。
- 6组净值回撤冷静期：D4有改善，但全期不足1且后段尾部回撤偏大。
- 12组邻域追加：包含D4重复对照；没有找到更稳健的升级。12%线候选F10全期Sharpe仅0.514，说明参数附近仍敏感。

冷静期的10%触发线不是总最大回撤上限。反复退出和重进、跳空及不可成交约束，仍可能使累计回撤超过10%。

校验：窗口记录数和唯一键检查通过；所有行使用同一Rf；基准终值准确复现；未解释大额公司行动计数合计0。
限制：历史已多次使用、窗口重叠；早期历史和分钟成交仍近似。不能把选中某个窗口Sharpe>1当成整体实现目标，也不应继续改变统计公式或无风险利率凑数。

## 完整表格

- [monthly_A_sharpe_20260925](C:/Users/22241/Desktop/quant/sh_sz_market_research/baselines/mainboard_baseline_2/monthly_A_sharpe_20260925/REPORT.md)
- [monthly_A_phase_sharpe_20260925](C:/Users/22241/Desktop/quant/sh_sz_market_research/baselines/mainboard_baseline_2/monthly_A_phase_sharpe_20260925/REPORT.md)
- [monthly_A_guard_sharpe_20260925](C:/Users/22241/Desktop/quant/sh_sz_market_research/baselines/mainboard_baseline_2/monthly_A_guard_sharpe_20260925/REPORT.md)
- [monthly_A_guard_refinement_20260925](C:/Users/22241/Desktop/quant/sh_sz_market_research/baselines/mainboard_baseline_2/monthly_A_guard_refinement_20260925/REPORT.md)
