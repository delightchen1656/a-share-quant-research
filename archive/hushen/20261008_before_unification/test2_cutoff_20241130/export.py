from pathlib import Path
import json,hashlib
HERE=Path(__file__).resolve().parent
def main():
    source=HERE.parent/'supermind_test2_D11_fast_daily.py'
    text=source.read_text(encoding='utf-8')
    w=json.loads((HERE/'selected_weights.json').read_text())['weights']
    text=text.replace("VERSION = '2026-10-03-D11-fast-v5'", "VERSION = '2026-10-04-D11-fast-cutoff20241130'\nTRAINING_CUTOFF_EXCLUSIVE = '2024-11-30'\nCAP_WEIGHT = %r\nVOL_WEIGHT = %r\nOVERNIGHT_WEIGHT = %r\nINTRADAY_WEIGHT = %r"%tuple(w))
    old="score = (-.35 * ranked['cap'] - .20 * ranked['vol'] +\n             .25 * ranked['overnight'] - .20 * ranked['intraday'])"
    new="score = (-CAP_WEIGHT * ranked['cap'] - VOL_WEIGHT * ranked['vol'] +\n             OVERNIGHT_WEIGHT * ranked['overnight'] - INTRADAY_WEIGHT * ranked['intraday'])"
    assert old in text;text=text.replace(old,new)
    text=text.replace('# -*- coding: utf-8 -*-', '''# -*- coding: utf-8 -*-
# D11提速截止版：每日频率，初始资金100000元。
# 本轮拟合和验证只使用2024-11-30之前的观测及标签，权重在运行中不再训练。
# 推断仍使用每个交易日之前已知行情；不能把训练截止理解为冻结未来交易特征。
# 保留调仓日全市场排名、非调仓日持仓/目标处理的提速逻辑。
# 原版平台收益不属于此版本；尚无新版平台回测。
# 继承的D11框架曾接触后续历史，本轮截断不消除既有选优影响。''',1)
    compile(text,'D11_cutoff_export','exec')
    target=HERE.parent/'supermind_test2_D11_fast_cutoff_20241130.py'
    target.write_text(text,encoding='utf-8')
    (HERE/'export_manifest.json').write_text(json.dumps(dict(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        export_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),weights=w,entrypoint=target.name),indent=2),encoding='utf-8')
    print(target)
if __name__=='__main__':main()
