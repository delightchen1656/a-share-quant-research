# 当前策略

本目录只维护两条当前主线：**科创基准1**与**沪深1**。

| 当前名称 | SuperMind入口 | 本地回测 | 研究与结果 |
|---|---|---|---|
| 科创基准1 | `kechuang/supermind_kechuang_1.py` | `kechuang/backtest/run.py` | `kechuang/research/`、`kechuang/results/` |
| 沪深1 | `hushen/supermind_hushen_1.py` | `hushen/backtest/run.py` | `hushen/research/`、`hushen/results/` |

两边统一使用 `research / backtest / results` 分层。当前回测所需的小型模型、冻结行情快照、基准日历和公司行动数据属于复现依赖，不是普通缓存。

2026-10-09之前的科创策略树位于 `archive/kechuang/20261009_before_unification/`；2026-10-08之前的沪深策略树位于 `archive/hushen/20261008_before_unification/`。旧名称、候选和研究版本仅用于溯源，不增加当前入口数量。
