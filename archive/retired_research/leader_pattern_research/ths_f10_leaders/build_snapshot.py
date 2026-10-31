"""Assemble the exact public F10 concept-table field; preserve cross-page differences."""
from pathlib import Path
from collections import defaultdict
import hashlib,json,re,unicodedata
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent
SNAP=HERE/'holdout_restricted/snapshot_20261027'
OUT=SNAP/'lists'
MAIN=r'^(600|601|603|605|000|001|002|003)\d{3}$'

def norm(s):return ''.join(unicodedata.normalize('NFKC',s).split())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def board(code):
    if re.fullmatch(MAIN,code):return '沪深主板'
    if code.startswith(('300','301')):return '创业板'
    if code.startswith(('688','689')):return '科创板'
    if code.startswith(('4','8','92')):return '北交所或其他场所待单独核验'
    return '其他待核验'

def main():
    OUT.mkdir(exist_ok=True)
    catalog=json.loads((SNAP/'catalog_union.json').read_text(encoding='utf-8'))
    assert len(catalog)==390 and len({r['href'] for r in catalog})==390
    assert len({norm(r['name']) for r in catalog})==390
    cat_by_name={norm(r['name']):r for r in catalog}
    boards={};sources=defaultdict(list);name_by_code={};conflicts=[]
    files=sorted(SNAP.glob('stock_*.json'))
    for file in files:
        page=json.loads(file.read_text(encoding='utf-8'))
        url=page.get('url',page.get('source_url'));assert url and '/concept.html' in url
        for row in page['rows']:
            assert norm(row['concept']) in cat_by_name
            assert re.fullmatch(r'\d{6}',row['board_code'])
            for stock in row['leaders']:
                assert re.fullmatch(r'\d{6}',stock['code']) and stock['name']
                if stock['code'] in name_by_code:assert name_by_code[stock['code']]==stock['name']
                name_by_code[stock['code']]=stock['name']
            code=row['board_code'];sig={(r['code'],r['name']) for r in row['leaders']}
            if code in boards and {(r['code'],r['name']) for r in boards[code]['leaders']}!=sig:conflicts.append(code)
            if code not in boards:boards[code]=row
            sources[code].append(dict(url=url,captured_at=page['captured_at'],file=file.name))
    assert not conflicts,'Do not merge contradictory column snapshots.'
    assert len(boards)==387
    uncovered=[r for r in catalog if norm(r['name']) not in {norm(b['concept']) for b in boards.values()}]
    assert {r['name'] for r in uncovered}=={'沪股通','深股通','融资融券'}
    rows=[];concepts=[]
    for code,row in sorted(boards.items(),key=lambda x:x[1]['concept']):
        source=sources[code][0]
        concepts.append(dict(concept=row['concept'],board_code=code,leaders=row['leaders'],
            source_url=source['url'],captured_at=source['captured_at'],consistent_source_pages=len(sources[code])))
        for order,stock in enumerate(row['leaders'],1):
            rows.append(dict(concept=row['concept'],board_code=code,code=stock['code'],name=stock['name'],
                source_display_order=order,source_url=source['url'],captured_at=source['captured_at'],
                consistent_source_pages=len(sources[code])))
    relationships=pd.DataFrame(rows);assert len(relationships)==1131
    assert not relationships.duplicated(['board_code','code']).any()
    current=json.loads((ROOT/'leader_pattern_research/market_wide/holdout_restricted/CURRENT.json').read_text(encoding='utf-8'))
    universe=pd.read_parquet(current['universe']);viewer_names=dict(zip(universe.code,universe.name))
    stocks=[]
    for code,g in relationships.groupby('code',sort=True):
        stocks.append(dict(code=code,name=g.name.iloc[0],market=board(code),concept_count=g.board_code.nunique(),
            concepts=sorted(set(g.concept)),in_viewer_universe=code in viewer_names,
            viewer_name=viewer_names.get(code),source_urls=sorted(set(g.source_url))))
    mainstocks=[r for r in stocks if r['market']=='沪深主板']
    assert len(stocks)==520 and len(mainstocks)==405
    cards=json.loads((SNAP/'board_card_crosschecks.json').read_text(encoding='utf-8'))
    differences=[];supplemental=set()
    for card in cards:
        direct=boards.get(card['board_code']);other={r['code'] for r in card['leaders']}
        if direct is None or {r['code'] for r in direct['leaders']}!=other:
            differences.append(dict(concept=card['concept'],board_code=card['board_code'],
                direct_column_leaders=direct['leaders'] if direct else None,
                concept_page_leaders=card['leaders'],concept_page_url=card['url'],
                resolution='Keep exact selected column; do not silently fill from concept page.'))
        supplemental |=other-set(name_by_code)
    pd.DataFrame(stocks).to_parquet(OUT/'all_leaders.parquet',index=False)
    pd.DataFrame(mainstocks).to_parquet(OUT/'mainboard_leaders.parquet',index=False)
    relationships.to_parquet(OUT/'concept_leader_relationships.parquet',index=False)
    dump(OUT/'all_leaders.json',stocks);dump(OUT/'mainboard_leaders.json',mainstocks)
    dump(OUT/'concepts.json',concepts);dump(OUT/'cross_page_differences.json',differences)
    matched=sum(r['in_viewer_universe'] for r in mainstocks)
    empty=[r for r in concepts if not r['leaders']]
    audit=dict(snapshot_date='2026-10-27',definition='exact individual-stock F10 concept table 龙头股 column',
        reference_catalog_concepts=390,catalog_assembly='Alphabet menu + all39timelinepages, deduplicated by source concept URL',
        timeline_rows=390,timeline_unique=381,catalog_union_unique=390,
        stock_f10_pages=len(files),direct_column_concepts=len(concepts),
        nonempty_column_concepts=len(concepts)-len(empty),official_empty_column_concepts=[r['concept'] for r in empty],
        missing_in_selected_column=[r['name'] for r in uncovered],
        supplementary_concept_pages_checked=True,cross_page_differences=differences,
        supplementary_codes_not_in_selected_column=sorted(supplemental),
        relationships=len(relationships),unique_stocks=len(stocks),mainboard_stocks=len(mainstocks),
        mainboard_matched_viewer=matched,mainboard_not_in_viewer=[r['code'] for r in mainstocks if not r['in_viewer_universe']],
        same_column_cross_source_conflicts=len(conflicts),
        software_star_pool_changed=False,not_historical_point_in_time_membership=True,
        source_definition_url='https://basic.10jqka.com.cn/48/885694/',
        source_rule='综合概念股涨停次数、涨停时间及累计涨幅的最优排名',
        source_files=[dict(path=str(p.relative_to(SNAP)),sha256=sha(p)) for p in files])
    dump(OUT/'AUDIT.json',audit)
    for name,data in [('同花顺F10概念龙头_全市场520只.txt',stocks),('同花顺F10概念龙头_沪深主板405只.txt',mainstocks)]:
        lines=[name[:-4],'采集日期：2026-10-27。严格来自个股F10“概念题材”的“龙头股”列。',
            '390个官方目录项中，387项读到该列，其中9项官方空白；沪股通、深股通、融资融券仅在概念F10页另行补查，不混入指定列。',
            '同花顺不同F10页面存在差异，单独留档；此名单保留指定列原值，不把另一页面的股票填进空白。',
            '这是采集日快照，不是历史龙头归属；软件现有★范围未替换。','',
            '股票代码  名称  市场  出现概念数  概念列表']
        for r in data:lines.append(f"{r['code']}  {r['name']}  {r['market']}  {r['concept_count']}  {'、'.join(r['concepts'])}")
        (OUT/name).write_text('\n'.join(lines),encoding='utf-8')
    lines=['同花顺F10概念—龙头逐项清单（指定列）','采集日期：2026-10-27；空白保持原样，不用其他页面填补。','']
    for r in concepts:
        names='、'.join(f"{x['name']}({x['code']})" for x in r['leaders']) or '官方该列为空 / --'
        lines.extend([f"{r['concept']} [{r['board_code']}]：{names}",f"来源：{r['source_url']}",''])
    (OUT/'概念对应及来源387项.txt').write_text('\n'.join(lines),encoding='utf-8')
    summary=['同花顺F10龙头列采集说明','',
        f'官方概念目录390项；个股概念题材龙头列387项，非空378项，官方空白9项。',
        f'总计1131条概念—股票关系；去重520只股票；沪深主板405只，其中{matched}只已在当前查看器股票范围。',
        '三个未出现在所选列的目录项：沪股通、深股通、融资融券；已核对其概念F10页，作为补充文件独立保存。',
        f'补充页与所选列内容不同的概念有{len(differences)}项，不混合。补充页另有{len(supplemental)}只不在所选列去重名单中的股票，未加入520只。',
        '同花顺官方说明：综合概念股涨停次数、涨停时间及累计涨幅的最优排名。口径偏交易表现，不能直接解释为长期产业地位或板块同步性。',
        '现有软件★范围与策略均未修改；不将采集日名单回填历史回测。','',
        '铜缆高速连接示例：通宇通讯002792、神宇股份300563、华脉科技603042。']
    (OUT/'采集说明.txt').write_text('\n'.join(summary),encoding='utf-8')
    print(json.dumps({k:audit[k] for k in ['reference_catalog_concepts','direct_column_concepts','nonempty_column_concepts','unique_stocks','mainboard_stocks','mainboard_matched_viewer','same_column_cross_source_conflicts','supplementary_codes_not_in_selected_column']},ensure_ascii=False))

if __name__=='__main__':main()
