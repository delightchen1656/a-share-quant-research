# 两方向年化与Sharpe调参

10万元，每个开发/验证窗口24个月；月初及移位5/10交易日起点。先开发筛选，再冻结验证，不按后段重选。

| 参数版本 | 年化中位数 | P10 | 最差窗口回撤 | Sharpe |
|---|---:|---:|---:|---:|
|monthly_base|16.15%|10.60%|18.54%|1.034|
|monthly_count_5|12.21%|3.44%|20.03%|0.763|
|monthly_count_7|15.62%|12.19%|16.33%|1.031|
|monthly_power_0.5|17.25%|9.98%|18.51%|1.069|
|monthly_power_1.0|16.11%|10.20%|18.46%|0.987|
|monthly_exposure_0.7|14.61%|9.39%|16.45%|1.014|
|monthly_exposure_0.9|18.59%|11.60%|19.77%|1.010|
|weekly_guard_base|15.66%|9.49%|16.82%|1.010|
|weekly_guard_count_5|11.38%|2.82%|18.06%|0.799|
|weekly_guard_count_7|13.93%|10.69%|14.90%|1.046|
|weekly_guard_power_0.5|15.48%|8.97%|16.81%|1.018|
|weekly_guard_power_1.0|14.97%|9.17%|16.60%|0.986|
|weekly_guard_exposure_0.7|13.74%|8.80%|15.30%|1.034|
|weekly_guard_exposure_0.9|16.77%|10.13%|18.08%|0.979|
|weekly_guard_threshold_0.08|14.76%|8.46%|15.99%|1.081|
|weekly_guard_threshold_0.12|16.74%|9.90%|17.15%|1.123|

| 冻结方向 | 参数 | 全部条件通过 |
|---|---|---|
|固定月初|{"power": 0.5}|False|
|月初选股周度风控|{"threshold": 0.12}|False|

| 版本 | 验证 | 年化中位数 | P10 | 最差回撤 | Sharpe |
|---|---|---:|---:|---:|---:|
|monthly_base|audit|19.17%|15.00%|13.78%|1.126|
|monthly_base|stress_dev|12.74%|7.09%|19.41%|0.816|
|monthly_base|stress_audit|15.90%|11.77%|15.40%|0.960|
|monthly_power_0.5|audit|19.31%|14.82%|14.12%|1.133|
|monthly_power_0.5|stress_dev|13.50%|6.78%|19.36%|0.878|
|monthly_power_0.5|stress_audit|15.88%|11.82%|15.57%|0.953|
|weekly_guard_base|audit|12.21%|8.03%|14.29%|0.873|
|weekly_guard_base|stress_dev|12.35%|6.55%|17.49%|0.825|
|weekly_guard_base|stress_audit|8.36%|4.96%|16.67%|0.633|
|weekly_guard_threshold_0.12|audit|12.64%|8.86%|14.10%|0.851|
|weekly_guard_threshold_0.12|stress_dev|13.17%|6.73%|17.91%|0.890|
|weekly_guard_threshold_0.12|stress_audit|8.59%|5.50%|16.77%|0.609|

| 版本 | 全历史终值 | 年化 | 回撤 | Sharpe |
|---|---:|---:|---:|---:|
|monthly_base|254670.74|14.99%|16.45%|0.936|
|monthly_power_0.5|267102.60|15.82%|16.44%|0.978|
|weekly_guard_base|216663.73|12.25%|14.75%|0.865|
|weekly_guard_threshold_0.12|240000.20|13.98%|15.12%|0.931|

总回测数：676；旧结果回归检查：120
全历史为2020-01-02至2026-09-11描述性结果，不参与筛选；各24月窗口有重叠，后段历史已观察，不能声称独立样本外。平台成交差异、股票池与公司行动限制仍在。未替换正式策略。
