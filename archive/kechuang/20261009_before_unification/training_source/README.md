# 科创模型训练源码

本目录保存当前科创1-2、科创2-2、科创3-1实际依赖的预测模型训练链。核心文件从 Git 提交 `ca523434` 恢复后按当前目录调整了数据路径。模型训练源码、特征构造和两份模型实物属于核心资产，后续常规清理不得删除。

## 保留内容

| 文件 | 用途 |
|---|---|
| `train_event_model.py` | 训练主上涨事件模型：未来20个交易日内最高价达到+30% |
| `train_stop_model_and_research.py` | 训练未来22个交易日先止损而非先止盈的风险模型 |
| `research_strategy3.py` | 训练科创2-2底层使用的季度走步熊市概率模型，并实现下行分散 |
| `src/model.py` | 18项历史价量特征、样本过滤和基础训练逻辑 |
| `src/data.py` | BaoStock下载和Parquet数据装载 |
| `model_artifacts/` | Git恢复的事件模型、止损模型、哈希和训练配置 |
| `industry_temperature/` | 科创2-2最终行业温度门控及其最小运行依赖 |

科创3-1没有第三套独立预测模型，它复用主上涨模型和止损模型，在执行层使用0.63阈值和30/60自然日延持规则。其20个参数方向和10个结构方向已经归纳到 `../history/baseline_3_1.md`，阶段筛选代码不再保留。

## 数据和运行

训练数据默认放在本目录 `data/raw/` 和 `data/qfq/`。若没有旧 `classified/` 目录，数据装载器会直接读取其中的 `688*.SH.parquet`。大型历史行情、缓存和批量结果不进入Git。

```powershell
cd C:\Users\22241\Desktop\quant\strategies\kechuang\training_source
python -m pip install -r requirements.txt
python train_event_model.py
python train_stop_model_and_research.py
```

重新训练会更新 `model_artifacts/` 中的本地模型，但不能自动替换正式SuperMind代码；必须先完成时间隔离、历史股票池、成交口径和平台一致性验证。历史模型由scikit-learn 1.9.0保存，严格复现应使用同版本。

各基准的研究尝试和冻结结论只维护在 `../history/`，不再以大量阶段代码保存。
