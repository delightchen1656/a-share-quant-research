# 科创板当前三基准

新增独立审计修订版 **科创3-2：强势延持审计修正版**，入口 `supermind_baseline_3_2_audited_daily.py`。详见 [3-2说明](baseline_3_2/README.md)。原科创3-1保持冻结；3-2待平台验证，不继承3-1的收益成绩。

当前仅维护以下三条科创主线：

| 名称 | 含义 | SuperMind文件 |
|---|---|---|
| 科创1-2 | 止损概率过滤；风险调整排序 | `supermind_baseline_1_2_stop_filter.py` |
| 科创2-2 | 行业升温防守；承接熊市缩仓与分散逻辑 | `supermind_baseline_2_2_rising_defense.py` |
| 科创3-1 | 高进攻强势延持 | `supermind_baseline_3_1_high_attack_adaptive_expiry.py` |

科创3-1另保留标准日频版 `supermind_baseline_3_1_high_attack_adaptive_expiry_daily.py`。120k、dynamic20等派生版本不属于当前核心，已移至根目录 `research_versions/kechuang_high_attack/`。

三条科创基准仍在使用的模型训练源码保存在 [`training_source/`](training_source/README.md)：包括主上涨模型、先止损模型、季度熊市概率模型及科创2-2最终行业温度门控。该目录不得在常规归档清理中删除。科创3-1的20方向与10结构方向代码保存在根目录研究版本归档；批量结果和缓存不保留。科创3-1已完成并冻结。

平台通常使用股票策略、日频和科创50基准 `000688.SH`。具体资金口径以每次研究任务明确指定为准，不能把一次50万元比较永久写成所有策略的默认本金。

重要：科创2-2代码中的季度熊市模型历史有效期截止2026-09-30。当前日期已进入2026年第四季度，在核对或更新内嵌模型前，不应直接把它视为最新可运行版本。

每个基准的历史思路、尝试方向、冻结结果和边界从 `HISTORY.md` 进入。
