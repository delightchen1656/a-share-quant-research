"""Fetch only an explicit pre2025 company/year gap list; checkpoint every response."""
import argparse
import hashlib
import json
import socket
import time
from pathlib import Path
import baostock as bs

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def save(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--gaps', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    plan = read(args.gaps)
    assert all(len(item) == 2 and 2018 <= int(item[1]) <= 2024 for item in plan)
    args.output.mkdir(parents=True, exist_ok=True)
    plan_hash = sha(args.gaps)
    plan_record = dict(queries=plan, source_sha256=plan_hash, cutoff='2024-12-31')
    save(args.output / f'query_plan_{plan_hash}.json', plan_record)
    save(args.output / 'query_plan.json', plan_record)
    manifest_path = args.output / 'manifest.json'
    manifest = read(manifest_path) if manifest_path.exists() else {}
    failures = []
    socket.setdefaulttimeout(30)
    assert bs.login().error_code == '0'
    try:
        for symbol, year in plan:
            name = f'{symbol}_{year}.json'
            path = args.output / name
            if name in manifest:
                assert sha(path) == manifest[name]['sha256']
                continue
            request = dict(code=symbol[-2:].lower()+'.'+symbol[:6], year=str(year), yearType='operate')
            for attempt in range(3):
                try:
                    result = bs.query_dividend_data(**request)
                    assert result.error_code == '0', result.error_msg
                    records = []
                    while result.next():
                        records.append(dict(zip(result.fields, result.get_row_data())))
                    assert result.error_code == '0'
                    assert all(not row.get('dividOperateDate') or row['dividOperateDate'] <= '2024-12-31' for row in records)
                    save(path, dict(key=f'{symbol}/{year}', records=records, request=request,
                                    error_code=result.error_code, error_msg=result.error_msg,
                                    fields=result.fields, row_count=len(records),
                                    successful_empty_response=not records, cutoff='2024-12-31'))
                    manifest[name] = dict(key=f'{symbol}/{year}', sha256=sha(path))
                    save(manifest_path, manifest)
                    break
                except Exception as error:
                    failures.append(dict(symbol=symbol, year=year, attempt=attempt+1, error=repr(error)))
                    save(args.output / 'query_errors.json', failures)
                    if attempt == 2:
                        raise
                    bs.logout()
                    time.sleep(1)
                    assert bs.login().error_code == '0'
            time.sleep(.05)
    finally:
        bs.logout()
    print(json.dumps(dict(requested=len(plan), complete=True, manifest=str(manifest_path))))

if __name__ == '__main__':
    main()
