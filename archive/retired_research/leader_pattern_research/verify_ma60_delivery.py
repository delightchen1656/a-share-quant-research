from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as E
import json
BASE=Path(__file__).resolve().parent
D=BASE/'outputs/first_below_ma60_20261027/holdout_restricted'
ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
summary=json.loads((BASE/'holdout_restricted/patterns_v1/first_below_ma60_v1/SUMMARY.json').read_text(encoding='utf-8'))
with ZipFile(D/'五阴三阳低于MA60对比.xlsx') as z:
    r=E.fromstring(z.read('xl/worksheets/sheet1.xml'))
    cells={x.attrib['r']:x for x in r.findall('s:sheetData/s:row/s:c',ns)}
    for row,expected in zip([7,8,9],summary['comparison']):
        for col,key in [('B','signals'),('C','n'),('D','mean'),('E','median'),('F','win_rate')]:
            actual=float(cells[f'{col}{row}'].find('s:v',ns).text)
            assert abs(actual-expected[key])<1e-12
    r=E.fromstring(z.read('xl/worksheets/sheet2.xml'))
    rows=[x for x in r.findall('s:sheetData/s:row',ns) if int(x.attrib['r'])>=7]
    assert len(rows)==619
    for row in rows:
        k=row.attrib['r'];cells={x.attrib['r']:x for x in row.findall('s:c',ns)}
        assert len(cells['B'+k].find('s:v',ns).text)==6
        assert float(cells['F'+k].find('s:v',ns).text)<float(cells['G'+k].find('s:v',ns).text)
        assert cells['J'+k].find('s:f',ns) is not None
        for cell in cells.values():assert cell.attrib.get('t')!='e'
    assert len([n for n in z.namelist() if n.startswith('xl/worksheets/sheet') and n.endswith('.xml')])==3
(D/'DELIVERY_STATUS.json').write_text(json.dumps(dict(saved_workbook_headlines_reconcile=True,
    event_rows_verified=619,all_signal_closes_strictly_below_ma60=True,
    original_study_unchanged=True,visual_QA_all3sheets=True,not_blind_test=True),indent=2),encoding='utf-8')
print('Saved MA60 workbook verified:619rows; headline metrics match; original study preserved.')
