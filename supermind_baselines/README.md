# 六个基准的SuperMind平台代码

平台统一设置：股票策略、每日频率、基准指数科创50 `000688.SH`。建议先以100万元复核历史区间，再进入模拟交易。

| 基准 | SuperMind策略名称 | 上传文件 | SHA256 |
|---|---|---|---|
| 基准1-1 | 科创暴涨前建仓 | `supermind_baseline_1_1_accumulation_rally.py` | `075F2AAB6CF49EC81ACAD814BA9251077E869055EE9A5CE87E3FE90BBE410EBB` |
| 基准1-2 | 科创止损概率过滤 | `supermind_baseline_1_2_stop_filter.py` | `F91A181C20B491D1EA5BFB7F5DE888DAF38830789B3A62EF9078DE53C6E1DA6B` |
| 基准1-3 | 科创熊市分散 | `supermind_baseline_1_3_bear_diversification.py` | `CFFC8F5CC27A8D712538507DE4DDB7D7F502FFE1E0649652B598B4FDB37E0BBF` |
| 基准2-1 | 科创行业温度进攻 | `supermind_baseline_2_1_temperature_attack.py` | `6AA45FE1193469A34181BC3D43A82DA779F16D57C979921065E8F8B5A55B84DC` |
| 基准2-2 | 科创行业升温防守 | `supermind_baseline_2_2_rising_defense.py` | `209BB158534063465B38992F68356F79824B3ADD98CC5A0580A049FAD307B7D4` |
| 基准3-1 | 高进攻强势延持 | `supermind_baseline_3_1_high_attack_adaptive_expiry.py` | `8B2B9BEDC87AF7663695EC2A539254CCBB6B6CFBB487EE24BBF2403356F13770` |

## 差异

- 基准1-1：原始异常拉升识别与交易规则。
- 基准1-2：增加先止损概率过滤和风险调整排序，不含熊市缩仓。
- 基准1-3：在基准1-2上增加季度熊市概率软缩仓和下行相关性分散。
- 基准2-1：在基准1-3上增加偏进攻的行业温度门控。
- 基准2-2：在基准1-3上增加偏防守的行业升温门控。
- 基准3-1：承接基准1-2，阈值0.63；30自然日到期时浮盈达到10%则延长至最多60自然日。

六份文件均通过Python语法检查，以及 `import os`、`open()`、`getattr()` 等SuperMind禁用调用扫描。基准1-3、2-1、2-2内嵌的季度熊市模型有效至2026-09-30，进入2026年第四季度前必须更新。
