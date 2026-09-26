# 沪深从零研究：round03_calendar_regime

状态：尚未通过完整目标门槛。

10万元；共同截止2026-09-11；250日年化，Sharpe=(复利年化-2%)/日收益年化波动；当前结果仅本地近似，不是平台实测。

|版本|信号|市值组|持股数|交易日间隔|开发年化中位数|开发Sharpe中位数|最差回撤|最低窗口平均仓位|
|---|---|---|---:|---:|---:|---:|---:|---:|
|C19|liquidity|regime|8|biweekly|21.87%|1.242|20.10%|70.61%|
|C17|liquidity|regime|8|biweekly|18.95%|1.049|19.77%|82.11%|
|C23|liquidity|regime|8|monthly|13.98%|0.758|19.04%|71.55%|
|C21|liquidity|regime|8|monthly|13.74%|0.711|18.94%|82.38%|
|C09|balanced|regime|8|monthly|14.15%|0.654|16.38%|80.72%|
|C11|balanced|regime|8|monthly|12.87%|0.648|17.40%|71.03%|
|C20|liquidity|regime|12|biweekly|9.51%|0.531|20.29%|68.87%|
|C22|liquidity|regime|12|monthly|9.64%|0.498|16.24%|80.24%|
|C24|liquidity|regime|12|monthly|8.09%|0.421|16.05%|70.09%|
|C10|balanced|regime|12|monthly|9.17%|0.416|19.55%|78.41%|
|C18|liquidity|regime|12|biweekly|7.58%|0.378|20.25%|79.78%|
|C33|small|regime|8|monthly|8.27%|0.333|17.39%|82.00%|
|C12|balanced|regime|12|monthly|6.97%|0.309|17.30%|69.28%|
|C35|small|regime|8|monthly|6.60%|0.273|19.57%|70.96%|
|C34|small|regime|12|monthly|6.80%|0.264|22.97%|78.87%|
|C36|small|regime|12|monthly|5.47%|0.204|22.31%|69.78%|
|C07|balanced|regime|8|biweekly|4.92%|0.182|19.41%|69.56%|
|C15|liquidity|regime|8|weekly|4.61%|0.174|23.13%|70.46%|
|C13|liquidity|regime|8|weekly|3.79%|0.117|20.91%|81.69%|
|C05|balanced|regime|8|biweekly|3.90%|0.110|24.95%|79.84%|
|C08|balanced|regime|12|biweekly|2.78%|0.055|20.68%|67.65%|
|C02|balanced|regime|12|weekly|2.40%|0.024|29.69%|75.93%|
|C06|balanced|regime|12|biweekly|2.33%|0.020|28.96%|76.92%|
|C03|balanced|regime|8|weekly|2.11%|0.007|31.06%|69.46%|
|C01|balanced|regime|8|weekly|1.64%|-0.020|35.77%|78.65%|
|C04|balanced|regime|12|weekly|0.99%|-0.068|24.81%|67.30%|
|C32|small|regime|12|biweekly|0.70%|-0.081|26.75%|67.92%|
|C31|small|regime|8|biweekly|0.38%|-0.088|22.69%|69.70%|
|C14|liquidity|regime|12|weekly|0.69%|-0.091|18.61%|79.30%|
|C29|small|regime|8|biweekly|-0.30%|-0.119|29.48%|80.90%|
|C16|liquidity|regime|12|weekly|0.30%|-0.123|21.00%|68.54%|
|C30|small|regime|12|biweekly|-1.38%|-0.189|33.34%|78.39%|
|C25|small|regime|8|weekly|-4.97%|-0.390|38.87%|80.21%|
|C26|small|regime|12|weekly|-5.87%|-0.454|34.48%|77.65%|
|C27|small|regime|8|weekly|-6.80%|-0.517|34.96%|69.08%|
|C28|small|regime|12|weekly|-7.38%|-0.600|31.59%|67.24%|

开发只用于筛选，开发窗口Sharpe>1不代表全期或不同起点达标。

|冻结候选|全期终值|年化|最大回撤|Sharpe|平均仓位|退市核销|未知大额公司行动|
|---|---:|---:|---:|---:|---:|---:|---:|
|C19|167060.54|8.22%|28.37%|0.352|77.59%|0|0|
|C17|167628.66|8.28%|28.61%|0.353|82.68%|0|0|

开发窗口数：864
滚动窗口内退市核销累计次数（重叠窗口重复计数）：0
含未知大额公司行动的开发窗口数：0
原始历史股票池3394只，包含199只后来退市股票；非ST/上市历史/流动性/波动资格按当时数据判断，不按最终存续状态排除。尚未解决的公司行动不可作为成功验收依据。
不同起点、成本压力和相邻参数的完整验收见PROTOCOL.md；未运行部分不能视为通过。历史反复使用，重叠窗口不是独立样本外。
