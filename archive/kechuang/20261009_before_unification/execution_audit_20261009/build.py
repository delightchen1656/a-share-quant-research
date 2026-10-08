from pathlib import Path
import ast,hashlib,json
HERE=Path(__file__).resolve().parent
BASE=HERE.parent
def main():
    source=BASE/'supermind_baseline_3_1_high_attack_adaptive_expiry_daily.py'
    raw=source.read_bytes();text=raw.decode('utf-8-sig')
    for name in ['init','before_trading','handle_bar']:text=text.replace('def '+name+'(', 'def _legacy_'+name+'(',1)
    text=text.replace('BASELINE1-2 candidates=', 'STAR3_1_FIXED500K candidates=')
    start=text.index('            if _available_cash(context) < price * 200 * 1.005:')
    end=text.index('        # Exactly one entry pass',start)
    text=text[:start]+'''            nav = float(context.portfolio.stock_account.total_value)
            quantity, reserve = _buy_size(nav, price, min(g.cash_budget, _available_cash(context)))
            if quantity < 200:
                log.info('BUY_SKIP_MIN_OR_CASH symbol=%s price=%.4f cash=%.2f' % (symbol,price,g.cash_budget))
                continue
            order_id = _safe_place(symbol, quantity, "BUY", probability, reserve)
            if order_id is not None:
                slots -= 1
'''+text[end:]
    # Avoid current-day feature leakage, without changing historical feature formula.
    text=text.replace('            values = _last_features(frame)', '''            if frame is not None and len(frame):
                frame = frame.copy()
                frame.index = pd.to_datetime(frame.index)
                frame = frame[frame.index.normalize() < pd.Timestamp(today)]
            values = _last_features(frame)''')
    # Make expiry available even when a >=24% winner cannot legally be halved.
    text=text.replace('                _submit(symbol, target, "TPHALF")\n        else:', '                _submit(symbol, target, "TPHALF")\n                continue\n        if symbol not in g.order_locks:')
    text=text.replace('            _submit(symbol, 0, "STOP")', '            _submit(symbol, 0, "STOP")\n            continue')
    text=text.replace('            _submit(symbol, 0, "TPALL")', '            _submit(symbol, 0, "TPALL")\n            continue')
    # Reconcile entry day from confirmed fill ledger, not position_days fallback.
    text=text.replace('            entry_date = today if int(pos.position_days) <= 0 else None', '            entry_date = g.entry_dates.get(symbol)\n            if entry_date is None:\n                g.session_blocked = True\n                log.warn("MISSING_ENTRY_DATE symbol=%s; reconcile required" % symbol)')
    patch=(BASE/'dynamic_500k_execution_20261008/runtime_patch.py').read_text(encoding='utf-8')
    patch=patch.replace("科创3旧模型动态仓位50万_执行修复V1", "科创3-1固定仓位50万_执行审计修复V1")
    patch=patch.replace('dynamic=10%%..20%%','fixed_target=10%%')
    patch=patch.replace('    g.records = {}','    g.records = {}\n    g.entry_dates = {}')
    patch=patch.replace("oid = order_target_percent(symbol, target) if action == 'BUY' else order_target(symbol, int(target))", "oid = order_target(symbol, int(target))")
    patch=patch.replace("        if rec['action'] == 'TPHALF'", "        if rec['action'] == 'BUY':\n            g.entry_dates[rec['symbol']] = rec['date']\n        if rec['action'] == 'TPHALF'")
    patch=patch.replace('    g.cash_budget = float(context.portfolio.stock_account.available_cash)', '    _poll_orders(context)\n    if g.session_blocked:\n        return\n    g.cash_budget = float(context.portfolio.stock_account.available_cash)')
    patch+='''
def _buy_size(nav, price, cash):
    if not np.isfinite(price) or price <= 0 or cash <= 5:
        return 0, 0.0
    # Keep target at <=10%; reserve adverse spread plus commission and one cent.
    padded = price * (1.0 + COST_SCENARIOS[COST_SCENARIO] / 2.0)
    qty = int(min(nav * 0.10 / price, (cash - 5.01) / (padded * 1.0003)))
    reserve = qty * padded + max(5.0, qty * padded * .0003) + .01
    if qty < 200 or reserve > cash:
        return 0, 0.0
    return qty, reserve
'''
    text+='\n\n'+patch
    text='# Platform: stock / daily / initial cash 500000 / independent empty account.\n'+text
    compile(text,'platform','exec')
    old=ast.parse(raw.decode('utf-8-sig'));new=ast.parse(text)
    def blobs(t):return {n.targets[0].id:ast.literal_eval(n.value) for n in t.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id.startswith('_EMBEDDED')}
    assert blobs(old)==blobs(new)
    target=HERE/'supermind_3_1_fixed_500k_execution_v1.py'
    target.write_text(text,encoding='utf-8')
    (HERE/'runtime_patch.py').write_text(patch,encoding='utf-8')
    (HERE/'manifest.json').write_text(json.dumps({'source_sha256':hashlib.sha256(raw).hexdigest(),'output_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'models_unchanged':True,'retrained':False,'platform_server_tested':False,'changes':['synchronous callback buffering and polling','explicit share sizing <=10%, cash reservation, minimum200','fill date ledger','expiry fallback for unhalvable positions','signal date filter','version logs']},indent=2),encoding='utf-8')
    assert source.read_bytes()==raw
    inputs=HERE/'inputs'
    if inputs.exists():
        (HERE/'input_manifest.json').write_text(json.dumps({p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in inputs.iterdir() if p.is_file()},indent=2),encoding='utf-8')
    print(target)
if __name__=='__main__':main()
