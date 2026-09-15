# 沪深主板数据管线

## 执行顺序

```text
m1_prepare_and_audit.py
  → m2_build_pools.py
  → m3_label_statistics.py
  → m4_train_models.py
  → m4_validate_stop_model.py
  → m5_backtest_baselines.py
```

轻量阶段结论归档在 `../../archive/migration_studies/mainboard_baselines_20260912/execution_20260914/`；本地 `outputs/`、模型和派生面板可重新生成，不进入 Git。

## 数据目录

```text
data/
├── raw/SH、raw/SZ       # 不复权行情：成交与资金结算
├── qfq/SH、qfq/SZ       # 前复权行情：信号与特征
├── metadata/            # 历史证券清单
└── indices/             # 基准指数行情
```

下载范围从 2018-01-01 开始，结束日由 `config.json` 配置并自动回退到最近交易日。下载器保存完成标记，重复运行会跳过完整文件并继续失败任务。

## 运行入口

- 图形控制台：项目根目录执行 `tools/启动沪深主板下载控制台.cmd`。
- 直接续传：双击本目录的 `继续下载沪深主板.cmd`。
- 本地面板：`dashboard_server.py`，只监听 `127.0.0.1:8765`。

原始行情和前复权行情是长期本地资产，不在整理时删除；`derived/`、`models/`、`outputs/`、运行状态与日志属于可再生成或阶段性文件。
