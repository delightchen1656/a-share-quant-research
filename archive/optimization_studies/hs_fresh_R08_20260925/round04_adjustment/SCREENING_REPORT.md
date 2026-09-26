# 沪深从零研究：round04_adjustment

状态：尚未通过完整目标门槛。

10万元；共同截止2026-09-11；250日年化，Sharpe=(复利年化-2%)/日收益年化波动；当前结果仅本地近似，不是平台实测。

|版本|信号|市值组|持股数|交易日间隔|开发年化中位数|开发Sharpe中位数|最差回撤|最低窗口平均仓位|
|---|---|---|---:|---:|---:|---:|---:|---:|
|D44|carry_trend|mid|12|bimonthly|17.95%|0.922|15.79%|80.81%|
|D42|carry_trend|mid|12|monthly|16.92%|0.919|13.61%|81.81%|
|D17|persistent|all|8|monthly|9.82%|0.760|11.86%|82.03%|
|D37|carry_trend|small|8|monthly|18.42%|0.753|17.62%|81.41%|
|D38|carry_trend|small|12|monthly|16.19%|0.723|16.24%|80.32%|
|D40|carry_trend|small|12|bimonthly|14.64%|0.647|16.78%|80.11%|
|D43|carry_trend|mid|8|bimonthly|13.31%|0.640|20.68%|82.39%|
|D29|persistent|large|8|monthly|7.74%|0.615|11.86%|81.98%|
|D12|carry|mid|12|bimonthly|9.87%|0.522|15.93%|80.51%|
|D19|persistent|all|8|bimonthly|7.60%|0.520|11.57%|81.92%|
|D31|persistent|large|8|bimonthly|7.33%|0.498|11.57%|81.98%|
|D10|carry|mid|12|monthly|9.57%|0.480|14.92%|80.71%|
|D07|carry|small|8|bimonthly|10.02%|0.444|22.47%|81.57%|
|D25|persistent|mid|8|monthly|8.89%|0.433|15.68%|82.59%|
|D24|persistent|small|12|bimonthly|10.12%|0.433|18.03%|80.19%|
|D22|persistent|small|12|monthly|9.88%|0.429|19.02%|80.54%|
|D21|persistent|small|8|monthly|9.77%|0.396|20.40%|81.92%|
|D18|persistent|all|12|monthly|5.88%|0.384|11.95%|80.01%|
|D30|persistent|large|12|monthly|5.66%|0.358|11.95%|79.46%|
|D20|persistent|all|12|bimonthly|5.71%|0.358|12.44%|79.02%|
|D45|carry_trend|large|8|monthly|5.11%|0.342|13.78%|82.04%|
|D48|carry_trend|large|12|bimonthly|5.44%|0.341|12.88%|79.95%|
|D23|persistent|small|8|bimonthly|9.04%|0.340|23.08%|81.48%|
|D26|persistent|mid|12|monthly|6.78%|0.324|14.86%|80.26%|
|D32|persistent|large|12|bimonthly|5.15%|0.315|12.44%|78.87%|
|D08|carry|small|12|bimonthly|7.01%|0.306|18.26%|79.99%|
|D39|carry_trend|small|8|bimonthly|8.55%|0.297|22.57%|81.06%|
|D06|carry|small|12|monthly|6.87%|0.296|16.93%|79.76%|
|D27|persistent|mid|8|bimonthly|6.19%|0.273|16.61%|82.12%|
|D28|persistent|mid|12|bimonthly|6.08%|0.272|15.53%|80.50%|
|D11|carry|mid|8|bimonthly|5.78%|0.267|17.27%|82.05%|
|D46|carry_trend|large|12|monthly|4.15%|0.226|13.04%|80.49%|
|D47|carry_trend|large|8|bimonthly|4.17%|0.225|13.78%|81.59%|
|D41|carry_trend|mid|8|monthly|4.22%|0.143|19.42%|82.55%|
|D02|carry|all|12|monthly|2.69%|0.079|12.25%|79.21%|
|D33|carry_trend|all|8|monthly|2.76%|0.077|13.82%|82.37%|
|D05|carry|small|8|monthly|2.68%|0.040|22.60%|81.51%|
|D03|carry|all|8|bimonthly|2.26%|0.029|11.45%|81.94%|
|D04|carry|all|12|bimonthly|2.12%|0.014|12.04%|78.94%|
|D15|carry|large|8|bimonthly|2.10%|0.010|11.44%|81.37%|
|D34|carry_trend|all|12|monthly|2.04%|0.004|13.09%|81.16%|
|D09|carry|mid|8|monthly|2.05%|0.004|20.22%|81.27%|
|D14|carry|large|12|monthly|1.56%|-0.049|12.47%|79.73%|
|D16|carry|large|12|bimonthly|1.38%|-0.069|12.44%|80.14%|
|D01|carry|all|8|monthly|1.05%|-0.095|13.69%|81.97%|
|D36|carry_trend|all|12|bimonthly|0.61%|-0.123|14.88%|79.95%|
|D13|carry|large|8|monthly|0.05%|-0.207|14.43%|81.85%|
|D35|carry_trend|all|8|bimonthly|-1.47%|-0.349|18.12%|81.66%|

开发只用于筛选，开发窗口Sharpe>1不代表全期或不同起点达标。

|冻结候选|全期终值|年化|最大回撤|Sharpe|平均仓位|退市核销|未知大额公司行动|
|---|---:|---:|---:|---:|---:|---:|---:|
|D44|223704.69|13.20%|14.60%|0.682|82.27%|0|0|
|D42|203366.48|11.55%|15.48%|0.600|82.50%|0|0|

开发窗口数：1152
滚动窗口内退市核销累计次数（重叠窗口重复计数）：0
含未知大额公司行动的开发窗口数：21
原始历史股票池3394只，包含199只后来退市股票；非ST/上市历史/流动性/波动资格按当时数据判断，不按最终存续状态排除。尚未解决的公司行动不可作为成功验收依据。
不同起点、成本压力和相邻参数的完整验收见PROTOCOL.md；未运行部分不能视为通过。历史反复使用，重叠窗口不是独立样本外。
