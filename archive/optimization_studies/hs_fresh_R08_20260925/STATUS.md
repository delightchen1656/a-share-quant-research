# 持续任务状态

最新终态：第21轮23995 exit0，14配置336开发，冻结P08/P10/P04全期Sharpe0.904932/0.845496/0.871144，均失败，无最终验收/补选。P08年化17.7295%、DD17.8498%、均仓88.8787%；三组未知行动/退市/低50仓位日0。报告、DISPOSITION完整。累计653配置、13880开发窗口、42冻结候选全期，另124诊断与2已知全期对照审计；47单元测试通过。无运行中进程，goal active未达标。

下一方向候选见STAGGERED_RESEARCH_PLAN.md：10万现金分两个/三个独立子账本，错峰双月/季度日历，合并逐日NAV后重算指标，不平均Sharpe；保留真实费用、整手等，需合计容量/T+1/资金守恒测试。尚未实现/回测，不重跑失败21或细扫持股数。开发筛选仍冻结后全期、失败不事后补选，完整普遍性标准不变。

最新：第20轮31590 exit0，8配置192开发均失败，无全期/最终验收；报告及DISPOSITION保存。累计639配置、13544开发窗口、39冻结候选全期，另124诊断与2对照审计；goal active。第20轮新增reference_prices前缀/未来数据测试通过（此前45+1）。不再细调风险均线。

当前活跃：第21轮round21_breadth_retention.py exec session23995，排名和910股票行情面板已装载，继续poll同会话勿重启。14预声明配置详BREADTH_RETENTION_PLAN.md：原carry_long中市值共同双月固定85/95等权，12只2倍buffer两组对照，加16/20/24只×buffer2/3×85/95共12新组合；候选池随最大buffer为72。使用原execution.py（无19/20风险覆盖），原费用与1500门槛/整手/实际仓位限制不变。validate已接入21，test_breadth_retention通过。尚无本轮冻结或全期结果。

最新终态：第19轮2593 exit0，12配置288开发窗口，冻结Y06/Y04/Y02全期Sharpe0.806437/0.908093/0.898325均失败。Y06年化14.8716%、DD15.9953%、均仓77.0991%，额外41风险变化日、488调整订单，总1066订单、费用9449.07；固定95/85精确旧R08/J24。无未知行动/退市/低50仓位日。SCREENING_REPORT及DISPOSITION已保存，无最终验收/补选，无运行中进程。累计631配置、13352开发窗口、39冻结候选全期，另124诊断及2次已知全期对照审计；45测试通过，goal active未达标。

下一可检验假设：广义CSI500风险信号与carry_long中市值实际持仓风格不同。可用第14轮之前已准备的style_price_indices.parquet中carry_mid参考篮子（2019预热、前一日信息、固定12股月度价格篮子，非可实现净收益）作为相同65/95高下限风险触发器，或与CSI500组合。但只是候选方向，尚未写代码/计划/跑新回测；不据此主张能够改善。也可转分散持仓数量/缓冲邻域，注意已知J24多起点诊断失败，不可只冲全期。

当前活跃回测：第19轮exec session2593，45项单元测试全部通过后启动；已输出Y01..Y05开发结果。继续poll2593，不重复启动。没有其他运行中会话。第18轮已完成失败；第19轮尚未完成/未判定达标。

最新：第18轮66968已exit0，24配置576开发全部失败，无全期/最终验证。SCREENING_REPORT、DISPOSITION保存。累计619配置、13064开发窗口、36冻结候选全期，另124诊断窗口。goal active未达标。

新增第19轮round19_daily_risk.py与DAILY_RISK_PLAN.md：12配置carry_long中市值共同双月8/12，只改现有持仓仓位。fixed85/95对照；CSI500前一日60/120MA±1%滞回或60/120滚动峰值回撤-8%减仓/-3%恢复，65/95档位；仅风险状态变化额外按原股票相对权重resize，不换新名单。状态用2018以来历史预热、入场不重置；正常调仓重合时按正常选择流程。保持原费用/1500最小调整/整手/限制，actualexpo仍逐窗验收，未成交不虚构补单。

执行使用独立execution_daily_overlay.py（从原execution.py复制，只新增resize_targets可选参数，原文件未动）。test_daily_risk两项通过（未来/前缀、关闭与原引擎同账本、加减仓不加新票）。audit_daily_risk_control.py已exit0，Y02固定85完整净值/指标精确复现J24 Sharpe0.898325，Y04固定95精确复现R08 Sharpe0.908093；daily_risk_control_audit.json保存。这2次仅已知对照一致性检查，不算新候选验证通过。validate已接入19。当前应按最新exec返回会话继续19，勿重复启动。

当前活跃：第18轮round18_earnings_value.py exec session66968，已完成两项test_earnings_value并开始RANK。共24配置3信号×mid/large×月/双月×8/12，85%等权；validate已接入18且财务版本gate仍False。prepare_earnings_value.py已exit0生成features_earnings_float_value.parquet 4414715行，96.474%代理已知；严格用已选fin_report对应利润，不用最新利润回填。17已完成全期失败，无其他运行中会话。继续poll66968，不重复启动。

第18轮信号已在运行前固定：earnings_proxy纯代理排名；quality_value=0.5代理+0.3原质量+0.2低波；value_pullback=0.5代理+0.3低20日收益+0.2低波。不是实际PE/EP；净利润属全部公司而分母是流通市值估计，存在自由流通比例混杂，必须披露。NBER w24458仅启发新方向，不声称复制论文。无长期空仓、无交易费用放宽。

最新：第17轮session54078 exit0，24配置576开发，冻结W07/W08/W19全期Sharpe0.613468/0.465638/0.673594，全部失败，无最终验收或补选。全期年化13.0683%/9.9639%/13.6732%；W08未知公司行动1，其余0。SCREENING_REPORT及DISPOSITION已写。累计595配置、12488开发窗口、36全期，另124诊断；目标active未达标。

下一方向已先写VALUE_RESEARCH_PLAN.md（NBER w24458盈利价格比研究启发，但本地无完整总股本，不声称论文复现）。新增prepare_earnings_value.py从已选定当时可用年报(fin_report)取归母净利润，除以当时float_cap_proxy，明确仅盈利/流通市值代理，不是实际PE/EP。尚需运行测试及特征准备，再实现第18轮24配置：3信号×mid/large×月/双月×8/12，85%等权原限制；所有财务版本验收阻断继续保留。不拿最新盈利除过去股价。

当前回测进程已确认：第17轮exec session54078，已开始RANK quality all，继续用write_stdin查看同会话，勿重复启动。下载及特征构建已全部完成，没有其他运行中的会话。

最新：199退市财务下载88896已exit0，全部有报告；补充特征构建45750已exit0。新增prepare_complete_financials.py生成features_broad_financials_complete.parquet 4414715行。financial_supplement_validation.json审计：原当前股票4330204行哈希完全不变，实际合格退市股票141只，其中132只有可用年报记录，退市资格样本可用率84.5381%（不是100%），所有已知可用日严格早于signal_date。各年总财务覆盖95.1%—99.1%。第一版有幸存者缺失的文件未覆盖。

补充schema保留EITIME缺失、不伪造；F10仅max公告/更新，批量源另加真实EITIME；41单元测试通过。跨来源882报告对照ROE/利润/收入/EPS/现金及公告更新日全一致，利润同比存在舍入及实质差，第17轮不使用同比。FINANCIAL_SUPPLEMENT_AUDIT.md、financial_source_comparison.json完整。原始版本时点证据仍未认证，validate财务版本gate继续False，不能只凭数字完成goal。

第17轮已准备启动round17_broad_quality.py（24预声明配置，见BROAD_QUALITY_PLAN.md），使用补充完整股票记录版本FEATURES而非旧缺失版本。检查最新exec实际返回session继续，不重复启动。仍571已完成配置、11912已完成开发窗口、33全期；第17轮完成后才更新计数。

当前活跃下载：download_retired_financials.py exec session88896，已确认前8只成功，继续poll同会话，不能重复启动。此前批量下载、特征构建全部终止成功，没有正在运行的回测。第17轮在缺失199退市财务补齐及新特征核验之前未启动。

恢复路径已找到：probe_retired_financials.py exit0，600068/600069/000005逐股F10分别返回104/104/108条报告，说明批量源缺失可通过正常公开逐股接口补齐，不是封禁绕过。新增download_retired_financials.py计划下载199只（复用3份探针缓存），1请求/秒，错误立即停止。需运行并保存实际session。补齐后应创建新特征版本（不覆盖当前有缺失的文件），将F10字段显式映射并记录其没有EITIME、仅max公告/更新的保守近似；不能伪造入库日期。原始版本验收阻断仍保留，不能只补齐条数就认证无未来数据。

重要最新：批量下载84698、特征构建3906均已exit0。2017..2025共203页，features_broad_financials.parquet 4414715行3296历史资格股票；但财务源只覆盖3195当前股票，全部199历史退市股票report_symbols=0、各年retired_known=0，正好全部缺失！这是来源幸存者偏差风险，不能用中性填充后声称规避。round17_broad_quality.py已写24配置和计划但**尚未启动回测**，main增加retired_report_symbols>0防误跑（仅防全缺失，不足以证明覆盖达标）。未来必须补充或更换来源并新版本特征，不能通过简单修改manifest来绕过。

新增prepare_broad_financials.py（严格max公告/更新/入库、900日年报、旧报告晚修订不替代新报告）、test_broad_financials.py四测试；全40测试通过；validate接入17并与16同样保留财务版本未核验阻断。新增probe_retired_financials.py对600068/600069/000005逐股F10接口诊断，原响应存retired_financial_probe，尚需运行。目标继续active；本轮进展是数据覆盖审计发现偏差，而不是策略达标。

当前在跑：download_annual_financials.py exec session84698。首尝F10年度过滤返回filter字段不支持（参数错误，不是访问封禁），已停止该形式。依据本地AKShare stock_yjbb_em源码改用专门批量业绩接口RPT_LICO_FN_CPD，REPORTDATE年度过滤、SECURITY_CODE排序、500条分页；目录public_sources/annual_performance。2017返回9943条20页（含非主板，后续仅匹配原3394历史主板元数据，不把额外市场加入策略）。已下载若干页，需继续poll同会话，不重复启动。各页原响应/URL/SHA保留。

批量源字段与F10不同：REPORTDATE、NOTICE_DATE、UPDATE_DATE、EITIME、WEIGHTAVG_ROE、BASIC_EPS、MGJYXJJE、SJLTZ、TOTAL_OPERATE_INCOME、PARENT_NETPROFIT、XSMLL。未来特征须保守考虑EITIME（抓到000001的UPDATE=2019-03-07但EITIME=2019-04-29），不能误用日期；行业PUBLISHNAME/BOARD_NAME不可作为历史行业。不要直接用round16的字段映射。第16轮报告已生成，36测试通过，无回测仍运行，只有批量下载进行中。所有目标门槛保持不变。

最新：第16轮session73691已exit0，16配置384开发窗口全部失败，无全期。DISPOSITION保存；需调用report_round.py round16_financial_quality生成汇总报告。累计571配置、11912开发窗口、33全期，另124诊断；goal active。最好Q08开发Sharpe0.420533、年化7.1158%。固定98股票池不继续细调，转拓展主板历史财务覆盖。

新增download_annual_financials.py：同一公开财务接口按2017..2025年报分页500条，按SECUCODE排序，缓存原响应和URL/SHA，1请求/秒、任何错误停止不绕过，核查count/页数/每年代码唯一。下载后尚需本地历史主板元数据过滤、缺失覆盖审计、保守更新日特征构建和原始版本限制；不是已通过时点审计的数据库。

当前最新：财务下载session50214已exit0，98只9541条报告、missing=[]；第16轮round16_financial_quality.py正在exec session73691运行，不能重复启动。features_financial_quality.parquet已构建157320行、98股票；可用财务155608行，财报年龄平均627日（保守更新日期导致较滞后），年度覆盖约97.6%—99.7%，没有fin_available>=signal_date。36单元测试全部通过。尚未全期/达标。

第16轮16预声明组合，方法见FINANCIAL_DATA_PLAN.md，代码/三项财务单测已保存，validate.py接入并硬性增加financial_vintage_verified=False，以防当前版本修订数据未经原始公告核验就认证目标。即使本轮数字通过仍需原始报告版本核验与可审计新特征重跑；不得简单改布尔通过。缺失财务填中性排名不删股票；日期严格晚于max公告/更新；900日报告年龄上限、仅年度。后续先等本轮实际结果，再决定拓展全历史主板财务覆盖或取得原公告数据。

最新：第十五轮session14527已exit0，24配置576开发全部失败，无冻结候选/全期；SCREENING_REPORT/DISPOSITION已保存。累计555配置、11528开发窗口、33全期，另124诊断；目标未达成。最高开发V18 Sharpe0.657636、年化8.3604%，不是全期。

公开数据新进展：probe_public_fundamentals.py下载招商银行历史日估值2120条(2018-01-02..2026-09-24)和财务102条。财务有NOTICE_DATE/UPDATE_DATE，发现2019年报NOTICE=2020-03-21、UPDATE=2021-03-20，不能按报告期或首次公告日提前用当前版本。原始响应和URL/SHA已存public_sources/fundamental_probe。不将估值直接用于验收；其历史是否回填修订仍未验证。新增download_historical_financials.py只对预先固定98股票下载财务，1请求/秒、无重试、连续3失败停止，不绕过限制。准备使用严格晚于max(公告,更新)且仅历史年报的质量信号；缺失处理及日期前缀测试尚需实现。

正在运行（最新）：第十五轮round15_historical_dividend.py，exec session14527，已完成排名和V01开发24窗，尚无全期结果，不可宣称达标。24预声明配置×24开发起点：四信号(defensive/barbell/lowvol_reversal/carry_long)×月/双月×8/12/20只，85%等权及原执行限制，固定2019披露98股票池，不分市值。validate.py已接入；test_historical_dividend两项通过。继续用write_stdin检查该会话，不重复启动。

用户授权下载后，已从和讯公开原件链接下载443484字节、46页大成中证红利2019半年报。extract_historical_dividend.py用捆绑Python pypdf读取、pypdfium2渲染1/34/36页并目视核验。public_sources/dividend_holdings_2019.json保存源URL/SHA、2019-08-27披露日及7.3.1全部98指数投资持仓；编号1..98，市值合计1104531453.35与报告7.2.1一致；排除7.3.2七只积极投资股票。不是精确指数成分声明，也不是财务数据库。原件未修改。98只行情全有，本轮157320特征行、无遗漏股票；保留后来退市股，不筛当前生存状态。

最新优先：第十四轮round14_style_adaptation完成36配置×24=864开发窗口，冻结S23/S28/S24全期Sharpe0.6710/0.6399/0.6160，全部失败；不补选、不运行不必要的完整验收。累计531配置、10952开发窗口、33全期，另124诊断窗口。31单元测试通过，无运行中回测，goal active。全期最高仍R08 Sharpe0.9081，但不能作为通过普遍性验收。

新增prepare_style_history.py、round14_style_adaptation.py和两组测试：2019历史资格构造四个12股月度参考篮子，先旧权重当日收益后收盘换股；退市终止损失不丢弃。126/252日风险/动量指标至少126观测且shift1；当前/未来数据不可改变当前评分。4风格top1/2交错选股，实际85%等权、整手可买性。fixed_carry对照精确复现J24。报告与DISPOSITION已完成。

用户确认没有额外本地财务数据，并明确授权下载公开历史数据。下一步探索2019-08-27披露的大成中证红利2019半年报历史完整持仓股票池；来源搜索已找到和讯转载全文及PDF链接，尚未下载解析。不能把2019年报(2020发布)用于2020初，不能用当前成分回填。之后仍按冻结开发/全期/多起点协议，历史报告不等于当前真实行业/估值数据。禁止绕过BaoStock封禁。

最新优先：第十三轮round13_liquidity_universe完成36配置×24=864开发窗口，冻结U03/U04/U32，3全期Sharpe0.6390/0.6792/0.8983，均失败，无后续完整验收/补选。低门槛小市值防守开发较强但全期DD32.59%/29.99%，5000万carry_long对照完整复现J24。各全期未知行动/退市/低50%仓位日0。累计十三轮495配置、10088开发窗口、30全期，另124诊断窗口；无运行中会话，goal active。

新增round13_liquidity_universe.py，使用prepare_lower_liquidity.PATH，3档流动性过滤后重算市值分位，再调用原carry_long/defensive/liquidity，85%等权双月8/12，2xbuffer和60候选/可买性。test_liquidity_universe.py验证50m对照多日期各信号排名和市值组精确一致；总27测试。validate.py接入。audit_capacity.py通用检查保存全期trades与raw当日量额；本轮capacity_audit.json最大股数参与率0.4757%/0.2927%/0.0931%，均<5%，不证明开盘分钟成交能力。报告及DISPOSITION完整。

后续可按STYLE_ADAPTATION_PLAN.md研究过去风格表现驱动的组合结构，尚未实现/回测。需要先审计2019预热：已有features_learning_2019.parquet只是50m基础因子，500万2019及carry_long特征尚未准备。可以按时间正确的价格篮子指数生成风格信号，但不能把信号指数收益当账户收益，必须前日指数决定当天实际账本交易。小风格集和有限参数、无空仓、原筛选验证标准保持。不要重复失败的流动性门槛或权重网格。

最新优先：第十二轮round12_core_neighborhood完成事先限定15配置×24=360开发窗口，冻结N03/N11/N02，3全期年化15.27/12.59/14.62%、Sharpe0.8459/0.6714/0.7847，均失败。各全期未知行动/退市/低50%仓位日均0。报告、DISPOSITION齐全，未补选/未完整验收；停止该评分族细粒度权重搜索。累计十二轮459配置、9224开发窗口、27全期，另124诊断窗口。无运行中进程，goal active。最高全期仍R08的0.908，但J24多起点不合格反证仍有效。

新增round12_core_neighborhood.py、test_core_neighborhood.py，25测试通过；mix433对照在多日期全部前60排名精确复现旧carry_long。validate.py已接入第十二轮。

下一轮数据已实际准备！读LIQUIDITY_UNIVERSE_PLAN.md。prepare_lower_liquidity.py完成，features_historical_5m.parquet与features_liquidity5m_long.parquet共4705860行、3309股票；后者含价格调整代理和长动量。>=5000万子集全体基础字段（除市值组）哈希逐行与features_historical_lowvol.parquet完全一致，manifest记录exact_50m_subset_factor_digest_match=true。不能重跑覆盖。research.py新增MIN_AMOUNT20默认仍50e6，仅该独立缓存构建用5e6，并把值记入新manifest；旧缓存未动。

建议下一轮固定36配置：3成交额门槛5/20/50百万×small/mid×carry_long/defensive/liquidity×8/12只，固定85%等权、共同双月、2xbuffer、60候选、可买性。先过滤每个门槛，再对当时股票池重算float_cap_proxy三分位（按research原floor(rankpct*3)clip2），不能沿用5m全池市值标签。5000万对照应与旧策略等价。所有费用和5%日量上限/T+1/停牌涨跌停/整手保持，不因放宽池子降低成本。候选通过后额外检查成交额占市场日额及成本压力，未知行动仍阻验收。数据范围研究不等于已回测成功。

最新：第十一轮round11_high_floor完成24配置×24=576开发窗口及冻结R08/R04/R12三次全期，均未达标。R08固定95%全期年化18.82%、Sharpe0.908093、DD21.85%、均仓91.91%；R04固定85%精确复现J24（16.80%、0.898325、18.68%、81.83%）；R12均线60/95%为16.07%、0.875574、17.76%、77.59%。各全期未知行动/退市/低50%仓位日均0。不因下调风险改写成功标准，未完整验证/补选。累计十一轮444配置、8864开发窗口、24全期，另124诊断窗口。无运行中会话，goal保持active。

round11_high_floor.py以round09.Study继承，将cfg.exposure改为前一日CSI500风险信息计算的date->target字典；fixed85/95、trend60/65（120MA）、vol12/16（60日波动，60..95%）六模式×月/双月×8/12。只在正常调仓日改变仓位，选股评分不变。test_high_floor.py验证前缀、当日未来不可影响当日、上下限、对照；合计23测试通过。validate.py接入本轮，report_round.py新增仓位规则表。旧原始结果保留。

下一轮按CORE_NEIGHBORHOOD_PLAN.md做严格限定15配置核心评分邻域：carry/longrisk/lowvol权重五组×10/12/14只，中市值、85%等权、共同双月、整手可买性、原费用。不能扩大成细粒度无限网格，必须开发冻结后全期，过关再完整80/44/压力/邻域验收。J24普遍性诊断(80起点Sharpe中位0.746、联合达标0%)不可忽略。若失败应转新信号/数据或组合结构。

最新优先：第十轮round10_cluster_rotation完成48配置×24=1152开发窗口，冻结K24/K27/K23全期分别Sharpe0.8406/0.6593/0.7046，均失败，无后续完整验收/补选。累计十轮420配置、8288开发窗口、21全期，另124诊断窗口。无运行中进程，goal保持active。全期最佳仍J23/J24 Sharpe0.898325。

重要新诊断：diagnose_j24_starts.py已跑完，round09_affordability/start_diagnostic.json和START_DIAGNOSTIC.md完整保存。80共同截止起点：年化中位13.17%、Sharpe中位0.746、联合达标率0%，2020/21/22/23/24入场Sharpe中位0.855/0.780/0.770/0.575/0.605；全部窗口盈利、最低平均仓位77.49%。44完整24月窗口年化中位15.20%、Sharpe0.886、联合达标20.45%，全部盈利。未知行动均0。只是诊断，没有压力/邻域测试，更没有目标达标。不能只看全期略低于1的结果。

round10_cluster_rotation.py实现48组合：8/16统计组×强/回调/冷组×all/mid×月/双月×8/12只，85%等权+可买性。每个当前组至少20合格股票，组均值mom/near_high/ret20/vol60排序，前三组内股票carry_long评分，交错排序60候选，buffer2x保留；没有强制实际组权重上限。test_cluster_rotation.py保证输入顺序不变性和单日截面及交错性，总21测试通过。validate.py已接入；报告及DISPOSITION完整。

接下来按HIGH_FLOOR_RISK_PLAN.md研究固定carry_long中市值核心的高仓位下限风险预算，不重复组别参数穷举。限定CSI500过去60日波动/120日均线及固定85%对照、目标仓位60/65%下限至95%上限，8/12只月/双月；实际每窗平均股票仓位仍>50%，没有长期空仓机制。与旧第三轮区别是不切换股票评分，只调整稳健核心仓位。先冻结协议并写前缀测试，再同样筛选/验证。

最新优先：第九轮round09_affordability已完成32组×24=768开发窗口，冻结J23/J24两次全期完全相同：年化16.7997%、Sharpe0.898325、DD18.6816%、均仓81.8277%、终值274220.93。无低于50%仓位日/未知公司行动/退市核销。仍未达到Sharpe目标；全期必要条件失败，不跑后续完整验收、不补选。累计九轮372组、7136开发窗口、18全期。无运行中会话，goal保持active。

新增round09_affordability.py、test_affordability.py；execution.py增加默认None的SELECTOR_CONTEXT，旧五参数SELECTOR不变，旧引擎快照execution_pre_affordability.py。新接口仅当前开盘价格/当时权益现金及费用信息，不传当天收盘高低/成交量。新策略60候选池与buffer2x旧仓保留分开；等权单股预算内能买一手（含滑点佣金）才选，否则补位。run的finally清理新global。集成单测验证关闭与旧账本净值交易一致、开启补位/现金非负/整手。注意其筛选用于等权配置，不要直接当成风险权重可买性保证。

下一轮分组所需数据已实际准备，不要重跑：prepare_clusters.py生成features_return_clusters.parquet，共3485002行，cluster8/cluster16，54次季度拟合（27季度×两组数），全部max_input_date<fit_date；393539行因季度新合格或不足历史无成员标签，应依预先规则排除/等待下季，不向前填充。训练仅季度当时合格股票的前120日收益、至少115观察、截断±20%、逐股票去均值标准化，MiniBatchKMeans种子20260925、n_init3,batch256,max_iter100,threadlimit1。cluster_preparation_protocol.json/audit.json完整。test_clusters.py未来变动不改变过去分组通过。总19测试通过。

接下来实现分组轮动交易（尚未实现回测！）：可先8/16组×强组/回调组/冷组×月/双月×8/12只，有限配置，85%等权加可买性。考虑组别动量/波动排名与个股carry/lowvol混合，所有聚合仅当天资格和已固定季度标签。不是历史真实行业；不能拿全期聚类回填。仍按24开发起点冻结后全期及完整门槛。也可之后对新的J23/J24附近做有限稳健性邻域，不可把0.898宣布突破1。不要重复已失败阶段。

最新：第八轮round08_long_momentum完成36组×24=864开发窗口，全部未入选，无全期/最终验证。累计八轮340组、6368开发窗口、16全期，仍未达标、goal active；没有正在运行的会话。报告与DISPOSITION已归档。最高开发H30年化中位数14.44%、Sharpe0.776，不是全期结果。原最好全期仍E34 Sharpe0.698。

round08_long_momentum.py生成features_long_momentum.parquet（合并原历史资格+价格调整代理），232日log收益跳20日/252日风险估计与市场beta调整，三信号三市值组月/双月8/12只，共36配置。test_long_momentum.py前缀/最近20日排除/市场复制零残差测试通过，总15测试。validate.py已接入第八轮。

下一方向读取CLUSTER_RESEARCH_PLAN.md：先加默认关闭或隔离的整手预算可买性选择，再做过去相关收益分组轮动。诊断发现H10/H12/H22/H24高价股票导致部分窗口实际仓位<50%（不是现金择时，但仍直接失败）。H12从2020-01-09两年平均仓位44.04%，初始茅台一手108814元，12股预算不足。不能把目标85%当成交85%。本地raw日行情没有PE/PB/财务字段，未找到历史财务缓存，不要凭空构造基本面策略。

最新（优先于所有下方旧状态）：第七轮round07_diversification完成40组×24=960开发窗口及冻结G18/G09/G20三次全期，全部失败（Sharpe0.624/0.510/0.648）。累计七轮304组、5504开发窗口、16全期，目标仍active；无运行中会话。报告及DISPOSITION完整保存，未跑不必要的完整验收，无事后补选。原最好全期仍E34 Sharpe0.698。

round07_diversification.py实现过去120/250日相关性、25%单位阵收缩、48候选、贪心分散+0.15旧仓优先，40配置含原始buffer2x不分散对照；85%目标等权，无空仓机制。test_diversification.py验证未来不影响过去、相关性惩罚和缺失保守处理；总13测试通过。validate.py已接入该轮，report_round.py增加相关性参数表。当前Study读取qfq pct_change，仅在date之前取尾窗；run用execution.SELECTOR并在finally清理。

下一轮建议读取LONG_MOMENTUM_PLAN.md，实施252日长期风险调整/市场残差动量，不重复失败的短期模型或相关性权重微调。当前mom仅120日跳20日，尚未真正研究252日。保持原验收/费用/历史股票池，不以年度诊断事后指定年份规则。所有结果依旧本地近似，不是SuperMind实测。

最新（覆盖下方旧状态）：第六轮round06_learning完成32组×24=768开发窗口，无候选通过开发筛选，未运行全期/最终验证。累计六轮264组、4544开发窗口、13全期，目标仍active且未达成。没有运行中进程。M29是本轮开发Sharpe最高0.570，年化中位数12.08%；不是全期结果。详见round06_learning/SCREENING_REPORT.md和DISPOSITION.md。

学习路线已实际实现并跑完，不要重复：learning_models.py四模型Ridge/浅层LightGBM×5/20标签，每季度严格过去504日、每5日截面训练；108次训练，3485002行预测保存features_learning_predictions.parquet。learning_models/protocol.json、audit.json、complete.json完整。test_learning.py新增成熟标签/未来数据变动不影响过去拟合、周月调仓路由测试，共10项测试通过。validate.py已支持第六轮（本轮无资格候选所以不调用）。

下一轮按DIVERSIFICATION_PLAN.md研究过去相关性约束的组合构建，保持85%目标股票仓位，先冻结有限参数再测试。不能用全历史相关性、未来行业分类，不能把公司行动代理说成真实分红。不覆盖旧研究结果。已有execution.SELECTOR(date,ranked,positions,target_count,buffer_count)接口可实现选择器，但需确保候选都已装载日行情且每次run结束清理全局状态。此前最好E34仍未达到Sharpe目标。

最新完成（优先读此段）：五轮232组、3776开发窗口、13全期均未达标，没有运行中的会话。第三轮round03_calendar_regime完成864窗口，C19/C17全期Sharpe0.352/0.353，失败。第四轮round04_adjustment完成1152窗口，D44全期年化13.20%、Sharpe0.682、DD14.60%、平均仓位82.27%。第五轮round05_adjustment_weights完成864窗口，E34等权双月12只略升至年化13.53%、Sharpe0.698、DD14.65%、平均仓位82.01%，仍失败。各目录SCREENING_REPORT.md和DISPOSITION.md完整保存。原基准不覆盖，goal继续active。

下一轮建议按LEARNING_PLAN.md做严格滚动训练选股，而不继续围着固定权重微调。prepare_learning.py已完成，learning_labels.parquet共3840248行，features_learning_2019.parquet用于2019预热，带target5/20和label_end5/20。仅为监督训练数据，模型尚未训练！训练必须标签已到期且严格过去，特征白名单不得包含未来字段；回测仍2020开始。sklearn/lightgbm可用，xgboost不可用。

本次审计定位B42/B44未知事件均为000970.SZ于2022-02-24配股。见RIGHTS_AUDIT.md及round02_broad_lowvol/unresolved_audit.json；已找到公司发行公告和巨潮发行结果原件。现账本没有参与配股、没有免费补现金/股份，保守承担稀释损失；仅来源核对完成，尚未改掉unknown标志。可后续明确“不参与配股”后标为已解释，但必须净值不变，不能泛化到其他未知事件。

新增代码round03.py（共同日历风格切换）、round04.py（历史原始价格调整代理，不是真实股息数据库）、round05.py（其参数微调）、prepare_learning.py、test_new_rounds.py。研究共8项单元测试通过。validate.py已支持round03/04/05的策略实例，日历策略相邻参数用持股数/缓冲而非无效的interval；最终候选的开发窗口未知公司行动也阻止验收。所有模拟原始结果完整保留。

2026-09-25最新完成：两轮112组、896开发窗口、6全期，均未达目标。没有正在运行的会话。round02_broad_lowvol已完成，冻结B42/B44/B54全期年化5.97%/7.19%/6.02%，Sharpe0.213/0.304/0.195，均失败，见SCREENING_REPORT.md与DISPOSITION.md。B42/B44各有1未知大额公司行动，后续需追踪。原始JSON summary.validation_pending仍true，只表示创建时有候选；DISPOSITION明确全期必要条件失败而剪枝，不算验证通过。

下一目标回合继续开第三轮，不要重复前两轮：建议检查未知公司行动；研究共同日历调仓（降低起点相位依赖）及有下限的市场风险/风格切换，或从原始preclose/close重建历史现金分配代理信号。不能直接把只覆盖当前2803只股票的公司行动账本当作完整历史股息数据库（其199只退市股覆盖为0）；不能凭数据缺失排除退市股后声称无幸存者偏差。若用价格调整代理必须明确命名和限制。执行账本仍可复用，未知大额调整必须阻止成功验收。

rank_cache已按特征内容hash、rank源码hash、市值组、保留条数缓存，可加速后续研究。同一类型maxbuffer40缓存可复用。第三轮任何调参仍先保存协议、只用开发窗口选择，冻结后验证；已反复使用的历史不能伪装独立样本外。目标保持active，不应标记完成。

最新：round01_historical已完成384开发窗口+3全期，F36/F34/F45全期均失败，见该目录DISPOSITION.md。无需为已失败候选运行完整验证，也不改选补位。第二轮运行round02.py（64组，低波动资格下限0.001、12/20只、四信号四市值组），输出round02_broad_lowvol，特征features_historical_lowvol.parquet。若冻结候选全期通过，运行validate.py round02_broad_lowvol。研究目标仍未达成。

目标见PROTOCOL.md。目标未达成，不替换正式策略。

2026-09-25：发现旧缓存不含199只历史退市股票，已停止首次试运行（无任何已完成开发回测结果），保留旧features.parquet及round01/protocol.json作审计。不得使用它们验收。现research.py从3394只历史股票池重算features_historical.parquet，输出round01_historical。使用工作区quant_env的Python。

完成第一轮后：读取round01_historical/summary.json。如果有冻结候选，运行validate.py，完成80个共同截止日起点、完整两年窗口、成本压力和相邻参数检验。不得只按全期Sharpe宣布达标。

若无候选或验证失败，保存失败证据后新增round02研究文件/输出目录，不覆盖round01；继续研究新的信号或结构。不使用当前行业分类回填历史，不以长期空仓抬高Sharpe。

基础数据：复用已缓存原始/复权日线及独立公司行动账本；历史股票池包含199只退市股；从原始日线重建资格和价格/成交量信号，不使用旧资格缓存、月初A评分或分红因子。残留退市持仓保守零估值，不假定可卖出；次数需披露。数据源已知限制须持续披露。

禁止重新尝试被明确限制的BaoStock服务或绕过其访问限制。没有分钟历史，不承诺完全复现SuperMind。
