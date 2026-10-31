from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as E
import json
import pandas as pd
BASE=Path(__file__).resolve().parent
D=BASE/'outputs/patterns_20261027/holdout_restricted'
ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
p=D/'三种形态逐次信号研究.xlsx'
with ZipFile(p) as z:
    found=[]
    for index,n in [(2,1008),(3,107)]:
        root=E.fromstring(z.read(f'xl/worksheets/sheet{index}.xml'))
        rows=root.findall('s:sheetData/s:row',ns)
        data=[r for r in rows if int(r.attrib['r'])>=7]
        assert len(data)==n
        print('sheet',index,'widths',[(c.attrib) for c in root.findall('s:cols/s:col',ns)])
        for r in data:
            cells={c.attrib['r']:c for c in r.findall('s:c',ns)}
            num=r.attrib['r'];code=cells['B'+num]
            assert code.attrib.get('t')=='str'
            assert len(code.find('s:v',ns).text)==6
            for key in ['D','E','F']:
                cell=cells.get(key+num)
                if cell is not None and cell.find('s:v',ns) is not None:
                    assert cell.attrib.get('t') not in ['str','inlineStr']
            assert cells['I'+num].find('s:f',ns) is not None
            for c in cells.values():assert c.attrib.get('t')!='e'
        r=next(r for r in data if r.attrib['r']=='7')
        print('row7 core',[(c.attrib['r'],c.attrib.get('s'),c.find('s:v',ns).text if c.find('s:v',ns) is not None else None) for c in r.findall('s:c',ns)[:11]])
        found.append(dict(sheet=index,signal_rows=n,leading_zero_identifiers=True,typed_dates=True,return_formulas=True))
    root=E.fromstring(z.read('xl/worksheets/sheet1.xml'))
    cells={c.attrib['r']:c for c in root.findall('s:sheetData/s:row/s:c',ns)}
    summary=json.loads((BASE/'holdout_restricted/patterns_v1/event_results_v1r2/SUMMARY.json').read_text(encoding='utf-8'))
    for rule,row in [('first',7),('third',8)]:
        expected=summary['summaries'][rule]['price_change']
        for col,key in [('C','n'),('D','mean'),('E','median'),('F','win_rate')]:
            actual=float(cells[f'{col}{row}'].find('s:v',ns).text)
            assert abs(actual-expected[key])<1e-12,(col,row,actual,expected[key])
    assert len([n for n in z.namelist() if n.startswith('xl/worksheets/sheet') and n.endswith('.xml')])==4
(D/'DELIVERY_STATUS.json').write_text(json.dumps(dict(first_and_third_completed=True,second_completed=False,
    second_missing='Historical minute data and contemporaneous upper/lower price limits',
    saved_workbook_verified=found,headlines_reconcile_to_engine=True,raw_body_repair_signals_unchanged=True,
    results_version='event_results_v1r2',portfolio_not_computed=True),ensure_ascii=False,indent=2),encoding='utf-8')
print('Saved workbook checks passed.')
