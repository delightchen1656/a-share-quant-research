from pathlib import Path
import ast,hashlib,json
HERE=Path(__file__).resolve().parent
SOURCE=Path(r'C:\Users\22241\.codex\attachments\f2175655-7e4c-4b63-9e96-7ec60ef2986b\已粘贴的文本.txt')
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
    raw=SOURCE.read_bytes();text=raw.decode('utf-8-sig')
    tree=ast.parse(text)
    # Preserve uploaded source as an immutable provenance copy.
    original=HERE/'uploaded_source.py'
    if original.exists():assert original.read_bytes()==raw
    else:original.write_bytes(raw)
    for name in ['init','before_trading','handle_bar']:
        text=text.replace('def '+name+'(', 'def _legacy_'+name+'(',1)
    text=text.replace('High Attack Adaptive Expiry DAILY 120K DYNAMIC initialized','High Attack Adaptive Expiry DAILY 500K DYNAMIC initialized')
    text=text.replace('BASELINE1-2 candidates=', 'STAR3_DYNAMIC500K candidates=')
    # The legacy prepare may clear only when the wrapper has checked no unresolved order.
    before='''            order_id = order_target_percent(symbol, target_fraction)
            if order_id is not None:
                g.order_locks[symbol] = order_id
                g.order_intent[order_id] = {"symbol": symbol, "action": "BUY", "probability": probability}
                g.submitted_action[symbol] = {"action": "BUY", "date": now.date()}
                slots -= 1'''
    after='''            order_id = _safe_place(symbol, target_fraction, "BUY", probability, required_cash)
            if order_id is not None:
                slots -= 1'''
    assert before in text;text=text.replace(before,after)
    # Never use a current-date daily bar as yesterday's signal.
    marker='''            values = _last_features(frame)'''
    assert marker in text
    text=text.replace(marker,'''            if frame is not None and len(frame):
                frame = frame.copy()
                frame.index = pd.to_datetime(frame.index)
                frame = frame[frame.index.normalize() < pd.Timestamp(today)]
            values = _last_features(frame)''')
    text+='\n\n'+(HERE/'runtime_patch.py').read_text(encoding='utf-8')
    text='# Set platform INITIAL CAPITAL=500000, STOCK, DAILY. Legacy models unchanged.\n'+text
    compile(text,'platform','exec')
    old={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ['_EMBEDDED_MODEL_B64','_EMBEDDED_STOP_MODEL_B64']}
    newtree=ast.parse(text)
    new={n.targets[0].id:ast.literal_eval(n.value) for n in newtree.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in old}
    assert old==new
    target=HERE/'supermind_3_legacy_dynamic_500k_execution_v1.py';target.write_text(text,encoding='utf-8')
    manifest={'source_sha256':sha(raw),'output_sha256':sha(target.read_bytes()),'model_blobs_unchanged':True,'retrained':False,'capital_setting':500000,'platform_server_tested':False,'sizing':'legacy dynamic10%-20% retained','model_hashes':{k:sha(v.encode()) for k,v in old.items()}}
    (HERE/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    assert SOURCE.read_bytes()==raw
    print(target)
if __name__=='__main__':main()
