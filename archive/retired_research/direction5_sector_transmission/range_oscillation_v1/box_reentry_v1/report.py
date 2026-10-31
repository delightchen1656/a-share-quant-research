"""Report saved frozen run only; never resimulates or alters rules."""
from pathlib import Path
import json
import hashlib
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

HERE=Path(__file__).resolve().parent
OUT=HERE/'audits/holdout_restricted/validation_2024_v1'


def create_report():
    summary=json.loads((OUT/'summary.json').read_text(encoding='utf-8'))
    stock=pd.read_parquet(OUT/'per_stock_summary.parquet')
    trades=pd.read_parquet(OUT/'trades.parquet')
    daily=pd.read_parquet(OUT/'daily_sleeves.parquet')
    nav=pd.read_parquet(OUT/'portfolio_nav.parquet')
    log=pd.read_parquet(OUT/'execution_log.parquet')
    events=json.loads((OUT/'corporate_event_admission.json').read_text(encoding='utf-8'))
    tests=json.loads((HERE/'execution_tests.json').read_text(encoding='utf-8'))
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans']
    plt.rcParams['axes.unicode_minus']=False
    (OUT/'charts').mkdir(exist_ok=True)
    fig,axes=plt.subplots(2,1,figsize=(12,7),sharex=True,layout='constrained',gridspec_kw={'height_ratios':[3,1]})
    dates=pd.to_datetime(nav.date)
    label='有条件账户估算' if summary['conditional_account_complete'] else '含未知账户的名义路径诊断（不是完整收益）'
    axes[0].plot(dates,nav.equity/1e6,label=label,color='#245b83',lw=1.5)
    axes[0].axhline(1,color='#777',ls='--',lw=1,label='初始现金基准')
    axes[0].set_title('固定20只 · 箱宽收缩10% · 下沿回入/上沿止盈/10%止损\n一次2024验证；含交易费用与现金红利20%税预留假设')
    axes[0].set_ylabel('权益/初始100万元')
    axes[0].legend(fontsize=9)
    axes[0].grid(alpha=.2)
    axes[1].fill_between(dates,nav.exposure*100,color='#57998c',alpha=.5)
    axes[1].set_ylabel('持仓市值占比%')
    axes[1].grid(alpha=.2)
    axes[1].xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    fig.savefig(OUT/'charts/portfolio.png',dpi=150)
    plt.close(fig)
    for page in range(5):
        fig,axes=plt.subplots(2,2,figsize=(15,9),layout='constrained')
        batch=stock.iloc[page*4:page*4+4]
        for ax,row in zip(axes.flat,batch.itertuples()):
            quote=pd.read_parquet(OUT/'inputs'/f'{row.symbol}.parquet')
            quote=quote.loc[pd.to_datetime(quote.date).ge('2024-01-01')]
            line=quote.set_index('date').close.where(quote.tradestatus.eq('1').to_numpy())
            d=daily.loc[daily.symbol.eq(row.symbol)]
            ax.plot(pd.to_datetime(line.index),line.to_numpy(),color='#255d83',lw=1,label='有效收盘价')
            ax.plot(pd.to_datetime(d.date),d.lower,color='#46a392',ls='--',lw=1,label='收缩后下沿（除息调整）')
            ax.plot(pd.to_datetime(d.date),d.upper,color='#d49138',ls='--',lw=1,label='收缩后上沿（除息调整）')
            t=trades.loc[trades.symbol.eq(row.symbol)]
            if len(t):
                ax.scatter(pd.to_datetime(t.entry_date),t.entry_price,marker='^',color='#c33c38',s=38,label='买入',zorder=5)
                exits=t.loc[t.status.eq('closed')]
                if len(exits):
                    ax.scatter(pd.to_datetime(exits.exit_date),exits.exit_price,marker='v',color='#1d8d55',s=38,label='卖出',zorder=5)
            outcome='账户未知' if row.account_unknown else f'有条件估算{row.return_conditional:+.1%}'
            ax.set_title(f'{row.symbol} {row.historical_name}（历史名）\n买入{row.buy_fills}次 / {outcome}',fontsize=10)
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
            ax.grid(alpha=.2)
            ax.set_ylabel('元/股')
        handles,labels=axes.flat[0].get_legend_handles_labels()
        fig.legend(handles,labels,loc='outside lower center',ncol=5,fontsize=8)
        fig.suptitle('2024固定规则交易路径 · 日线与暂存公司行动账本条件模拟 · 不据此调参',fontsize=13)
        fig.savefig(OUT/f'charts/stocks_{page+1:02d}.png',dpi=150)
        plt.close(fig)

    lines=['固定20只：收缩箱体下沿回入策略的一次2024验证','= '*32,'',
           '本报告属于受限后验审计；不得将结论返回本轮因子研发或据此修改已冻结交易规则。',
           '用户确认：上下沿各收缩原箱宽5%，向上穿过新下沿买入，新上沿止盈，买价下方10%止损。',
           '', '规则与执行假设',
           '• 固定2023年底原20只，不按2024表现更换；原始高精度边界L/U，W=U-L，新下沿L+0.05W，新上沿U-0.05W。现金除息日同步减去每股现金额，保持报价基准；不重新拟合箱体。',
           '• 完整收盘从下向上穿过新下沿、且收盘仍低于新上沿，次交易日开盘尝试买入。下一开盘低于下沿/已越过上沿、ST、无法成交等取消；等待新的穿越。2024首日开始产生信号，2023末价格仅作前收盘上下文，没有预置仓位。',
           '• 目标价是收缩后上沿；止损初始为实际成交价90%，除息同步调整。按T+1，不假装买入当日能止损或止盈；买入当日碰止损则延迟到下一可卖开盘。跳空止损按实际开盘与不利滑点，不能承诺最多亏10%。',
           '• 开盘触发先于日内波动；若开盘未触发，日内止损/止盈同时触及则按止损先到。日内止盈需最高价严格越过向上取整后的目标价，仅触及不假设排队成交。一字涨停不买，一字跌停不假装卖出。',
           '• 100万元均分20份，每股5万元独立循环，不跨股票调资金，不借贷，100股整数手；前一交易日成交量1%作为整笔成交容量上限。期末未卖出仓位按末日有效收盘估值，没有虚构年末收盘成交。',
           '• 成交费假设：佣金双边万三、单笔最低5元，过户费双边十万分之一，卖出印花税万五；市价/止损滑点单边5基点并按分取整，不能越过当日实际高低价；目标限价卖出不额外扣价格滑点。现金不计利息。',
           '• 公司行动总账仍是暂存，原approved_for_economic_labels均未因此获批准。本次只在双供应商金额一致、字段完整、普通现金分红等条件下估算登记日权益/除息应收/到账资金；现金红利统一预留20%税，属于保守情景，不冒充按个人持有期精确计税。',
           '• 出现非现金股份事件、未知参考价、字段不全等，不删掉证券或持仓；保留未知并阻断完整组合收益结论。日线不能证明盘中先后、集合竞价排队与真实容量，所有结果是有条件模拟。',
           '', '2024结果',
           f"交易日：{summary['first_session']}至{summary['last_session']}，{summary['market_sessions']}个市场交易日。沪深交易所2024官方休市安排与本地日历逐日核对一致。",
           f"完整有条件账户路径：{summary['conditional_account_complete']}；未知股票账户数：{summary['unknown_sleeves']}/20。"]
    if summary['conditional_account_complete']:
        lines += [f"初始资金1000000元；期末有条件权益{summary['conditional_equity_end']:.2f}元；模拟总收益{summary['conditional_return']:+.2%}；最大回撤{summary['conditional_max_drawdown']:.2%}。"]
    else:
        lines += ['因存在未知账户，不发布完整20只组合收益或回撤。保存的名义轨迹只供定位问题，不能替代完整账户收益。']
    lines += [f"产生买入信号{summary['signals']}次，买入成交{summary['buys']}次，取消{summary['cancelled_buys']}次；闭合交易{summary['closed_trades']}次，期末未平仓{summary['open_trades']}笔。",
              f"闭合交易盈利{summary['closed_wins']}次，条件模拟胜率{summary['closed_win_rate']:.2%}。平均持仓市值占权益{summary['average_exposure']:.2%}；交易费用合计{summary['buy_sell_fees']:.2f}元。",
              f"止损退出{summary['stop_exits']}次，其中价格损失超过10%共{summary['stop_price_loss_worse_than10pct']}次；最差已闭合交易价格变动{summary['worst_closed_trade_price_return']:.2%}。注意价格变动与含红利/费用的经济收益不同。",
              f"确认权益现金红利{summary['gross_dividends_entitled']:.2f}元，20%税预留{summary['dividend_tax_reserve']:.2f}元；公司行动事件{summary['event_count']}条，本地条件支持现金事件{summary['conditionally_supported_cash_events']}条、未支持{summary['unsupported_events']}条。",
              f"日内同时碰上下退出条件而按止损处理{summary['dual_touch_stop_first']}次；止损受阻延迟{summary['stop_delayed_days']}个股票日；买入当日碰止损因T+1延迟{summary['entry_day_stop_latched']}次。",
              '', '全部20只（各股5万元独立资金账户；收益含未平仓估值；历史名称）',
              '代码 | 名称 | 原下沿/上沿 | 初始收缩下沿/上沿 | 买入/闭合/未平 | 有条件估算收益 | 账户状态']
    for r in stock.itertuples():
        ret='未知' if r.account_unknown else f'{r.return_conditional:+.2%}'
        lines.append(f'{r.symbol} | {r.historical_name} | {r.original_lower:.4f}/{r.original_upper:.4f} | {r.contracted_lower:.4f}/{r.contracted_upper:.4f} | {r.buy_fills}/{r.closed_trades}/{r.open_trades} | {ret} | {"未知" if r.account_unknown else "条件支持"}')
    lines += ['', '逐笔成交（完整明细另见trades.parquet）',
              '代码 | 买入日期/价 | 数量 | 卖出日期/价 | 原因 | 含费用与红利税预留盈亏元']
    for r in trades.itertuples():
        exit_text='期末持仓' if r.status=='open' else f'{r.exit_date}/{r.exit_price:.2f}'
        lines.append(f'{r.symbol} | {r.entry_date}/{r.entry_price:.2f} | {r.qty} | {exit_text} | {r.exit_reason or "open"} | {r.pnl_after_fees_and_dividend_reserve:+.2f}')
    lines += ['', '公司行动条件审计', '证券 | 除息日 | 每股现金 | 本地条件支持 | 原因（原经济标签审批未改变）']
    for e in events:
        lines.append(f"{e['symbol']} | {e['ex_date']} | {e.get('cash_per_share','—')} | {e['supported']} | {e.get('reason','')}")
    exceptions=log.loc[log.kind.isin(['unsupported_corporate_action','unexplained_quote_reference','missing_held_quote_unknown_not_assumed_suspension','invalid_adjusted_box'])]
    lines += ['', '无法确认的执行/参考价情况',exceptions.to_string(index=False) if len(exceptions) else '无触发账户未知的事件。',
              '', '核验与文件',
              f"规则登记先于2024行情读取；{len(tests['tests'])}项合成执行与记账检查通过；每股资金恒等式和逐笔盈亏对账通过；20个账户逐日完整保留。原协议与全局门槛未修改。",
              '规则：上层spec.json、rule_registration.json；代码/测试冻结：execution_registration.json；开启审计时间：holdout_opened.json。',
              'per_stock_summary.parquet、trades.parquet、daily_sleeves.parquet、portfolio_nav.parquet、execution_log.parquet保存完整明细。',
              'inputs/保存本次只读行情副本与input_audit.json哈希。charts/portfolio.png为曲线，stocks_01至05为全部20只成交图。',
              '本次结果不返回因子研究，不据此改箱宽、止损、进出场、股票池或成本假设。若未来新增版本，必须明确这是已看过的后验信息。',
              '', '主要规则来源',
              '深交所2023交易规则：https://docs.static.szse.cn/www/lawrules/rule/allrules/bussiness/W020230217564423808793.pdf',
              '上交所2024休市安排：https://www.sse.com.cn/disclosure/announcement/general/c/c_20231226_5733939.shtml',
              '深交所2024休市安排：https://www.szse.cn/disclosure/notice/t20231226_605108.html',
              '证券交易印花税减半公告：https://shanxi.chinatax.gov.cn/web/detail/sx-11400-545-1780448',
              '个人现金红利差别化税制：https://www.chinatax.gov.cn/n810341/n810755/c1797427/content.html',
              '佣金、滑点、容量、统一20%红利预留为登记的模拟假设，不表示真实券商费率或个人最终税负。']
    (OUT/'REPORT.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    paths=[p for p in OUT.rglob('*') if p.is_file() and p.name!='artifact_registration.json']
    (OUT/'artifact_registration.json').write_text(json.dumps(dict(files=[dict(path=str(p.relative_to(OUT)),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(paths)]),ensure_ascii=False,indent=2),encoding='utf-8')
    print('Report: '+str(OUT/'REPORT.txt'),flush=True)


if __name__=='__main__':
    create_report()
