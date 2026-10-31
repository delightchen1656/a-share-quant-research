"""Register research execution rules, without reading posterior results or placing orders."""
from pathlib import Path
import datetime
import hashlib
import json

BASE=Path(__file__).resolve().parent.parent
FROZEN=BASE/'audits/holdout_restricted/monday_factor_v5/frozen_exploratory_requested_v1'
OUT=BASE/'audits/holdout_restricted/monday_trading_rules_v1'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write_json(path,data):
    Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def main():
    assert sha(FROZEN/'FREEZE_MANIFEST.json')=='81d0ea7fd52dee7722b9522e82de61c1cb2c7a9f19f5648993f8cf6910e17e25'
    manifest=json.loads((FROZEN/'FREEZE_MANIFEST.json').read_text(encoding='utf-8'))
    for row in manifest['files']:
        assert sha(FROZEN/row['path'])==row['sha256']
    protocol=json.loads((FROZEN/'protocol.json').read_text(encoding='utf-8'))
    OUT.mkdir(parents=True,exist_ok=True)
    assert not (OUT/'RULES.json').exists(),'Never overwrite a registered execution rule version'
    source_sse='https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml'
    source_szse='https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf'
    rules=dict(
        id='Monday_model_timed_exit_execution_rules_v1',
        status='Research/paper-trading specification only; not backtested account performance, not connected to broker or production.',
        authorization='User asks for buy/sell rules based on the latest11factor-plus120day-momentum selection. No authorization to place orders inferred.',
        model=dict(variant='combine__long_momentum',path=str(FROZEN.relative_to(BASE)/'candidate.joblib'),
            freeze_manifest_sha256=sha(FROZEN/'FREEZE_MANIFEST.json'),model_sha256=sha(FROZEN/'candidate.joblib'),
            features=protocol['ordered_candidate_features'],training_end='2023-12-31',retrain=False,
            designation='Exploratory factor candidate; prior development upgrade failure is unchanged by creation of execution rules.'),
        data_boundary='No posterior quote/label/result/report/image reads used to design these rules. Future rule research uses only registered development whitelist; subsequent audits remain one-way.',
        signal=dict(asof='Last actual exchange session close strictly before scheduled Monday, usually Friday; no Monday daily data in score.',
            pool=dict(prefixes=protocol['data_prefixes'],active=True,nonST=True,close_min_cny=3.,valid_observed_bars_min=120,
                last20_quote_coverage_min=.9,last20_median_amount_min_cny=20000000),
            preprocess='Original signal-date peer percentile ranks; frozen train medians, scaler and model.',
            ranking='Score descending, symbol ascending for ties.',top_n=10,score_threshold=None,
            save='Signal timestamp, full pool and scores,top10, source/model hashes, mark-to-market NAV and cash before any entry.'),
        schedule=dict(timezone='Asia/Shanghai',entry_weekday='Monday',entry_phase='Opening call auction09:15-09:25',
            exit_weekday='Tuesday',exit_phase='Closing call auction14:57-15:00',
            closed_endpoint_policy='For new entries, if either scheduled Monday or Tuesday is closed, skip whole week. No weekday shift or Friday entry.',
            old_position_exit='Existing carry positions may attempt exit on every actual open Tuesday even if that week has no new entry.'),
        capital=dict(initial_cash_is_parameter=True,research_example_initial_cash_cny=1000000,
            maximum_open_symbols=10,new_position_budget_fraction_of_signal_NAV=.10,total_cash_debit_must_be_nonnegative=True,
            leverage=False,short=False,idle_cash_return=0,
            old_positions_count_towards_limit=True,add_to_existing_position=False,
            selection='From originaltop10, in rank order, take unheld symbols up to remaining position slots; no names outside originaltop10.',
            failed_buy='Leave its budget in cash; no replacement stock, no redistribution, no continuous-session chasing.',
            budget='min(0.10*signal_NAV, remaining unreserved spendable cash). Receivables and unlisted shares are not spendable cash.'),
        buy=dict(order_type='Limit order intended only for Monday opening auction; broker validity and cancellation mechanics require separate execution verification.',
            legal_price_source='Historical date/security-specific official price bands/tick and ex-right reference, or live broker/exchange fields. Never universally hardcode10%/5%for every date.',
            pre_entry_checks='Still nonST, trade-enabled, correct session, known valid upper band and tick, reconciled cash, no duplicate held name.',
            limit_price='Verified upper price limit minus one minimum price tick; if invalid/unavailable, skip new entry.',
            quantity='Largest nonnegative100share multiple q with q*limit_price+estimated_buy_fees(q*limit_price)<=budget; set before final opening auction price is known.',
            capacity_fraction_of_previous_session_volume=.01,
            capacity_policy='If full intended order exceeds registered capacity cap, cancel that symbol rather than filling a later-ranked replacement.',
            no_quantity_recalc_from_final_open=True,
            execution='Actual broker reports determine fills, including partial fills. Daily open-price replay is only a conditional quote proxy, not proof of an auction fill.',
            unfilled='Request cancellation of all residuals; require confirmation. Residuals can persist into continuous trading, so absence of auction-only broker controls cannot be called strict opening-only execution.'),
        holding=dict(normal_exit='Hold until scheduled Tuesday closing auction, then attempt full exit irrespective of profit/loss or new model rank.',
            intraday_take_profit=None,intraday_stop_loss=None,averaging_down=False,extra_entry=False,
            rationale='Preserve the trained MondayOpen-TuesdayClose target. New stop or take-profit variants need separate registration and suitable intraday data; this rule version has not evaluated them.'),
        sell=dict(order_type='Limit sell submitted after Tuesday closing call auction starts, using actual listed and legally sellable quantity.',
            limit_price='Verified lower price limit plus one minimum tick; actual execution at matched price, if any.',
            intent='Sell all available shares; include small residual shares using the applicable exchange declaration rules.',
            capacity_fraction_of_previous_session_volume=.01,
            capacity_policy='Daily quote proxy conservatively rejects a whole exit attempt above capacity cap; real partial fills are retained exactly and the remaining shares stay held.',
            failure='Lower-limit/no-depth, suspension, missing verified tradability or unlisted shares: do not invent an exit; retain actual shares, risk and occupied capital.',
            retry='Next actual open Tuesday closing auction only; if closed, next open Tuesday. Never silently shift to Wednesday.',
            terminal='Open positions/receivables at sample end remain marked and disclosed, not forced closed or removed.'),
        accounting=dict(prices='Execution reports for any broker simulation; gross daily OHLC quotes only as explicitly conditional historical proxy.',
            fees='Use each trade date applicable stamp/transfer schedule plus actual or explicitly assumed brokerage commission. Avoid double counting bundled regulatory fees.',
            paper_commission_each_side=.0003,paper_minimum_commission_cny=5,
            paper_slippage=0,slippage_note='Zero slippage retains prior research assumption; actual auction prices and depth are not guaranteed.',
            corporate_actions='Record-date rights, ex-date quantity/receivable recognition, payment-date cash and stock-listing-date sellability tracked separately; do not assume an unverified empty action ledger complete.',
            dividends='Keep gross shareholder distributions and individual dividend withholding separately; do not claim full personal after-tax PnL unless verified.',
            missing_held_quotes='Do not assume a missing row is suspension or delete the holding; mark account state unresolved until verified.',
            evidence='Daily cash/listed shares/unlisted shares/cash receivables/NAV; orders/fills/cancel acknowledgements/delayed exits; cash and share reconciliation.'),
        comparison_to_signal_study='New causal pre-auction sizing and actual execution constraints differ from idealized open-price-sized signal statistics. Existing signal/postperiod means do not certify this rule account return.',
        next_validation_scope='Rules registered before any new account backtest. Evaluate execution and accounting on allowed development years first; do not optimize rules using prior posterior results.',
        references=[dict(title='上交所交易规则（2026年修订）发布页',url=source_sse),dict(title='深交所交易规则（2026年修订）原文',url=source_szse)],
        deployment=False)
    write_json(OUT/'RULES.json',rules)
    text='''周一模型选股：买卖规则 V1（研究/仿真版）

绑定模型
采用已冻结的“11因子＋120日动量”探索模型，不改因子、不重训，也不因后验好坏更换规则。本次未读取后验报告、图表或收益数据。创建交易规则不改变它尚未通过开发升级门槛的事实。

1. 什么时候选
在周一之前最后一个实际交易日收盘后评分，通常为周五收盘。只用截至该时点的K线，按冻结的横截面排名、训练中位数、标准化器和模型处理；模型分数由高到低，平分按股票代码排序，固定取前10只。分数没有另加人为阈值。
股票池沿用：沪深主板既定代码范围，信号时正常交易且非ST，价格至少3元，至少120条有效观测，近20日有效报价覆盖至少90%，近20日成交额中位数至少2000万元。120条是观测资格，不冒充真实上市年龄。

2. 什么时候买
仅周一开盘集合竞价参与买入，目标是该阶段实际成交；本版不在周五买入。周一或周二任一端点休市，该周不建立新仓，不顺延日期。
保留原top10名单。旧持仓也占10只名额，不重复加仓；剩余名额按top10内未持有股票的排名依次分配。买入失败留现金，不补第11名，不盘中追补，不把失败预算重新分给其他股。

3. 买多少
最多10只。每笔新仓的费用内预算为“信号日净值的10%”与“尚未预留的可用现金”的较小值。示例资金100万元时，每只新仓预算上限10万元；全部委托连同费用都必须有现金覆盖，不融资。
这是新仓预算，不是保证每只实际成交后都精确10%：整手、限价、费用、旧持仓和未成交都会造成差异。旧仓随价格漂移也不会被假装再平衡。

4. 委托价格与数量
委托前取得该证券当日合法涨停价、跌停价、最小报价单位及除权参考，缺失或不适用则跳过新买入，不把所有时期统一套10%/5%。买入限价=合法涨停价减一个最小报价单位；用此限价计算最大可负担100股整数倍，费用也计入预算。不得先看最终开盘价、再声称预先下出了相应股数。
新买入前再次确认非ST、可交易、无同名旧仓、资金与股份可核对。单笔计划买入量不超过前一实际交易日成交量的1%；超限则整笔不买，仍不换候补股。
真实执行以券商成交回报为准。残单须请求撤销并等待确认；集合竞价结束后残单可能继续进入连续竞价，券商不具备对应委托时效控制时，不能声称严格只在开盘成交。
只有日K线时，可以做有条件的开盘报价代理，但它不证明集合竞价有足够深度或已成交。开盘价也可能由连续竞价形成。

5. 持有与退出
普通持仓统一持有到周二收盘集合竞价，无论当时盈亏或新排名，尝试卖出全部可卖股份。本版不加盘中止盈/止损、不补仓摊薄。这样保留模型原先研究的周一开盘至周二收盘目标；若以后测试止盈止损，应另立版本与数据要求。
周二14:57进入收盘集合竞价后申报，限价=当日合法跌停价加一个最小报价单位；以实际成交回报记账，不保证成交在收盘价或一定成交。股份须真实可卖，未上市红股不得卖。
日K代理按原研究保守容量约束核验：整笔卖出量超过前交易日量1%时不假设整笔可退出。实际部分成交则按真实数量减少持仓，剩余部分继续保留。

6. 卖不掉怎么办
遇跌停、停牌、缺乏成交对手、股份未上市或状态未核实，不虚构卖出。剩余仓位及占用资金留在账上，下一实际开市的周二收盘继续尝试；周二休市则等下一开市周二。已有旧仓的退出不因该周没有新买入而取消。
下一周一仅使用空闲名额和真实可用现金；旧仓不因跌出新名单就从账上消失。因此这是“只在周一/周二操作”的规则，无法保证所有仓位都只承受两天风险。

7. 费用与公司行动
回测必须扣对应日期的佣金、最低佣金、过户及印花税。佣金研究示例沿用双边万三、最低5元；真实券商费率和是否已含规费需分别记录，避免重复计费。滑点0只是此前研究假设，不代表真实集合竞价没有执行差异。
登记日、除权日、现金支付日、红股上市日分别记账；应收股息和未上市股份不能当作可用现金。遇未核实公司行动或持仓报价缺失，标记记账不完整，不用空表或删除持仓掩盖。

8. 如何验收
这份文件只定义规则，没有新增账户回测或实盘部署。下一步先在允许开发数据内核验成交假设、股份/现金与费用，再比较完整账户净值、回撤、失败订单、延迟退出及资金占用。已有的信号平均收益不能直接替代该规则的账户收益；本次没有把后验表现反馈进规则设计。

官方交易制度核对
沪深现行规则的开盘集合竞价阶段为09:15—09:25，收盘集合竞价阶段为14:57—15:00；相应竞价阶段存在撤单限制，买入主板证券通常以100股整数倍申报。具体证券、日期、委托时效和例外以交易所及券商真实规则为准，历史回测不得把现行制度倒灌历史。
上交所：SOURCE_SSE
深交所：SOURCE_SZSE

附：RULES.json为同一版本的结构化配置；REGISTRATION.json记录冻结模型与本规则文件哈希。未连接券商，不下单，不改任何生产基线。
'''.replace('SOURCE_SSE',source_sse).replace('SOURCE_SZSE',source_szse)
    (OUT/'RULES.txt').write_text(text,encoding='utf-8')
    write_json(OUT/'REGISTRATION.json',dict(registered_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        before_execution_backtest_or_broker_deployment=True,posterior_results_not_read=True,
        frozen_factor_model_unchanged=True,
        model_manifest_sha256=sha(FROZEN/'FREEZE_MANIFEST.json'),
        files=[dict(path=str(p.relative_to(BASE)),sha256=sha(p)) for p in [OUT/'RULES.json',OUT/'RULES.txt',Path(__file__)]],
        sources_checked_client_date='2026-10-27'))
    assert rules['signal']['top_n']==rules['capital']['maximum_open_symbols']==10
    assert rules['holding']['intraday_stop_loss'] is None and rules['holding']['intraday_take_profit'] is None
    assert len(rules['model']['features'])==12 and rules['model']['features'][-1]=='momentum120'
    print('RULES:',OUT/'RULES.txt',flush=True)
    print('CONFIG:',OUT/'RULES.json',flush=True)
    print('Registration and model binding verified; no market/performance data read.',flush=True)


if __name__=='__main__':
    main()
