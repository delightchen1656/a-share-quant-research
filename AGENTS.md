# 项目记忆

## 新增授权修订版（2026-10-03）

- 科创3-2：强势延持审计修正版，入口 `strategies/kechuang/supermind_baseline_3_2_audited_daily.py`；审查处置、构建、研究约束与回归测试位于 `strategies/kechuang/baseline_3_2/`。属于用户明确授权的新分支，待平台验证，尚无新收益数据。
- 科创3-1及其标准日频版保持冻结，不以3-2覆盖。3-2继承旧模型，不能声称已消除历史选优/幸存者偏差或已严格重训。

更新日期：2026-10-03。当前且仅有四条正式主线：**科创1-2、科创2-2、科创3-1、沪深1**。用户已撤回“沪深测试2”，沪深目前只有基准1。

## 当前入口

| 当前名称 | 策略含义 | SuperMind入口 |
|---|---|---|
| 科创1-2 | 止损概率过滤；风险调整排序 | `strategies/kechuang/supermind_baseline_1_2_stop_filter.py` |
| 科创2-2 | 行业升温防守；承接熊市缩仓与分散逻辑 | `strategies/kechuang/supermind_baseline_2_2_rising_defense.py` |
| 科创3-1 | 高进攻强势延持 | `strategies/kechuang/supermind_baseline_3_1_high_attack_adaptive_expiry.py` |
| 沪深1 | R08高仓精选V1.0 | `strategies/hushen/supermind_mainboard_baseline_1.py` |

科创3-1另有标准日频版 `strategies/kechuang/supermind_baseline_3_1_high_attack_adaptive_expiry_daily.py`。

## 必须保留的核心资产

- `strategies/kechuang/training_source/`：科创1-2、2-2、3-1仍在使用的模型训练、特征构造、科创2-2最终门控和模型实物；常规清理不得删除。
- `strategies/kechuang/history/`：三条正式科创基准及3-2候选各自的研究思路、尝试方向、冻结数据和边界。
- `strategies/hushen/HISTORY.md`：沪深1的研究思路、尝试方向、晋升数据和边界。R08是规则策略，没有独立机器学习预测模型，旧轮次研究引擎不再保留。
- 科创3-1已完成并冻结，不再作为循环优化任务；冻结不等于删除其来源代码。

## 历史记忆

- 科创研究从 `strategies/kechuang/HISTORY.md` 进入各基准独立历史文件。
- 沪深1研究维护在 `strategies/hushen/HISTORY.md`。
- 不再恢复与当前四基准无关的旧基准、独立候选或大型回测产物。正式策略仍依赖的预测模型训练源码属于核心；可由历史Markdown承接的阶段筛选代码不再保留。

## 避免混淆

- 科创3-1标准版与历史120k、dynamic20派生版不同；派生版已退出当前范围。
- 沪深1为分钟频率、调仓日09:31执行、10万元初始口径、最多12只、目标仓位95%。
- 科创2-2内嵌季度熊市模型有效期截至2026-09-30；第四季度使用前必须先核对更新。
- 2026-09-30科创三策略50万元比较的数据截止2026-09-29，只作为历史记忆，不能称为今天最新数据或用户实际持仓。
- `国金ptrade/` 位于根目录，作为未来独立研究线；未经用户明确要求，不并入当前四基准。
- 用户已暂停此前循环优化目标；读取仓库不代表恢复自动优化、消耗额度或实盘交易。
