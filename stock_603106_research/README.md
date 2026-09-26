# 603106 恒银科技：2020年至今的模型研究

最新研究取消最低持仓限制，以验证期年化收益为目标，比较5,340组机器学习/技术策略及48组自适应轮换规则。静态搜索报告见 `return_exploration/REPORT.md`，轮换报告见 `return_exploration/adaptive/REPORT.md`。这些结果属于多轮探索，不能当作完全独立测试。

本轮结论和同期对比见 **`return_exploration/OVERVIEW.md`**。取消最低持仓限制后，上一版参考模型在2025年至今的交易和净值没有变化；本轮新增优胜方案没有在后期超过它。

```powershell
.\quant_env\Scripts\python.exe .\stock_603106_research\explore_returns.py
.\quant_env\Scripts\python.exe .\stock_603106_research\adaptive_explore.py
.\quant_env\Scripts\python.exe .\stock_603106_research\compare_results.py
.\quant_env\Scripts\python.exe -m unittest discover -s stock_603106_research -p 'test_*.py' -v
```

此前的 **10万元本金、至少持有一个自然月**中长线模型保留在 `medium_term/REPORT.md`。

```powershell
.\quant_env\Scripts\python.exe .\stock_603106_research\medium_term.py
.\quant_env\Scripts\python.exe -m unittest discover -s stock_603106_research -p test_backtest.py -v
```

中长线版本按2020—2022年初始训练、2023—2024年选参、2025年至今最终历史评估。72组候选只在验证期比较，选中参数先落盘再评估后期数据；此前短线实验已接触后期行情，这一点在报告中明确披露。各季度扩展训练时，只加入在当时已经完整实现的标签。

该文件夹不读取其他项目的历史行情缓存。仓库只保存源码、报告、参数汇总和图表；新下载行情、训练模型、逐日预测、候选明细及交易曲线均为可再生成工作文件，不进入版本库，并已在 2026-09-26 整理时删除。

## 运行

在项目根目录 `C:\Users\22241\Desktop\quant` 执行：

```powershell
.\quant_env\Scripts\python.exe .\stock_603106_research\download_data.py
.\quant_env\Scripts\python.exe .\stock_603106_research\backtest.py --verify
```

下载器默认19点之后请求当日，否则请求上一自然日，实际覆盖时间以数据末日为准。可用 `--end 2026-09-17` 固定请求结束日。每次下载都会重新请求接口，不增量复用行情；回测只读取本目录刚下载并校验过的快照。

依赖：Python、baostock、pandas、numpy、pyarrow、scikit-learn、matplotlib、joblib，沿用项目现有 Python 环境。

## 文件

- `REPORT.md`：结果及研究边界。
- `download_data.py`：网络下载入口。
- `backtest.py`：特征、滚动训练、成交模拟、验证及报告生成。
- `data/`、`models/`、`outputs/`：运行时重建的本地工作目录，不进入 Git。
- 各级 `REPORT.md`、`OVERVIEW.md`：保留的研究结论、指标和边界。
- `*.py`：下载、特征、回测、搜索和验证入口。

2020—2021年初始训练，2022年起历史样本外回测。参数不按回测收益挑选，结果不等于实盘可获收益。
