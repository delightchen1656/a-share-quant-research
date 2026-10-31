"""Register the user's Tuesday touch/reopen exit rule and probe pre2024intraday coverage."""
from pathlib import Path
import sys
import json
import datetime
import hashlib
import pandas as pd

BASE=Path(__file__).resolve().parent.parent
ROOT=BASE.parent
OUT=BASE/'audits/holdout_restricted/monday_trading_rules_v2'
OLD=BASE/'audits/holdout_restricted/monday_trading_rules_v1'
STORE=BASE/'inputs_pre2025/intraday5m_probe_v2'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()


def dump(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    assert not (OUT/'RULES.json').exists(),'Retain registered versions'
    rules=json.loads((OLD/'RULES.json').read_text(encoding='utf-8'))
    rules.update(id='Monday_selection_Tuesday_touch_limit_then_reopen_exit_v2',
        status='User-confirmed exit-event logic; intraday execution resolution pending, no new performance claimed.',
        parent_rules_sha256=sha(OLD/'RULES.json'),
        authorization='User: Tuesday forced close unless limitdown; then clarifies Tuesday intraday touch activates immediate first-reopen exit, not waiting Tuesdayclose or nextTuesday.',
        data_boundary='Only pre2024development inputs in optimizer. Postperiod audit outputs never read. New lower-frequency data cannot be labelled exact tick execution.')
    rules['holding'].update(normal_exit='If no Tuesday limit-down touch has occurred, exit at Tuesdayclose as before.',
        limit_touch_exit='Any Tuesday intraday touch of that day legal lower limit activates persistent exit intent. First later reopening with executable buy-side liquidity triggers exit attempt, including Tuesday before close.',
        unresolved_after_Tuesday='If still locked at Tuesdayclose, continue monitoring every following actual trading session; exit on first executable reopening, do not wait for nextTuesday.',
        same_day_price_reference='Judge reopening relative to that session legal lower limit, not the originalTuesdayfloor.',
        partial_exit='Keep trying remaining shares until filled; no imaginary sale or guaranteed fill merely because a trade print exists.')
    rules['schedule']['old_position_exit']='Triggered emergency exit may occur Wednesday-Friday or any later open session; normal new entries remain Mondayopen.'
    rules['sell'].update(order_type='NormalTuesdayclose exit plus persistent Tuesday-touch/reopening emergency exit.',
        normal_price='Idealized Tuesdayclose for valid currently listed shares if no emergency fill and not locked at lower limit.',
        capacity_policy='Remove sell-side1%prior-volume cap and lowerlimit-plus-tick price restriction in the idealized price test. Buy-side constraints unchanged.',
        capacity_fraction_of_previous_session_volume=None,
        limit_price=None,
        failure='If limitlocked keep exit intent; no valid trade quote or unlisted shares are data/legal constraints, tracked separately, not fabricated fills.',
        retry='First executable reopening in any subsequent trading session; earlier Tuesday intraday reopening executes before scheduledclose.',
        timing_evidence='Exactfirstreopen requires ordered trade/quote data and liquidity. A daily high abovefloor gives neither event order nor a first executable fill price.')
    rules['capital']['same_open_emergency_exit']='Mondaynew-buy budgets and slots remain based on confirmed preauction cash/holdings; do not spend unconfirmed proceeds from an emergency sale in the same openingauction.'
    rules['comparison_to_signal_study']='New user-directed intraday exit changes original fixed Tuesdayclose label window. This is a new execution rule, not factor optimization or a proven profit improvement.'
    rules['intraday_resolution']=dict(exact='Orderedticks/quotes with executable bid evidence; no same-timestamp hindsight.',
        possible5m_proxy='Only if user accepts: observe completed5mbar for touch/reopening, then attempt at next eligiblebaropen; no samebar high/low sequencing assumption or sale at previously knownfloorplusone.',
        currently_approved_proxy=None)
    dump(OUT/'RULES.json',rules)
    text='''周一选股买卖规则V2：周二触及跌停后，首次开板退出

绑定原冻结“11因子＋120日动量”探索模型；因子、训练、周一买入、top10、资金预算与费用不变。本次只按用户明确指令改变卖出规则，未读取后验成绩。

正常情形：周二没有触及当日跌停价，仍按周二有效收盘价强制退出。
触发情形：周二盘中一旦触及当日跌停价，即进入持续退出状态；首次开板且有可成交买盘时马上尝试卖出，不等收盘。
跨日情形：若周二仍封跌停，从之后每个实际交易时段继续监控，首次可成交开板即尝试退出，可在周三至周五或以后任何开市日卖出，不再等下周二。
判断开板使用当日合法跌停价，不要求回到原周二跌停价。部分成交后保留余股继续尝试。
卖出端取消原成交量1%容量限制和“跌停价加一档”的限制，作为理想化成交研究；买入端保持原容量、开盘前定量、预算预留与失败留现金规则。
停牌、缺少有效成交报价或未上市红股另行记录，不用旧价冒充新成交，不提前卖出未上市权益。原始买入股已退出与附生权益待交付要分别列示。
若应急卖出和周一新买同处开盘集合竞价，新买单仍只用事前确认的现金与空闲名额，不把未确认卖出资金预先花掉。

数据要求：日K不能确定触板和开板的先后顺序，也不能定位首次可成交价。逐笔/盘口是精确验证所需；5分钟只能是另行明确的近似，观察完整bar后才可发单，不得利用同一bar最高最低价倒推成交。
尚未宣称新规则的回测收益；精度口径确认和盘中数据核验通过后，才能单独计算。旧V1及其V1.1账簿回测全部保留。
'''
    (OUT/'RULES.txt').write_text(text,encoding='utf-8')
    dump(OUT/'REGISTRATION.json',dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        before_intraday_rule_performance=True,user_confirmed_trigger='Tuesdayintradaytouch',
        rules_sha256=sha(OUT/'RULES.json'),code_sha256=sha(Path(__file__)),postperiod_metrics_not_read=True))
    # Availability probe uses only this study's already observed development
    # holding episodes, never2025-2026prices. No strategy return is computed.
    logs=pd.read_parquet(BASE/'audits/holdout_restricted/monday_account_backtest_v1_1/execution_log.parquet')
    examples=logs.loc[logs.method.eq('long120')&logs.kind.eq('sell_delayed')&logs.reason.eq('close_below_sell_limit')].sort_values('date')
    probe=examples.iloc[[0,-1]][['symbol','date']].drop_duplicates()
    assert pd.to_datetime(probe.date).le('2023-12-31').all()
    sys.path.insert(0,str(ROOT))
    from tools import daily_market_update as updater
    updater.safe_login()
    metadata=[]
    try:
        for row in probe.itertuples():
            code=row.symbol[-2:].lower()+'.'+row.symbol[:6]
            day=pd.Timestamp(row.date)
            end=min(day+pd.Timedelta(days=3),pd.Timestamp('2023-12-31'))
            result=updater.bs.query_history_k_data_plus(code,'date,time,code,open,high,low,close,volume,amount,adjustflag',
                start_date=str(day.date()),end_date=str(end.date()),frequency='5',adjustflag='3')
            frame=updater.result_frame(result,context='pre2024intradaycoverageprobe')
            if len(frame):
                assert pd.to_datetime(frame.date).between(day,end).all()
            target=STORE/f'{row.symbol}_{day.date()}_{end.date()}.parquet'
            STORE.mkdir(parents=True,exist_ok=True)
            assert not target.exists()
            frame.to_parquet(target,index=False)
            metadata.append(dict(symbol=row.symbol,start=str(day.date()),end=str(end.date()),rows=len(frame),frequency='5',adjustflag='3',
                source='BaoStockread-onlyqueryviaunifiedmarkethelper',file=target.name,sha256=sha(target),
                only_pre2024_requested=True,not_tick_or_orderbook_data=True))
    finally:
        updater.bs.logout()
    dump(STORE/'manifest.json',dict(boundary_version='public-pre2025-v2',purpose='Intradaydataavailabilityonly,noreturncomputed',files=metadata))
    dump(OUT/'data_availability.json',dict(local_existing_intraday_files_found=False,provider_5m_probe=metadata,
        exact_first_reopen_not_verified=True,no_new_backtest_results=True))
    print('RulesV2registered; pre2024five-minute probe rowcounts:',[r['rows'] for r in metadata],flush=True)


if __name__=='__main__':
    main()
