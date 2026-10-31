# 沪深1 V7 在线冻结因子权重研究

结论：没有候选通过；按协议保留精确基线。

- 白名单边界：2013—2024；评价为 2016—2024 每年第一季度全部交易日起点，共 526 个。
- 候选：504/756 交易日 IC 窗口 × 0.25/0.50 混合；未搜索协议外参数。
- 标签：随后 20 个交易日 close/preclose 经济收益，只有完成日不晚于当前信号日的截面可进入在线权重。
- 执行：前一完整日信号、下一开盘、整手、T+1、停牌、涨跌停、成交量、历史费率与公司行动。
- 压力：双倍佣金与 40% 容量；全部候选及基线均已运行。

## 门槛结果

| 候选 | 通过 | 最差年度中位超额 | 较弱分段超额改善 | 改善年度 | 改善起点占比 | 失败原因 |
|---|---:|---:|---:|---:|---:|---|
| online_w504_m025 | 否 | -4.64% | -6.12% | 4 | 37.64% | all_nine_annual_median_excess_positive;both_segments_excess_above_baseline;both_segments_cagr_drop_within_2pp;at_least_seven_years_median_excess_improved;more_than_half_starts_improved;all_leave_one_year_out_improvements_positive;sibling_improves_both_segments;execution_integrity_clean |
| online_w504_m050 | 否 | -13.95% | -19.05% | 1 | 14.83% | all_nine_annual_median_excess_positive;both_segments_excess_above_baseline;both_segments_cagr_drop_within_2pp;at_least_seven_years_median_excess_improved;more_than_half_starts_improved;all_leave_one_year_out_improvements_positive;single_year_positive_contribution_below_50pct;sibling_improves_both_segments;execution_integrity_clean |
| online_w756_m025 | 否 | -14.03% | -4.69% | 2 | 23.95% | all_nine_annual_median_excess_positive;both_segments_excess_above_baseline;both_segments_cagr_drop_within_2pp;at_least_seven_years_median_excess_improved;more_than_half_starts_improved;annual_median_excess_std_not_above_baseline;all_leave_one_year_out_improvements_positive;single_year_positive_contribution_below_50pct;sibling_improves_both_segments;execution_integrity_clean |
| online_w756_m050 | 否 | -6.28% | -15.69% | 2 | 23.00% | all_nine_annual_median_excess_positive;both_segments_excess_above_baseline;both_segments_cagr_drop_within_2pp;at_least_seven_years_median_excess_improved;more_than_half_starts_improved;all_leave_one_year_out_improvements_positive;single_year_positive_contribution_below_50pct;sibling_improves_both_segments;execution_integrity_clean |

## 分段结果（正常费用）

| 模型 | 分段 | 平均年化 | 平均年化超额 | 相对基线超额改善 | 相对基线年化变化 |
|---|---|---:|---:|---:|---:|
| baseline | 2016-2019 | -5.47% | -4.20% | 0.00% | 0.00% |
| baseline | 2020-2024 | 45.35% | 40.96% | 0.00% | 0.00% |
| online_w504_m025 | 2016-2019 | -3.05% | -1.78% | 2.43% | 2.43% |
| online_w504_m025 | 2020-2024 | 39.23% | 34.84% | -6.12% | -6.12% |
| online_w504_m050 | 2016-2019 | -4.12% | -2.85% | 1.36% | 1.36% |
| online_w504_m050 | 2020-2024 | 26.31% | 21.92% | -19.05% | -19.05% |
| online_w756_m025 | 2016-2019 | -7.19% | -5.92% | -1.72% | -1.72% |
| online_w756_m025 | 2020-2024 | 40.66% | 36.27% | -4.69% | -4.69% |
| online_w756_m050 | 2016-2019 | -4.15% | -2.88% | 1.33% | 1.33% |
| online_w756_m050 | 2020-2024 | 29.66% | 25.27% | -15.69% | -15.69% |

## 压力汇总

| 模型 | 场景 | 平均年化 | 中位超额 | 最低年化 | 平均回撤 | 平均成本 | 完整性问题 |
|---|---|---:|---:|---:|---:|---:|---:|
| baseline | capacity_40pct | 22.43% | 11.78% | -45.89% | 20.50% | 1696.98 | 982 |
| baseline | double_commission | 21.83% | 11.34% | -46.26% | 20.62% | 2284.98 | 982 |
| baseline | normal | 22.65% | 11.95% | -45.88% | 20.50% | 1663.77 | 982 |
| online_w504_m025 | capacity_40pct | 20.06% | 5.82% | -37.71% | 20.40% | 1674.49 | 890 |
| online_w504_m025 | double_commission | 19.59% | 5.41% | -37.95% | 20.47% | 2258.80 | 890 |
| online_w504_m025 | normal | 20.34% | 6.12% | -37.30% | 20.33% | 1641.57 | 890 |
| online_w504_m050 | capacity_40pct | 12.52% | 3.65% | -45.72% | 21.29% | 1667.98 | 881 |
| online_w504_m050 | double_commission | 11.99% | 3.33% | -46.28% | 21.37% | 2248.14 | 881 |
| online_w504_m050 | normal | 12.71% | 4.06% | -45.71% | 21.22% | 1635.63 | 881 |
| online_w756_m025 | capacity_40pct | 18.99% | 3.29% | -39.42% | 21.01% | 1682.90 | 890 |
| online_w756_m025 | double_commission | 18.51% | 2.72% | -39.62% | 21.07% | 2271.86 | 890 |
| online_w756_m025 | normal | 19.28% | 3.52% | -39.07% | 20.93% | 1651.15 | 890 |
| online_w756_m050 | capacity_40pct | 14.42% | 2.39% | -33.92% | 20.34% | 1669.68 | 990 |
| online_w756_m050 | double_commission | 13.80% | 1.55% | -34.57% | 20.45% | 2247.07 | 989 |
| online_w756_m050 | normal | 14.56% | 2.39% | -34.09% | 20.33% | 1637.23 | 991 |

## 审计

- 代码哈希：`a73bd440147ae6d8e0b6a7f6999073783d058588b14fbfcd6f776b4b2ab22df5`
- 搜索空间哈希：`f8b1734f600387f9a30624c905aeb995487b5a5e93d9ced6e78e802cfcc28925`
- 排名集合哈希：`d73f37dd3182a033798f7f3e1da5cd82d880b16d39cbb35d8511836cde2061ea`
- 逐起点、逐年度、分段、门槛、压力和失败原因见同目录 CSV。
