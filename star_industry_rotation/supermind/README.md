# 基准2-1—2-2 SuperMind文件

- `supermind_strategy4_temperature_attack_single.py`：基准2-1温度进攻（文件名保留旧技术编号）。
- `supermind_strategy5_rising_defense_single.py`：基准2-2升温防守（文件名保留旧技术编号）。
- `build_temperature_supermind.py`：从冻结基准1-3单文件生成基准2-1、2-2。
- `test_temperature_supermind.py`：语法、映射、真实行情温度与门控边界测试。
- `test_result.json`：机器可读测试结果。

两个基准都是自包含单文件，平台无需额外模型或行业映射附件。推荐先使用每日频率、100万元、2020-01-01至2026-07-31回测。
