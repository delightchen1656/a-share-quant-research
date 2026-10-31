import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from common import AUDIT,BASE,sha,dump,install_development_guard

def main():
    install_development_guard()
    status=json.loads((AUDIT/'DEVELOPMENT_STATUS.json').read_text(encoding='utf-8'))
    assert status['status']=='complete'
    summary=pd.read_parquet(AUDIT/'development_summary.parquet').sort_values(['year','start_date'])
    daily=pd.read_parquet(AUDIT/'development_daily_nav.parquet')
    rows=[]
    for y,g in summary.groupby('year'):
        rows.append(dict(year=int(y),starts=len(g),minimum_return=float(g.account_return.min()),median_return=float(g.account_return.median()),
            maximum_return=float(g.account_return.max()),minimum_drawdown=float(g.maximum_drawdown.min()),maximum_drawdown=float(g.maximum_drawdown.max())))
    overview=pd.DataFrame(rows)
    overview.to_parquet(AUDIT/'development_yearly_overview.parquet',index=False)
    lines=['2019—2023：每年一月全部开市周一起点、独立10万元、到当年年底',
        '固定12因子/池/超参数/交易规则；每年仅以前成熟标签训练，年内不再训练。既有逐年向前评分原样复用。因子选择已观察这些开发年份，不能当作全新独立验证。',
        '一月每个开市周一启动一个独立100000元账户；同年其后每周一开盘买、周二收盘卖；非完整周按已冻结交易日历规则处理，起点不删选。年末未平仓按真实股份/权益估值，不造清仓成交。',
        '双边万三，每只股票每次成交最低5元；加原日期印花税与过户费。零滑点、个人差别化红利税前。',
        '原top10，最多10个持仓，新仓目标信号净值10%，涨停减一档限价下事前定整手量并预留预算；买入失败留现金，无补选。',
        '周二触跌停且日最高价高于跌停，按当日跌停价假设全部已上市股份卖出。全天封死则后续每个交易日重试。日线触板/开板次序和盘口容量不可认证；后续日按跌停价记账可能低于当日最低价，均另行计数。',
        '年内收益以各自一月起点100000元为分母，不是跨年连续收益，也没有将不满一年收益年化。最大回撤用该账户初始资金和每日收盘净值计算。',
        '', '逐年全部起点（收益、收盘最大回撤、期末资金、交易费用合计）']
    for r in summary.itertuples():
        lines.append(f'{r.year} {r.start_date}→{r.end_date} | 收益{r.account_return:+.2%} | 回撤{r.maximum_drawdown:.2%} | 期末{r.end_equity:.2f}元 | 费用{r.fees:.2f}元 | 买入{r.buys}笔 | 未平仓{r.open_trades}笔')
    lines+=['','每年起点分布（只描述全部起点，不选最优）']
    for r in overview.itertuples():lines.append(f'{r.year} {r.starts}起点 | 收益最低/中位/最高：{r.minimum_return:+.2%}/{r.median_return:+.2%}/{r.maximum_return:+.2%} | 回撤范围{r.minimum_drawdown:.2%}—{r.maximum_drawdown:.2%}')
    lines+=['','核验：全部17个账户独立重放现金、上市及未上市股份、应收款；买入事前预算/数量/排名/名额与所有成交费用核验通过。初始10万元整手、最低佣金与期末持仓测试通过。',
        '公司行动：原供应商证据缓存加425组按股票及除权年严格限定到2023年底的公开替代事件查询；实际获得权益的补充事件使用公司公告原文核实支付日及真实权益/虚拟参考系数。未核实的非持有事件日期保持unsupported，不借除权日冒充支付/上市日。持有期间未解决事件和参考变动不得通过。',
        '供应商事件覆盖和正常价格界限为条件核验，不能据此声称历史退市覆盖、全部公司行动经济台账或真实盘口成交完全认证。当前账户的证据和账簿核验通过不改变这些范围限制。',
        '', '执行假设计数']
    for r in summary.itertuples():lines.append(f'{r.start_date} | 跌停开板卖出{r.emergency_fills}笔 | 触板/开板顺序不明{r.ambiguous_order_fills}笔 | 跌停价低于当天最低价{r.floor_below_daily_low_fills}笔 | 期末股票估值{r.end_share_value:.2f} | 应收现金{r.end_cash_receivable:.2f}')
    lines+=['','2024—2026由原独立审计子代理另存后验报告和表图；主代理未读取其行情、业绩或排序，不用于优化。']
    (AUDIT/'DEVELOPMENT_REPORT.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans'];plt.rcParams['axes.unicode_minus']=False
    cells=[]
    for r in summary.itertuples():
        cells.append([str(r.year),r.start_date,f'{r.account_return:+.2%}',f'{r.maximum_drawdown:.2%}',f'{r.end_equity:,.2f}',f'{r.fees:,.2f}',str(r.buys),str(r.open_trades)])
    fig,ax=plt.subplots(figsize=(13.8,10.5));ax.axis('off')
    ax.set_title('2019—2023：一月全部周一起点，独立10万元账户\n每年只用此前数据训练；当年年底停止；全部起点列示',fontsize=17,pad=20)
    table=ax.table(cellText=cells,colLabels=['年份','启动日','账户收益','收盘最大回撤','期末资金（元）','费用合计（元）','买入笔数','未平仓笔数'],
        loc='upper center',cellLoc='center',colWidths=[.06,.13,.115,.14,.16,.16,.105,.105],bbox=[0,.16,1,.80])
    table.auto_set_font_size(False);table.set_fontsize(11)
    for (row,col),cell in table.get_celld().items():
        cell.set_edgecolor('#e1e5ec')
        if row==0:cell.set_facecolor('#1e3858');cell.set_text_props(color='white',weight='bold')
        else:cell.set_facecolor('#f1f5f9' if int(cells[row-1][0])%2 else 'white')
    ax.text(0,.11,'佣金双边万三、逐笔最低5元，另计原日期印花税/过户费；个人红利税前、零滑点。',transform=ax.transAxes,fontsize=11)
    ax.text(0,.07,'日线触跌停后开板按跌停价假设卖出；年末残余权益保留估值。回撤按日收盘净值。',transform=ax.transAxes,fontsize=11)
    ax.text(0,.03,'开发年份已用于因子选择，属于重复开发评估；成交与公司行动估计的条件详见报告。',transform=ax.transAxes,fontsize=10,color='#6b7280')
    fig.tight_layout();fig.savefig(AUDIT/'DEVELOPMENT_RESULTS_FOR_USER.png',dpi=145);plt.close(fig)
    fig,axes=plt.subplots(3,2,figsize=(14,11),layout='constrained');colors=['#166a8f','#b75a3c','#588855','#8c63a1','#d29836']
    for ax,(year,g) in zip(axes.flat,summary.groupby('year')):
        for k,r in enumerate(g.itertuples()):
            d=daily.loc[daily.account_id.eq(r.account_id)]
            ax.plot(pd.to_datetime(d.date),d.equity/100000,label=r.start_date[5:],lw=1.1,color=colors[k])
        ax.set_title(str(year));ax.set_ylabel('账户净值（初始=1）');ax.legend(title='一月起点',fontsize=8);ax.grid(alpha=.2)
    axes.flat[-1].axis('off')
    axes.flat[-1].text(.02,.8,'每条曲线为独立10万元账户\n每年年初过去数据训练，年内不变\n不跨年接续资金，不按收益挑起点\n交易费用后、个人红利税前\n日线成交近似，收盘净值',fontsize=14,linespacing=1.8)
    fig.suptitle('每年不同一月起点的账户净值',fontsize=18)
    fig.savefig(AUDIT/'DEVELOPMENT_ACCOUNT_CURVES.png',dpi=140);plt.close(fig)
    dump(AUDIT/'DEVELOPMENT_ARTIFACTS.json',dict(status='complete',no_posterior_read=True,
        source_engine_manifest_sha256=sha(AUDIT/'frozen_engine_v1/FREEZE_MANIFEST.json'),
        files=[dict(path=p.name,sha256=sha(p)) for p in sorted(AUDIT.iterdir()) if p.is_file() and p.name!='DEVELOPMENT_ARTIFACTS.json']))
    print('Development report and complete start-date figures saved.',flush=True)

if __name__=='__main__':main()
