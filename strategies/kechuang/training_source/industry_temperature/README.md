# 科创2-2行业温度研究源码

本目录保存科创2-2“升温防守”仍需复现的最小研究链，不是第二套平台入口。

运行关系：

1. `backtest.py`装载科创行情并提供基础回测工具；
2. `temperature_variants.py`构造行业热度、宽度、量能、联动和龙头强度；
3. `frozen_research_code.py`保存最终科创2-2门控与回测逻辑；
4. `industry_map.csv`是静态行业映射，`download_industry_map.py`保存其生成方法。

`research_strategy3.py`位于上一级目录，提供季度走步熊市概率模型、下行相关性分散和真实成交模拟。十方向初筛、六方向优化和统一比较已经记录到 `../../history/baseline_2_2.md`，相应重复脚本不再保留。

本目录只保存源码和小型静态映射，不保存行情、缓存或回测输出。科创2-2正式平台入口仍是 `strategies/kechuang/supermind_baseline_2_2_rising_defense.py`。

注意：正式平台代码内嵌的季度熊市模型历史有效期截至2026-09-30。进入2026年第四季度后，必须先重训或核对，不能把旧内嵌参数当作已更新模型。
