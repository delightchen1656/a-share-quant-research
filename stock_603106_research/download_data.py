"""Download a fresh, self-contained BaoStock snapshot; never read other projects."""
from pathlib import Path
from datetime import datetime, timedelta
import argparse
import hashlib
import json
import baostock as bs
import pandas as pd

ROOT = Path(__file__).resolve().parent
FIELDS = 'date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST'

def frame(result):
    rows = []
    while result.error_code == '0' and result.next():
        rows.append(result.get_row_data())
    if result.error_code != '0':
        raise RuntimeError(f'{result.error_code}: {result.error_msg}')
    return pd.DataFrame(rows, columns=result.fields)

def main():
    parser = argparse.ArgumentParser()
    now = datetime.now()
    default_end = (now if now.hour >= 19 else now - timedelta(days=1)).date().isoformat()
    parser.add_argument('--end', default=default_end)
    args = parser.parse_args()
    folder = ROOT / 'data'
    folder.mkdir(exist_ok=True)
    login = bs.login()
    if login.error_code != '0':
        raise RuntimeError(login.error_msg)
    manifest = {'provider': 'BaoStock', 'symbol': 'sh.603106', 'requested_start': '2020-01-01',
                'requested_end': args.end, 'downloaded_at': now.isoformat(),
                'fresh_network_download': True, 'files': {}}
    try:
        for kind, flag in [('raw', '3'), ('qfq', '2')]:
            data = frame(bs.query_history_k_data_plus('sh.603106', FIELDS,
                         start_date='2020-01-01', end_date=args.end, frequency='d', adjustflag=flag))
            if data.empty:
                raise RuntimeError(f'No {kind} daily bars returned')
            for col in set(data.columns) - {'date', 'code'}:
                data[col] = pd.to_numeric(data[col], errors='raise')
            data.to_parquet(folder / f'{kind}.parquet', index=False)
            print(kind, len(data), data.date.min(), data.date.max(), flush=True)
        actions = []
        for year in range(2020, int(args.end[:4]) + 1):
            result = frame(bs.query_dividend_data(code='sh.603106', year=str(year), yearType='operate'))
            actions.append(result)
        pd.concat(actions, ignore_index=True).drop_duplicates().to_parquet(folder / 'dividends.parquet', index=False)
        frame(bs.query_stock_basic(code='sh.603106')).to_parquet(folder / 'security.parquet', index=False)
        frame(bs.query_trade_dates(start_date='2020-01-01', end_date=args.end)).to_parquet(folder / 'calendar.parquet', index=False)
    finally:
        bs.logout()
    for path in sorted(folder.glob('*.parquet')):
        data = pd.read_parquet(path)
        manifest['files'][path.name] = {'rows': len(data), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        if 'date' in data:
            manifest['files'][path.name].update(first_date=str(data.date.min()), last_date=str(data.date.max()))
    (folder / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Fresh snapshot saved:', folder, flush=True)

if __name__ == '__main__':
    main()
