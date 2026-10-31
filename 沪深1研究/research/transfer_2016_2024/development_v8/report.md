# 沪深1 V8 冻结多袖套研发结果

- 搜索空间哈希：`ed95a27102e39bdcc5d0a074e9f54a23c9660ed96432c5803e58ed9703e78973`
- 实现哈希：`dfa302fe71ddd23dc73d26640974770069d08da89c86ae705edcba1cfb49ce53`
- 数据边界：2013—2015预热，2016—2024研发评价；仅使用`inputs_pre2025/`。

结论：没有候选通过全部冻结门槛，保留精确基线。

## 候选判定

| 模型 | 通过 | 失败门槛 | 执行完整性 |
|---|---:|---|---|
| baseline | 否 | nine_year_median_excess_positive, both_segment_excess_above_baseline, at_least_seven_years_majority_start_improvement, all_leave_one_year_out_improvement_positive, single_year_positive_contribution_below_half, execution_integrity | fail |
| factor_sleeves_k2 | 否 | nine_year_median_excess_positive, both_segment_excess_above_baseline, both_segment_cagr_decline_within_2pp, at_least_seven_years_majority_start_improvement, all_leave_one_year_out_improvement_positive, single_year_positive_contribution_below_half, execution_integrity, same_structure_k2_k3_dual_segment_support | fail |
| factor_sleeves_k3 | 否 | nine_year_median_excess_positive, both_segment_excess_above_baseline, both_segment_cagr_decline_within_2pp, at_least_seven_years_majority_start_improvement, all_leave_one_year_out_improvement_positive, single_year_positive_contribution_below_half, execution_integrity, same_structure_k2_k3_dual_segment_support | fail |
| vintage_sleeves_k2 | 否 | nine_year_median_excess_positive, both_segment_excess_above_baseline, both_segment_cagr_decline_within_2pp, at_least_seven_years_majority_start_improvement, all_leave_one_year_out_improvement_positive, single_year_positive_contribution_below_half, execution_integrity, same_structure_k2_k3_dual_segment_support | fail |
| vintage_sleeves_k3 | 否 | nine_year_median_excess_positive, both_segment_excess_above_baseline, both_segment_cagr_decline_within_2pp, at_least_seven_years_majority_start_improvement, all_leave_one_year_out_improvement_positive, single_year_positive_contribution_below_half, execution_integrity, same_structure_k2_k3_dual_segment_support | fail |
| mixed_sleeves_k2 | 否 | nine_year_median_excess_positive, both_segment_excess_above_baseline, both_segment_cagr_decline_within_2pp, at_least_seven_years_majority_start_improvement, all_leave_one_year_out_improvement_positive, single_year_positive_contribution_below_half, execution_integrity, both_component_families_supported | fail |

## 逐年中位年化超额

| 模型 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | -0.22% | -12.19% | -10.93% | 2.30% | 17.20% | 56.88% | 63.80% | 18.86% | 52.05% |
| factor_sleeves_k2 | 8.20% | -36.49% | -6.85% | -9.82% | -28.72% | 11.33% | 10.06% | -4.07% | -21.09% |
| factor_sleeves_k3 | 1.70% | -36.60% | -0.39% | -17.77% | -23.86% | 1.02% | 3.28% | 3.92% | -17.24% |
| vintage_sleeves_k2 | 18.89% | -37.81% | -7.27% | -8.80% | -2.90% | 27.65% | 38.15% | 14.12% | 34.19% |
| vintage_sleeves_k3 | 27.23% | -32.13% | -3.57% | -1.24% | 3.53% | 28.95% | 35.17% | 11.16% | 43.04% |
| mixed_sleeves_k2 | -6.45% | -35.38% | -13.19% | -4.21% | -2.61% | 3.68% | 36.46% | 7.06% | 12.08% |

## 分段

| 模型 | 分段 | 平均超额 | 基线平均超额 | 超额改善 | 年化相对基线 |
|---|---|---:|---:|---:|---:|
| baseline | 2016-2019 | -4.71% | -4.71% | 0.00% | 0.00% |
| baseline | 2020-2024 | 40.95% | 40.95% | 0.00% | 0.00% |
| factor_sleeves_k2 | 2016-2019 | -11.24% | -4.71% | -6.54% | -6.54% |
| factor_sleeves_k2 | 2020-2024 | -6.34% | 40.95% | -47.29% | -47.29% |
| factor_sleeves_k3 | 2016-2019 | -13.22% | -4.71% | -8.51% | -8.51% |
| factor_sleeves_k3 | 2020-2024 | -5.73% | 40.95% | -46.68% | -46.68% |
| vintage_sleeves_k2 | 2016-2019 | -9.02% | -4.71% | -4.31% | -4.31% |
| vintage_sleeves_k2 | 2020-2024 | 21.53% | 40.95% | -19.42% | -19.42% |
| vintage_sleeves_k3 | 2016-2019 | -2.60% | -4.71% | 2.10% | 2.10% |
| vintage_sleeves_k3 | 2020-2024 | 22.79% | 40.95% | -18.16% | -18.16% |
| mixed_sleeves_k2 | 2016-2019 | -14.75% | -4.71% | -10.04% | -10.04% |
| mixed_sleeves_k2 | 2020-2024 | 11.73% | 40.95% | -29.22% | -29.22% |

## 压力测试

| 场景 | 模型 | 起点数 | 平均年化 | 平均超额 | 平均回撤 | 平均费用 | 容量拒单 |
|---|---|---:|---:|---:|---:|---:|---:|
| capacity_40pct | baseline | 526 | 22.20% | 20.34% | 20.50% | 1696.93 | 0 |
| capacity_40pct | vintage_sleeves_k3 | 526 | 13.21% | 11.35% | 20.70% | 1648.27 | 0 |
| double_commission | baseline | 526 | 21.60% | 19.74% | 20.62% | 2284.85 | 0 |
| double_commission | vintage_sleeves_k3 | 526 | 12.39% | 10.53% | 20.88% | 2405.11 | 0 |
