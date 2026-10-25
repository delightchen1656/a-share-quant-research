# 当前策略基线

`strategies/` 只维护三条基线，不再承载桌面软件、K线练习或一次性研究工具。

| 基线 | 当前入口 | 当前口径 | 研究记录 |
|---|---|---|---|
| 沪深1 | `hushen/supermind_hushen_1.py` | 5只、98%仓位、20交易日调仓 | `hushen/research/思路与历史.md` |
| 沪深2 | `hushen_2/CURRENT_SELECTION.json` | C04_NEW原前三后仅保留ATR≥2.5%，不递补、不重排 | `hushen_2/README.md` |
| 科创1 | `kechuang/supermind_kechuang_1.py` | 当前冻结科创基准1 | `kechuang/README.md` |

沪深2没有SuperMind入口，也没有自动实盘授权。其独立桌面工作台位于根目录 `沪深2_星轨软件/`；K线练习位于根目录 `沪深2_K线练习/`。两者可以读取仓库公共行情，但代码、模型和本地状态互不依赖，也不从 `archive/` 导入运行代码。

归档、旧研究和一次性脚本不是额外基线。公共行情、公司行动、更新审计和冻结白名单属于保护资产，不能按缓存清理。
