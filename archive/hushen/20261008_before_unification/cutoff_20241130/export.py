from pathlib import Path
import json, hashlib

HERE=Path(__file__).resolve().parent
def main():
    source=HERE.parent/'supermind_mainboard_baseline_1.py'
    original=source.read_text(encoding='utf-8')
    selected=json.loads((HERE/'selected_weights.json').read_text())
    wd,wm,wv=selected['weights']
    # Strip previous-version return claims; preserve execution logic.
    text=original[original.index('from mindgo_api import *'):]
    text='''# 沪深1：截止2024-11-30前数据的权重重估版。分钟频率，09:31执行，建议本金100000。
# 参数拟合及验证观测截止2024-11-29，未使用之后的行情或标签选参。
# R08框架曾用后续历史选优，因此不是完全独立的历史样本外实验。
# 训练结果是因子排名检验，不是组合年化收益；本版本尚未完成平台回测。
# 运行时可使用每个交易日之前的已知行情进行推断，权重不会在线重新训练。
''' + text
    text=text.replace('TARGET_COUNT = 12',f"TRAINING_CUTOFF_EXCLUSIVE = '2024-11-30'\nDISTRIBUTION_WEIGHT = {wd!r}\nMOMENTUM_WEIGHT = {wm!r}\nLOW_VOL_WEIGHT = {wv!r}\nTARGET_COUNT = 12",1)
    text=text.replace("c = pd.to_numeric(q.close, errors='coerce')", "# Reconstruct using only contemporaneous raw prices and ex-reference closes.\n    ratio = x.close / x.prev_close\n    c = ratio.where((ratio > 0) & np.isfinite(ratio)).cumprod()")
    text=text.replace('.4 * q.distribution_proxy.rank(pct=True)','DISTRIBUTION_WEIGHT * q.distribution_proxy.rank(pct=True)')
    text=text.replace('.3 * q.long_risk.rank(pct=True)','MOMENTUM_WEIGHT * q.long_risk.rank(pct=True)')
    text=text.replace('.3 * (1 - q.vol60.rank(pct=True))','LOW_VOL_WEIGHT * (1 - q.vol60.rank(pct=True))')
    line="        qdata = history(batch, ['close'], HISTORY_BARS, '1d', False, 'pre', True, False)\n"
    assert line in text;text=text.replace(line,'')
    text=text.replace("if not isinstance(qdata, dict) or not isinstance(rdata, dict):", "if not isinstance(rdata, dict):")
    text=text.replace("q, raw = past_bars(qdata.get(s), today), past_bars(rdata.get(s), today)","raw = past_bars(rdata.get(s), today)\n            q = raw  # history gate only; stock price chain is reconstructed in stock_features")
    text=text.replace("log.info('沪深基准1 R08 V1.0 MINUTE required;", "log.info('沪深1 cutoff20241130 weights=0.3/0.2/0.5 MINUTE required;")
    # Benchmark is an unadjusted index, with no future price adjustment basis.
    text=text.replace("['close'], HISTORY_BARS, '1d', False, 'pre', True, False)","['close'], HISTORY_BARS, '1d', False, None, True, False)",1)
    compile(text,'cutoff_export','exec')
    target=HERE.parent/'supermind_mainboard_baseline_1_cutoff_20241130.py'
    target.write_text(text,encoding='utf-8')
    manifest=dict(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),export_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),weights=selected['weights'],entrypoint=target.name,training_cutoff_exclusive='2024-11-30')
    (HERE/'export_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(target)
if __name__=='__main__':main()
