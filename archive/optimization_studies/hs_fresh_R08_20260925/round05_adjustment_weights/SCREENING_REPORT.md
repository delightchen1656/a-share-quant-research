# 沪深从零研究：round05_adjustment_weights

状态：尚未通过完整目标门槛。

10万元；共同截止2026-09-11；250日年化，Sharpe=(复利年化-2%)/日收益年化波动；当前结果仅本地近似，不是平台实测。

|版本|信号|市值组|持股数|交易日间隔|开发年化中位数|开发Sharpe中位数|最差回撤|最低窗口平均仓位|
|---|---|---|---:|---:|---:|---:|---:|---:|
|E34|carry_trend|mid|12|bimonthly|19.12%|0.963|15.63%|80.64%|
|E35|carry_trend|mid|12|bimonthly|17.95%|0.922|15.79%|80.81%|
|E17|carry_trend|mid|12|monthly|16.92%|0.919|13.61%|81.81%|
|E16|carry_trend|mid|12|monthly|16.57%|0.890|14.13%|80.11%|
|E36|carry_trend|mid|12|bimonthly|17.44%|0.884|15.75%|80.91%|
|E18|carry_trend|mid|12|monthly|15.93%|0.879|13.56%|80.92%|
|E25|carry_trend|mid|8|bimonthly|16.84%|0.759|21.55%|82.06%|
|E31|carry_trend|mid|12|bimonthly|14.77%|0.738|20.68%|80.31%|
|E26|carry_trend|mid|8|bimonthly|15.38%|0.705|22.06%|82.15%|
|E27|carry_trend|mid|8|bimonthly|14.47%|0.665|22.32%|81.52%|
|E32|carry_trend|mid|12|bimonthly|12.71%|0.649|20.83%|80.29%|
|E29|carry_trend|mid|8|bimonthly|13.31%|0.640|20.68%|82.39%|
|E28|carry_trend|mid|8|bimonthly|13.43%|0.640|19.75%|81.83%|
|E33|carry_trend|mid|12|bimonthly|12.22%|0.618|20.68%|80.21%|
|E14|carry_trend|mid|12|monthly|12.01%|0.614|16.49%|81.60%|
|E09|carry_trend|mid|8|monthly|12.93%|0.608|18.52%|82.16%|
|E15|carry_trend|mid|12|monthly|11.73%|0.604|16.10%|81.13%|
|E13|carry_trend|mid|12|monthly|11.66%|0.584|16.99%|80.74%|
|E30|carry_trend|mid|8|bimonthly|12.08%|0.580|21.32%|81.74%|
|E08|carry_trend|mid|8|monthly|12.24%|0.556|19.25%|82.38%|
|E07|carry_trend|mid|8|monthly|11.60%|0.521|20.27%|82.17%|
|E22|carry_trend|mid|6|bimonthly|5.10%|0.170|21.19%|82.56%|
|E10|carry_trend|mid|8|monthly|4.55%|0.163|19.39%|82.10%|
|E19|carry_trend|mid|6|bimonthly|4.76%|0.158|22.83%|83.04%|
|E23|carry_trend|mid|6|bimonthly|4.79%|0.156|21.20%|82.54%|
|E02|carry_trend|mid|6|monthly|4.61%|0.155|24.05%|83.06%|
|E03|carry_trend|mid|6|monthly|4.50%|0.154|23.26%|82.46%|
|E11|carry_trend|mid|8|monthly|4.22%|0.143|19.42%|82.55%|
|E12|carry_trend|mid|8|monthly|4.10%|0.137|19.57%|81.99%|
|E24|carry_trend|mid|6|bimonthly|4.39%|0.135|22.59%|82.19%|
|E20|carry_trend|mid|6|bimonthly|4.21%|0.131|22.98%|82.87%|
|E01|carry_trend|mid|6|monthly|3.99%|0.112|24.93%|83.22%|
|E21|carry_trend|mid|6|bimonthly|3.43%|0.083|23.16%|82.46%|
|E06|carry_trend|mid|6|monthly|2.61%|0.035|20.46%|82.49%|
|E05|carry_trend|mid|6|monthly|2.01%|0.000|20.85%|82.78%|
|E04|carry_trend|mid|6|monthly|1.28%|-0.041|21.82%|82.93%|

开发只用于筛选，开发窗口Sharpe>1不代表全期或不同起点达标。

|冻结候选|全期终值|年化|最大回撤|Sharpe|平均仓位|退市核销|未知大额公司行动|
|---|---:|---:|---:|---:|---:|---:|---:|
|E34|227978.52|13.53%|14.65%|0.698|82.01%|0|0|
|E35|223704.69|13.20%|14.60%|0.682|82.27%|0|0|
|E17|203366.48|11.55%|15.48%|0.600|82.50%|0|0|

开发窗口数：864
滚动窗口内退市核销累计次数（重叠窗口重复计数）：0
含未知大额公司行动的开发窗口数：0
原始历史股票池3394只，包含199只后来退市股票；非ST/上市历史/流动性/波动资格按当时数据判断，不按最终存续状态排除。尚未解决的公司行动不可作为成功验收依据。
不同起点、成本压力和相邻参数的完整验收见PROTOCOL.md；未运行部分不能视为通过。历史反复使用，重叠窗口不是独立样本外。
