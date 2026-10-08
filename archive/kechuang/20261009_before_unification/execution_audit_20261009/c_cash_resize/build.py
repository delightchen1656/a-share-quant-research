"""Minimal derivative: retain dynamic legacy behavior, allow cash-limited entry."""
from pathlib import Path
import ast,hashlib,json,math
HERE=Path(__file__).resolve().parent
SOURCE=Path(r'C:\Users\22241\.codex\attachments\e69a4b9a-10c8-4d0a-9cf6-9b56177d08a1\已粘贴的文本.txt')
HELPER='''
def _cash_limited_buy_qty(total_value, target_fraction, price, cash):
    # Estimate adverse fill from the existing configured spread. No new signal.
    if not np.isfinite(price) or price <= 0 or cash <= 5:
        return 0
    px = price * (1.0 + COST_SCENARIOS[COST_SCENARIO] / 2.0)
    desired = int(total_value * target_fraction / px)
    affordable = int(max(0.0, cash - 5.0) / (px * 1.0003))
    qty = min(desired, affordable)
    if qty < MIN_STAR_SHARES or qty * px + max(5.0, qty * px * .0003) > cash:
        return 0
    return qty
'''
def main():
    raw=SOURCE.read_bytes();old=raw.decode('utf-8-sig')
    before='''            required_cash = total_value * target_fraction * 1.005
            if _available_cash(context) < required_cash:
                continue
            order_id = order_target_percent(symbol, target_fraction)'''
    after='''            required_cash = total_value * target_fraction * 1.005
            available_cash = _available_cash(context)
            if available_cash < required_cash:
                qty = _cash_limited_buy_qty(total_value, target_fraction, price, available_cash)
                if qty < MIN_STAR_SHARES:
                    log.info("CASH_RESIZE_SKIP %s cash=%.2f" % (symbol, available_cash))
                    continue
                log.info("CASH_RESIZE_BUY %s qty=%d cash=%.2f" % (symbol, qty, available_cash))
                order_id = order_target(symbol, qty)
            else:
                order_id = order_target_percent(symbol, target_fraction)'''
    assert old.count(before)==1
    text='# C candidate: DAILY, platform initial cash=500000. Legacy dynamic 10%-20%; ONLY cash-limited entry changed.\n'+old.replace(before,after)+HELPER
    compile(text,'platform','exec')
    a=ast.parse(old);b=ast.parse(text)
    funcs=lambda t:{n.name:ast.dump(n) for n in t.body if isinstance(n,ast.FunctionDef)}
    fa,fb=funcs(a),funcs(b)
    unchanged=[n for n in fa if n!='handle_bar'];assert all(fa[n]==fb[n] for n in unchanged)
    constants=lambda t:{n.targets[0].id:ast.dump(n.value) for n in t.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name)}
    assert constants(a)==constants(b)
    ns={'np':type('NP',(),{'isfinite':staticmethod(math.isfinite)}),'COST_SCENARIOS':{'neutral':.004},'COST_SCENARIO':'neutral','MIN_STAR_SHARES':200}
    exec(HELPER,ns);f=ns['_cash_limited_buy_qty']
    tests=0
    for price in [10,50,100,250,300,490]:
        for cash in [0,5,1000,3000,20000,49900,100000]:
            target=max(.1,price*200*1.01/500000)
            q=f(500000,target,price,cash);px=price*1.002
            assert q==0 or (q>=200 and q*px+max(5,q*px*.0003)<=cash and q*px<=500000*target)
            tests+=1
    assert f(500000,.1,15,1650)==0
    assert f(500000,.1,15,10000)>=200
    dest=HERE/'supermind_3_legacy_dynamic_500k_cash_resize_C.py';dest.write_text(text,encoding='utf-8')
    p=HERE/'uploaded_legacy_source.py'
    if p.exists():assert p.read_bytes()==raw
    else:p.write_bytes(raw)
    (HERE/'verification.json').write_text(json.dumps({'passed':True,'boundary_cases':tests+2,'unchanged_functions':unchanged,'constants_and_models_unchanged':True,'source_sha256':hashlib.sha256(raw).hexdigest(),'output_sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'platform_tested':False,'remaining_legacy_issues':['callback race/audit zeros','missing entry date fallback','unhalvable expiry branch','no async local cash reservation'],'local_comparison':'C uses common daily proxy and sizes all buys explicitly; platform retains original percent order for fully funded buys, not exact platform return reproduction'},indent=2),encoding='utf-8')
    print(dest);print('PASS',tests+2,'boundary cases; only handle_bar changed plus one sizing helper')
if __name__=='__main__':main()
