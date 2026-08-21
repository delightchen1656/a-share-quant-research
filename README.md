# A股个人量化研究项目

这是一个面向个人研究的 A 股中低频量化项目，主要覆盖中证 100 多因子研究、机器学习排序，以及晚间主力建仓形态策略。研究与策略实现以 Python 为主，数据获取、平台回测和模拟交易使用同花顺 SuperMind；本地行情研究项目同时支持 BaoStock。

> 本项目仅用于量化研究与技术验证，不构成投资建议。历史回测不代表未来表现。

## 目录结构

```text
quant/
├── notebooks/                    # CSI100 研究与数据导出 Notebook
├── data/                         # 本地研究数据，不上传 GitHub
├── evening_accumulation/         # 晚间主力建仓策略完整项目
│   ├── src/                      # 数据、特征、模型和回测核心代码
│   ├── supermind/                # SuperMind 单文件策略与部署材料
│   ├── data/                     # 本地行情数据，不上传 GitHub
│   ├── outputs/                  # 回测和训练产物，不上传 GitHub
│   ├── config.json               # 策略参数
│   └── README.md                 # 子项目详细说明
├── main.py                       # 基础环境检查入口
├── requirements.txt              # 根目录研究环境依赖
├── 继续下载.cmd                  # 行情断点续传入口
└── quant_env/                    # 本地虚拟环境，不上传 GitHub
```

根目录中原有的 `backtest/`、`factors/`、`models/`、`strategies/` 是早期空脚手架，不参与当前项目运行，也不会被 Git 收录。

## 研究内容

### CSI100 多因子与机器学习

`notebooks/` 保存中证 100 研究流程，包含：

- 历史成分股与行情数据获取
- 动量、波动率、估值、质量、股息和流动性因子
- 风险调整动量、价值质量、低波质量、长期反转等规则策略
- LightGBM 和排序模型的滚动训练与样本外检验
- 交易成本、换手率、最大回撤和基准对比
- 2026 年独立测试区间

Notebook 说明见 [`notebooks/README.md`](notebooks/README.md)。

### 晚间主力建仓策略

`evening_accumulation/` 是独立可运行子项目，包含数据下载、特征构造、模型训练、事件识别、年度回测和 SuperMind 部署代码。详细命令、参数和交易约束见 [`evening_accumulation/README.md`](evening_accumulation/README.md)。

## 快速开始

### 1. 创建本地环境

```powershell
cd C:\Users\22241\Desktop\quant
python -m venv quant_env
.\quant_env\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

晚间建仓子项目还需要安装自己的依赖：

```powershell
pip install -r .\evening_accumulation\requirements.txt
```

### 2. 验证环境

```powershell
python .\main.py
```

正常输出：

```text
Quant project started
```

### 3. 运行 CSI100 研究

```powershell
jupyter notebook .\notebooks
```

SuperMind Notebook 使用平台内置的数据 API，本地环境不能直接调用这些接口。需要本地复现时，应先在 SuperMind 导出合规数据，再把读取部分替换为本地 Parquet 或 CSV。

### 4. 运行晚间建仓项目

```powershell
cd .\evening_accumulation
python run.py download
python run.py train
python run.py backtest
python run.py evening
```

若下载中断，可在项目根目录双击 `继续下载.cmd`。

## 数据与版本控制

股票历史行情、虚拟环境、训练模型、回测输出和缓存均由 `.gitignore` 排除，不会推送到 GitHub。克隆仓库后需要自行重新下载或导入数据。

提交前可检查：

```powershell
git status --short
git check-ignore -v data evening_accumulation/data evening_accumulation/outputs quant_env
```

## 当前状态

- 已完成 CSI100 多因子和多个机器学习策略的研究性比较
- 已完成交易成本、换手率与独立测试区间分析
- 已形成可在 SuperMind 回测的策略版本
- 晚间建仓项目具备本地下载、训练、回测和平台部署流程

后续重点应放在避免未来函数、维护历史成分股、控制交易成本、滚动样本外检验和模拟交易稳定性，而不是继续对单一区间反复调参。

