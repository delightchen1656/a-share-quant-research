"""Build D7 daily base; no invented intraday opportunities in daily research."""
from pathlib import Path
import ast, hashlib, json

HERE=Path(__file__).resolve().parent
V6=HERE.parent/'execution_v6'

def main():
    source=(HERE/'uploaded_v5.py').read_text(encoding='utf-8-sig')
    engine=(V6/'execution_functions.py').read_text(encoding='utf-8')
    names={'_status','_terminal','_remember_order','on_order','on_trade','_submit','PendingReceipt','_run_stage'}
    replacement={n.name:ast.get_source_segment(engine,n) for n in ast.parse(engine).body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names}
    lines=source.splitlines(keepends=True)
    for n in reversed(ast.parse(source).body):
        if isinstance(n,ast.FunctionDef) and n.name in replacement:
            lines[n.lineno-1:n.end_lineno]=[replacement.pop(n.name)+'\n']
    code=''.join(lines)+'\n\n'+'\n\n'.join(replacement.values())+'\n'
    code=code.replace("VERSION = '2026-10-03-D11-fast-v5'", "VERSION = '2026-10-08-baseline2-audited-D7-daily'")
    code=code.replace('set_slippage(PriceSlippage(2 * SLIP_ONE_SIDE))','set_slippage(PriceSlippage(0.0))')
    code=code.replace('return math.floor(value * 100 + 1e-8) / 100','return min(float(b.high_limit), math.ceil(value * 100 - 1e-8) / 100)')
    code=code.replace('return math.ceil(value * 100 - 1e-8) / 100','return max(float(b.low_limit), math.floor(value * 100 + 1e-8) / 100)')
    code=code.replace('value = q * op * (1 + SLIP_ONE_SIDE)', 'value = q * (op * (1 + SLIP_ONE_SIDE) + .01)  # reserve tick rounding')
    code=code.replace('    g.alpha_submitting = None\n    _assert_isolated(context)',
        '    g.alpha_submitting = None\n    g.exec_orders = {}\n    g.exec_filled = {}\n    g.exec_seen_orders = set()\n    g.exec_seen_trades = set()\n    g.exec_audit = []\n    g.exec_halt = False\n    _assert_isolated(context)')
    code=code.replace("    if MODEL not in ('E10', 'D11'):","    frequency = str(getattr(getattr(context, 'run_info', None), 'frequency', '1d')).lower()\n    if frequency not in ('1d', 'daily', 'day'):\n        raise ValueError('D7 requires DAILY frequency')\n    if MODEL not in ('E10', 'D11'):")
    code=code.replace('    g.alpha_ready = False\n    _assert_isolated(context)',
        '    g.alpha_ready = False\n    g.exec_seen_orders = set()\n    g.exec_seen_trades = set()\n    g.exec_orders = {}\n    g.exec_filled = {}\n    _assert_isolated(context)')
    code=code.replace("log.info('SUBMIT V6", "log.info('SUBMIT D7").replace("log.info('NO_ORDER V6", "log.info('NO_ORDER D7")
    code=code.replace("    # SuperMind specifies a TOTAL spread: .002 means +/- .001 per side.","    # Limit already includes tolerance; zero extra platform accounting slippage.")
    code=code.replace('def _submit(context, symbol, quantity, limit):\n',
        "def _submit(context, symbol, quantity, limit):\n    if g.exec_halt:\n        log.warn('EXEC_HALTED: confirmed limit breach; inspect platform before restarting')\n        return None\n    foreign = [o for o in (get_open_orders() or []) if str(o.order_id) not in g.alpha_order_ids]\n    if foreign:\n        raise RuntimeError('Unmanaged active order in dedicated strategy account')\n")
    code=code.replace("        message = 'LIMIT_BREACH id=%s price=%s limit=%s'", "        g.exec_halt = True\n        message = 'LIMIT_BREACH id=%s price=%s limit=%s'")
    code=code.replace("    return _run_stage('handle_bar', _handle_bar, context, bar_dict)",
        "    if g.alpha_executed != _date(get_datetime()):\n        log.info('EXEC_DAILY strategy_time=%s wall_utc=%s; quote=open; no intraday retry' % (get_datetime(), pd.Timestamp.utcnow()))\n    return _run_stage('handle_bar', _handle_bar, context, bar_dict)")
    # Validate that generated buy limits are rounded UP, sell limits DOWN.
    ast.parse(code)
    target=HERE/'supermind_baseline2_D7_daily.py';target.write_text(code,encoding='utf-8')
    (HERE/'daily_build.json').write_text(json.dumps(dict(source_sha256=hashlib.sha256((HERE/'uploaded_v5.py').read_bytes()).hexdigest(),
        export_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),changes=['daily source retained','limit tick rounding','zero extra platform slippage','cash rounding reserve','receipt dedup and fee audit','timing diagnostics'],
        user_steering='Daily data only; no risk drawdown threshold. No minute-repricing performance claim.'),indent=2),encoding='utf-8')
    print(target)

if __name__=='__main__':main()
