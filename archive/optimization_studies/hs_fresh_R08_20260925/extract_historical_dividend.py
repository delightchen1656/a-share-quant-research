"""Read-only source PDF extraction; no changes to the downloaded original."""
import hashlib,json,re
from pathlib import Path
from pypdf import PdfReader
import pypdfium2 as pdfium

HERE=Path(__file__).resolve().parent
SRC=HERE/'public_sources/dacheng_dividend_2019_halfyear.pdf'
reader=PdfReader(SRC)
first=reader.pages[0].extract_text()
assert re.search(r'2019\s*年\s*8\s*月\s*27\s*日',first)
text='\n'.join(reader.pages[i].extract_text() for i in (33,34,35))
section=text.split('7.3.1',1)[1].split('7.3.2',1)[0]
pattern=r'^\s*(\d+)\s+(\d{6})\s+(.+?)\s+([\d,]+)\s+([\d,.]+)\s+([\d.]+)\s*$'
rows=[]
for m in re.finditer(pattern,section,re.M):
    n,code,name,shares,value,weight=m.groups()
    rows.append(dict(ordinal=int(n),symbol=code+('.SH' if code.startswith('6') else '.SZ'),
        name=name,shares=int(shares.replace(',','')),value=float(value.replace(',','')),weight_pct=float(weight)))
assert [x['ordinal'] for x in rows]==list(range(1,99)),len(rows)
assert len({x['symbol'] for x in rows})==98
total=sum(x['value'] for x in rows)
assert abs(total-1104531453.35)<.01,total
obj=dict(source_url='https://download.hexun.com/ftp/all_stockdata_2009/all/120/664/1206647980.pdf',
    source_sha256=hashlib.sha256(SRC.read_bytes()).hexdigest(),asof='2019-06-30',published='2019-08-27',
    section='7.3.1 index-investment complete holdings; not a claim of exact index membership',
    exclude='7.3.2 active-investment holdings',rows=rows,total_value=total)
(SRC.parent/'dividend_holdings_2019.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
pdf=pdfium.PdfDocument(SRC)
for p in (0,33,35):
    pdf[p].render(scale=1.5).to_pil().save(SRC.parent/('source_page_%02d.png'%(p+1)))
print(json.dumps(dict(rows=len(rows),total_value=total,published=obj['published'])))
