# 当前策略

本目录是项目唯一的当前策略入口，设五条正式主线：

- `kechuang/`：科创1-2、科创2-2、科创3-1；
- `hushen/`：沪深基准1（R08 高仓精选 V1.0）、沪深基准2（原D11固定5只、20交易日调仓，入口`supermind_mainboard_baseline_2.py`）。

目录中的顶层Python文件包含SuperMind正式入口和候选交付代码。2026-10-06用户明确晋升原D11为基准2；科创3-2、沪深截止日重估、严格重训及周调仓/扩容/调参分支仍是独立候选或验证版本。

当前研究史从 `kechuang/HISTORY.md` 进入各科创基准，从 `hushen/HISTORY.md` 进入沪深基准1与2（基准2独立说明为`hushen/baseline_2/README.md`）。预测模型训练源码统一保存在 `kechuang/training_source/`。已退出当前入口、但有版本或研究价值的代码统一位于根目录 `research_versions/`。
