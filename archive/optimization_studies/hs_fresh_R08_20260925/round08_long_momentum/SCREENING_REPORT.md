# 沪深从零研究：round08_long_momentum

状态：尚未通过完整目标门槛。

10万元；共同截止2026-09-11；250日年化，Sharpe=(复利年化-2%)/日收益年化波动；当前结果仅本地近似，不是平台实测。

|版本|信号|市值组|持股数|交易日间隔|开发年化中位数|开发Sharpe中位数|最差回撤|最低窗口平均仓位|
|---|---|---|---:|---:|---:|---:|---:|---:|
|H30|carry_long|mid|12|monthly|14.44%|0.776|17.26%|79.06%|
|H32|carry_long|mid|12|bimonthly|15.05%|0.765|21.44%|78.52%|
|H29|carry_long|mid|8|monthly|13.06%|0.656|18.25%|80.81%|
|H27|carry_long|small|8|bimonthly|13.17%|0.541|20.87%|80.92%|
|H28|carry_long|small|12|bimonthly|13.08%|0.539|24.95%|78.96%|
|H34|carry_long|large|12|monthly|8.51%|0.509|13.05%|74.81%|
|H31|carry_long|mid|8|bimonthly|9.24%|0.446|21.74%|80.90%|
|H25|carry_long|small|8|monthly|9.57%|0.368|24.12%|81.05%|
|H33|carry_long|large|8|monthly|6.47%|0.324|14.81%|75.84%|
|H15|market_adjusted|small|8|bimonthly|8.34%|0.322|29.02%|78.89%|
|H36|carry_long|large|12|bimonthly|5.32%|0.257|13.91%|73.26%|
|H08|long_risk|mid|12|bimonthly|5.02%|0.184|25.76%|71.67%|
|H26|carry_long|small|12|monthly|5.25%|0.168|26.10%|78.56%|
|H19|market_adjusted|mid|8|bimonthly|4.01%|0.131|23.23%|75.58%|
|H14|market_adjusted|small|12|monthly|4.07%|0.114|29.80%|75.56%|
|H03|long_risk|small|8|bimonthly|4.08%|0.104|25.15%|79.17%|
|H16|market_adjusted|small|12|bimonthly|3.75%|0.097|28.31%|75.90%|
|H20|market_adjusted|mid|12|bimonthly|3.34%|0.093|20.06%|71.58%|
|H21|market_adjusted|large|8|monthly|2.87%|0.070|18.39%|58.41%|
|H35|carry_long|large|8|bimonthly|2.70%|0.049|18.70%|76.04%|
|H13|market_adjusted|small|8|monthly|2.27%|0.015|32.91%|79.43%|
|H11|long_risk|large|8|bimonthly|1.21%|-0.053|27.51%|60.49%|
|H02|long_risk|small|12|monthly|0.95%|-0.057|34.56%|75.87%|
|H22|market_adjusted|large|12|monthly|1.26%|-0.063|14.82%|47.37%|
|H17|market_adjusted|mid|8|monthly|0.88%|-0.070|24.11%|76.39%|
|H24|market_adjusted|large|12|bimonthly|0.84%|-0.104|15.95%|42.28%|
|H18|market_adjusted|mid|12|monthly|0.49%|-0.105|22.80%|72.04%|
|H04|long_risk|small|12|bimonthly|-0.38%|-0.131|26.15%|76.08%|
|H23|market_adjusted|large|8|bimonthly|-1.09%|-0.200|26.92%|56.86%|
|H06|long_risk|mid|12|monthly|-1.71%|-0.232|28.16%|72.08%|
|H01|long_risk|small|8|monthly|-2.70%|-0.248|35.85%|78.20%|
|H07|long_risk|mid|8|bimonthly|-3.84%|-0.339|36.59%|75.45%|
|H05|long_risk|mid|8|monthly|-4.04%|-0.349|30.70%|76.30%|
|H12|long_risk|large|12|bimonthly|-3.71%|-0.466|29.40%|44.04%|
|H10|long_risk|large|12|monthly|-7.04%|-0.745|31.91%|48.76%|
|H09|long_risk|large|8|monthly|-12.87%|-0.985|43.07%|60.22%|

开发只用于筛选，开发窗口Sharpe>1不代表全期或不同起点达标。

|冻结候选|全期终值|年化|最大回撤|Sharpe|平均仓位|退市核销|未知大额公司行动|
|---|---:|---:|---:|---:|---:|---:|---:|

开发窗口数：864
滚动窗口内退市核销累计次数（重叠窗口重复计数）：0
含未知大额公司行动的开发窗口数：2
原始历史股票池3394只，包含199只后来退市股票；非ST/上市历史/流动性/波动资格按当时数据判断，不按最终存续状态排除。尚未解决的公司行动不可作为成功验收依据。
不同起点、成本压力和相邻参数的完整验收见PROTOCOL.md；未运行部分不能视为通过。历史反复使用，重叠窗口不是独立样本外。
