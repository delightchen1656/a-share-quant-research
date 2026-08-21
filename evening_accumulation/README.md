# 晚间主力建仓形态策略

免费数据源：BaoStock。研究区间固定为 2015-01-01 至 2026-07-31。股票池只保留在 2026-07-31 当日仍上市的股票，目标日前已退市股票不下载。

本项目不能直接观察“主力”，而是学习低波动横盘、量价配合、换手与突破前状态等代理特征。未来上涨 30% 只用于训练标签，任何实盘特征均不读取未来数据。

## 一键运行

```powershell
cd C:\Users\22241\Desktop\quant\evening_accumulation
..\quant_env\Scripts\python.exe run.py download
..\quant_env\Scripts\python.exe run.py train
..\quant_env\Scripts\python.exe run.py backtest
..\quant_env\Scripts\python.exe run.py evening
```

`download` 支持断点续传；重复运行会跳过已完整下载的股票。`evening` 更新到配置截止日、加载各板块模型并输出 `outputs/signals_YYYYMMDD.csv`，只产生模拟盘候选，不会真实下单。

查看后台全量下载进度：

```powershell
.\download_status.ps1
```

也可以直接双击项目根目录的 `继续下载.cmd`。它会安全核对旧进程，以新股票池中序号最大的已下载股票为 checkpoint，并从其前5只开始扫描。终端用 `EXISTS` 标记已有数据、`DOWNLOADED` 标记本次新增，并显示全市场序号、百分比、速度、预计剩余时间和失败数；按 `Ctrl+C` 可以再次暂停。

## 交易所与板块分类

运行 `classify_data.ps1` 后，当前有效股票池会按 `data/classified/{SH|SZ}/{main|star|chinext}/{raw|qfq}` 分类。分类文件是原始 Parquet 的 NTFS 硬链接，不复制数据内容、不额外占用一整份磁盘空间。清单和分类统计位于 `data/metadata/classified_manifest.csv` 与 `classified_summary.csv`。

价格用途：`raw` 不复权行情用于真实成交价格、止盈止损；`qfq` 前复权行情用于特征和收益标签。股票统一编码为 `600519.SH`、`000001.SZ`、`830799.BJ`。

默认排除 ST、上市不足 120 日、20 日平均成交额低于 5000 万元的股票。单票资金上限 10%，亏损 6% 止损，上涨 20% 卖一半，上涨 30% 清仓，最长持有 60 个交易日。回测信号在下一交易日开盘成交，并计入佣金和滑点。

首版交易范围为沪深 A 股（其中已包含主板、创业板、科创板）；按风控设计暂不交易北交所。代码仍保留 `.BJ` 分类能力，后续若启用北交所，应改用覆盖北交所的免费接口并单独训练，不能把其更宽的涨跌幅制度直接混入沪深模型。
