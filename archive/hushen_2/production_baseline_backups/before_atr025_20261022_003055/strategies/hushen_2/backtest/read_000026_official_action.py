"""Read-only download/extract official company action evidence; no strategy/account changes."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen,Request
from pypdf import PdfReader


def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);args=parser.parse_args()
    out=args.output;out.mkdir(parents=True,exist_ok=True)
    sources=[('000026_2025_distribution_20260603.pdf','https://static.cninfo.com.cn/finalpage/2026-06-03/1225347066.PDF'),
             ('000026_2026_halfyear.pdf','https://disc.static.szse.cn/disc/disk03/finalpage/2026-08-21/fdde0bd9-7985-4de0-af20-473b5536339b.PDF')]
    receipts=[]
    for name,url in sources:
        path=out/name
        if not path.exists():
            request=Request(url,headers={'User-Agent':'Mozilla/5.0'})
            with urlopen(request,timeout=30) as response:
                data=response.read();status=response.status
            assert status==200 and data.startswith(b'%PDF')
            path.write_bytes(data)
        else:data=path.read_bytes();status=200
        reader=PdfReader(path)
        pages=[]
        for number,page in enumerate(reader.pages,1):
            text=page.extract_text() or ''
            pages.append(dict(page=number,text=text))
        (out/(name+'.text.json')).write_text(json.dumps(pages,ensure_ascii=False,indent=2),encoding='utf-8')
        receipt=dict(url=url,local_file=str(path.resolve()),sha256=hashlib.sha256(data).hexdigest(),http_status=status,pages=len(pages),fetched_at=datetime.now().isoformat())
        receipts.append(receipt)
        print(json.dumps(receipt,ensure_ascii=False))
        for page in pages:
            if name.startswith('000026_2025') or ('权益分派' in page['text'] or '利润分配' in page['text']):
                print('PAGE',page['page'],page['text'])
    (out/'OFFICIAL_DOCUMENT_RECEIPTS.json').write_text(json.dumps(receipts,ensure_ascii=False,indent=2),encoding='utf-8')
    pages=json.loads((out/'000026_2025_distribution_20260603.pdf.text.json').read_text(encoding='utf-8'))
    compact=''.join(''.join(p['text'].split()) for p in pages)
    assert '2026年6月9日' in compact and '2026年6月10日' in compact and '每10股派1.20元' in compact
    halfyear=json.loads((out/'000026_2026_halfyear.pdf.text.json').read_text(encoding='utf-8'))
    assert '48,691,680.84' in halfyear[97]['text']
    evidence=dict(source_kind='official_issuer_filing',key='000026.SZ/2026',documents=receipts,
        records={'000026.SZ/2026':[dict(dividOperateDate='2026-06-10',dividRegistDate='2026-06-09',dividPayDate='2026-06-10',
            dividCashPsBeforeTax='0.12',dividStocksPs='0',dividReserveToStockPs='0',source=receipts[0]['url'])]},
        coverage_basis='Official implementation announcement pp1-2 plus halfyear financial statements p98: total common-stock dividend 48,691,680.84 equals the one disclosed annual distribution. Announcement p1 confirms share capital unchanged from proposal disclosure through implementation. Scope resolves only actual held interval, not an invented successful empty full-year API response.',
        baostock_fallback_reason='Two login attempts failed to receive a successful response; no BaoStock empty response was fabricated.')
    (out/'OFFICIAL_ACTION_RECEIPT.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
