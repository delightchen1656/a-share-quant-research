from pathlib import Path
import hashlib,json
HERE=Path(__file__).resolve().parent
SOURCE=Path(r'C:\Users\22241\.codex\attachments\80e5c6cf-9b67-4344-9bf0-81aab65ce39b\已粘贴的文本.txt')
source=SOURCE.read_text(encoding='utf-8-sig')
target=HERE.parent/'supermind_test2_D11_fast_weekly.py'
if target.exists():raise RuntimeError('Weekly entry already exists; do not silently overwrite')
(HERE/'uploaded_source.py').write_text(source,encoding='utf-8')
code=source.replace("VERSION = '2026-10-03-D11-fast-v5'","VERSION = '2026-10-06-D11-fast-calendar-weekly'")
code=code.replace("INTERVAL = 10 if MODEL == 'E10' else 20","REBALANCE_RULE = 'FIRST_TRADING_DAY_OF_CALENDAR_WEEK'")
helper='''def _weekly_rebalance_due(today, previous_session, first_entry):
    # Monday-based calendar weeks: holiday Mondays roll to the next session.
    # Compare with the preceding actual session, not a five-session counter.
    if first_entry:
        return True
    today = pd.Timestamp(today).normalize()
    previous_session = pd.Timestamp(previous_session).normalize()
    if previous_session >= today:
        raise ValueError('Weekly schedule requires a strictly prior session')
    week_start = today - pd.Timedelta(days=today.weekday())
    previous_week_start = previous_session - pd.Timedelta(days=previous_session.weekday())
    return week_start != previous_week_start


'''
code=code.replace('def mainboard(symbol):',helper+'def mainboard(symbol):',1)
code=code.replace('    g.alpha_first = True','    g.alpha_first = True\n    g.alpha_rebalance_due = False',1)
old='    rebalance = g.alpha_first or (g.alpha_index - 1) % INTERVAL == 0'
assert code.count(old)==2
code=code.replace(old,'    g.alpha_rebalance_due = _weekly_rebalance_due(today, prior[-1], g.alpha_first)\n    rebalance = g.alpha_rebalance_due',1)
code=code.replace(old,'    rebalance = g.alpha_rebalance_due',1)
code=code.replace("    log.info('%s: 100000 CNY, DAILY/open bar; platform accounting, not local return reproduction' % MODEL)","    log.info('%s WEEKLY: 100000 CNY, DAILY/open bar; first entry then first session of each calendar week; unfinished targets retry daily' % MODEL)")
code=code.replace('# -*- coding: utf-8 -*-','# -*- coding: utf-8 -*-\n# 以用户2026-10-06上传D11提速版为基准，仅改为自然周首个交易日调仓。\n# 平台仍设每日频率、10万元；首次运行可在周中建仓；周内继续处理未完成目标和原ST退出。\n# 原权重-0.35/-0.20/+0.25/-0.20不变，不是严格重训权重版；无新增收益结论。',1)
assert ' % INTERVAL' not in code
compile(code,str(target),'exec');target.write_text(code,encoding='utf-8')
(HERE/'manifest.json').write_text(json.dumps(dict(source_attachment=str(SOURCE),source_sha256=hashlib.sha256(source.encode()).hexdigest(),export_sha256=hashlib.sha256(code.encode()).hexdigest(),entrypoint=target.name,frequency='daily',rebalance='first entry, then first actual trading session of Monday-based calendar week',weights=[-.35,-.20,.25,-.20],initial_cash=100000,no_training=True,no_platform_backtest=True),ensure_ascii=False,indent=2),encoding='utf-8')
print(target)
