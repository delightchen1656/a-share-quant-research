# 当前策略

本目录维护三条并列策略：**科创基准1**、**沪深1**与**沪深2**。

| 当前名称 | SuperMind入口 | 本地回测 | 研究与结果 |
|---|---|---|---|
| 科创基准1 | `kechuang/supermind_kechuang_1.py` | `kechuang/backtest/run.py` | `kechuang/research/`、`kechuang/results/` |
| 沪深1 | `hushen/supermind_hushen_1.py` | `hushen/backtest/run.py` | `hushen/research/`、`hushen/results/` |
| 沪深2 | 尚未制作SuperMind入口 | `hushen_2/backtest/compute_risk_metrics.py` | `hushen_2/results/` |

沪深1与科创1使用 `research / backtest / results` 分层；沪深2使用 `runtime / backtest / results`，登记前研究统一放在 `archive/hushen_2/`。当前回测所需的小型模型、冻结行情快照、基准日历和公司行动数据属于复现依赖，不是普通缓存。

2026-10-09之前的科创策略树位于 `archive/kechuang/20261009_before_unification/`；2026-10-08之前的沪深策略树位于 `archive/hushen/20261008_before_unification/`。旧名称、候选和研究版本仅用于溯源，不增加当前入口数量。
