"""Paired legacy dynamic sizing: skip versus cash-limited entry; no tuning."""
from pathlib import Path
import sys, json, html, importlib.util
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('paired_ablation', HERE.parent / 'ablation/run.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
p, s, ref = a.p, a.s, a.ref
OUT = HERE / 'results'

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s.OUT = OUT
    p.OUT = OUT
    source = HERE.parent / 'c_cash_resize/uploaded_legacy_source.py'
    ns = p.namespace(source.read_text(encoding='utf-8-sig'))
    keys = ['_EMBEDDED_MODEL_B64', '_EMBEDDED_STOP_MODEL_B64']
    models = [p.fast(json.loads(p.zlib.decompress(p.base64.b64decode(ns[k])))) for k in keys]
    snapshot = ref.BASE / 'snapshots' / a.END
    manifest = json.loads((snapshot / 'manifest.json').read_text())
    assert all(p.sha(snapshot / f) == v['sha256'] for f, v in manifest.items())
    print('SNAPSHOT VERIFIED; computing frozen signals', flush=True)
    ds, panels, meta = p.dataset(snapshot, '2020-01-01', a.END)
    ds = ds[ds.symbol.isin(models[0]['universe'])].copy()
    ds['p'] = ns['_batch_probabilities'](models[0], ds[p.F].to_numpy())
    ds['stop'] = ns['_batch_probabilities'](models[1], ds[p.F].to_numpy())
    ds['score'] = ds.p - .22 * ds.stop
    cand = s.candidates(ds, .63, .50)
    cache = json.loads((a.STAR / 'baseline_3_1_start_dates_500k_20261008/results/corporate_actions.json').read_text(encoding='utf-8'))
    p.save(OUT / 'corporate_actions.json', cache)
    actions = s.prepare_actions(panels, {x for v in cand.values() for x in v}, '2020-01-01', a.END)
    starts = [f'{y}-{m}-01' for y in range(2020, 2027) for m in ['01', '07']]
    p.save(HERE / 'protocol.json', dict(starts=starts, end=a.END, capital=500000,
        source_sha256=p.sha(source), retrained=False, tuned=False,
        comparison='A insufficient full target cash skips; C cash-limited entry >=200 shares',
        unchanged='legacy dynamic 10%-20%, models, thresholds, exit branches, buy-before-sell',
        limitations=['local daily opening proxy, not platform replay', 'successful fills/callbacks assumed',
        'common legacy cost approximation: .2% each-side slippage, .03% commission minimum5, .1% sell stamp,20% dividend tax',
        'shared overlapping history, not independent tests', 'C local all entries integer-sized; platform C fully-funded entries use percent orders']))
    rows = []
    for start in starts:
        a.START = start
        for cfg in [a.CONFIGS[0], a.CONFIGS[2]]:
            result = a.executor(panels, meta, actions, cfg)(cand)
            metrics, curve, tx, diffs = result
            assert curve.cash.min() >= -.01
            assert tx.loc[tx.side == 'BUY', 'qty'].ge(200).all()
            s.save_run(start + '_' + cfg[0][0], result)
            row = dict(metrics, start=start, variant=cfg[0][0], fees=float(tx.fee.sum()))
            rows.append(row)
            p.save(OUT / 'summary.json', rows)
            print(json.dumps(row, ensure_ascii=True), flush=True)
    headers = ['入场日','处理方式','最终资产（万）','累计收益','年化收益','最大回撤','Sharpe','平均仓位','成交笔数','交易费用（元）']
    table = []
    for r in rows:
        table.append([r['start'], '不足整笔跳过' if r['variant']=='A' else '不足缩量',
            f"{r['final_asset']/10000:.2f}", f"{r['total_return']:.2%}", f"{r['cagr']:.2%}",
            f"{abs(r['max_drawdown']):.2%}", f"{r['sharpe_rf0']:.2f}",
            f"{r['avg_exposure']:.2%}", str(r['fills']), f"{r['fees']:,.2f}"])
    body = '<tr>' + ''.join('<th>'+v+'</th>' for v in headers) + '</tr>'
    body += ''.join('<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in row)+'</tr>' for row in table)
    (HERE / 'report.html').write_text('<!doctype html><meta charset="utf-8"><title>现金不足处理对比</title><style>body{font:15px Microsoft YaHei;margin:30px}td,th{padding:9px;border-bottom:1px solid #ddd}table{border-collapse:collapse}tr:nth-child(4n+2),tr:nth-child(4n+3){background:#eef5fa}</style><h1>动态旧版：现金不足跳过 vs 缩量</h1><p>每组50万元独立空仓；2020起每半年至2026-09-30，28个本地日线近似回测。未重训、未调参、保留旧退出分支。非平台或实盘成绩。</p><table>'+body+'</table><p>费用为佣金与卖出印花税合计，滑点计入成交价；分红税另计。旧引擎税费近似未改，未声称券商精确口径。C与平台百分比下单有股数取整差异。重叠区间不是独立样本。</p>', encoding='utf-8')
    p.save(OUT / 'verification.json', dict(runs=len(rows), passed=True, snapshot_hashes=True, cash_nonnegative=True, buy_minimum200=True, platform_tested=False))

if __name__ == '__main__':
    main()
