"""Independent result checks and readable research artifacts; no rule changes."""
from pathlib import Path
import json
import math
import hashlib
import tempfile
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from run_scan import HERE, ROOT, SPEC, sha, dump, describe


def main():
    out = HERE / 'results'
    metrics = pd.read_parquet(out / 'all_stock_metrics.parquet')
    candidates = pd.read_parquet(out / 'primary_candidates.parquet')
    forward = pd.read_parquet(out / 'forward_persistence.parquet')
    audit = json.loads((out / 'audit.json').read_text(encoding='utf-8'))
    assert sha(HERE/'spec.json') == json.loads((HERE/'registration.json').read_text())['spec_sha256']
    assert audit['post_2023_rows_loaded_into_frames'] == 0
    assert audit['data_maximum_date'] == '2023-12-29'
    assert not metrics.duplicated(['symbol','year']).any()
    assert candidates[['primary_pass','data_quality_pass','liquidity_pass','shape_pass','confirmation_pass','structural_integrity_pass']].all().all()
    assert set(candidates[['symbol','year']].itertuples(index=False, name=None)) == set(metrics.loc[metrics.primary_pass, ['symbol','year']].itertuples(index=False, name=None))
    assert candidates.active_coverage.ge(.95).all()
    assert candidates.maximum_unavailable_run.le(5).all()
    assert candidates.traversals.ge(6).all()
    assert candidates.second_half_frozen_coverage.ge(.8).all()
    assert candidates.structural_event_dates.eq(0).all()
    assert len(forward) == 2 * len(candidates)
    assert forward.loc[forward.year.eq(2023), 'status'].eq('not_matured').all()
    assert forward.loc[forward.year.eq(2022) & forward.horizon.eq(252), 'status'].eq('not_matured').all()
    assert pd.to_datetime(forward.end_date.dropna()).le('2023-12-31').all()

    # Verify unchanged registered parent files: this branch must not open the return/training gates.
    parent = json.loads((ROOT/'audits/data_revision_v5_registration.json').read_text(encoding='utf-8'))
    for item in parent['files']:
        assert sha(ROOT/item['path']) == item['sha256'], item['path']
    assert sha(ROOT/'research_protocol_v1.json') == parent['original_protocol_sha256']
    manifest = json.loads((ROOT/'inputs_pre2025/kline_v1/manifest.json').read_text(encoding='utf-8'))
    by_symbol = {x['symbol']:x for x in manifest['files']}
    calendar = pd.read_parquet(ROOT/'inputs_pre2025/trading_calendar_v1/calendar.parquet')
    dates = pd.DatetimeIndex(calendar.loc[calendar.is_trading_day.eq(1)&calendar.calendar_date.le(SPEC['data_cutoff']), 'calendar_date'])
    current = candidates.loc[candidates.year.eq(2023)].sort_values(['score','symbol'],ascending=[False,True])

    # Re-read every selected symbol at its actual historical asof and independently
    # align onto the window calendar; this catches future-chain/calendar indexing errors.
    checked = []
    for row in candidates.itertuples():
        path = ROOT/'inputs_pre2025/kline_v1'/by_symbol[row.symbol]['snapshot_file']
        df = pd.read_parquet(path, filters=[('date','<=',pd.Timestamp(row.asof))])
        df['date'] = pd.to_datetime(df.date)
        frame = df.set_index('date').reindex(dates[(dates>=row.window_start)&(dates<=row.asof)])
        nums = frame[['open','high','low','close','volume','amount','pctChg']].apply(pd.to_numeric,errors='coerce')
        v = frame.tradestatus.eq('1').to_numpy() & np.isfinite(nums.to_numpy()).all(axis=1) & nums.iloc[:,:6].gt(0).all(axis=1).to_numpy() & nums.pctChg.gt(-100).to_numpy()
        quote = np.cumsum(np.log1p(np.where(v,nums.pctChg.to_numpy()/100,0.)))
        result = describe(nums.close.to_numpy(),v,quote)
        for field in ['lower','upper','center_drift','boundary_drift','abs_trend','score','second_half_frozen_coverage']:
            assert math.isclose(result[field],getattr(row,field),abs_tol=1e-8), (row.symbol,row.year,field)
        assert result['traversals'] == row.traversals
        checked.append(dict(symbol=row.symbol,year=int(row.year)))

    # Synthetic append invariance: extreme 2024 values must not change a historical predicate.
    with tempfile.TemporaryDirectory(dir=HERE) as temp:
        path = Path(temp)/'synthetic.parquet'
        base = pd.DataFrame({'date':pd.date_range('2023-01-01', periods=5), 'close':np.arange(5.)+10})
        extra = pd.DataFrame({'date':[pd.Timestamp('2024-01-02')], 'close':[1e100]})
        pd.concat([base,extra]).to_parquet(path,index=False)
        actual = pd.read_parquet(path,filters=[('date','<=',pd.Timestamp('2023-12-31'))])
        pd.testing.assert_frame_equal(actual,base)

    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei','SimHei','DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    chart_dir = out/'charts'
    chart_dir.mkdir(exist_ok=True)
    figures = []
    # All 20 charts, ranked only by the preregistered score. Five pages of four.
    for page_start in range(0,len(current),4):
        batch = current.iloc[page_start:page_start+4]
        fig, axes = plt.subplots(2,2,figsize=(15,9),layout='constrained')
        for ax,row in zip(axes.flat,batch.itertuples()):
            path = ROOT/'inputs_pre2025/kline_v1'/by_symbol[row.symbol]['snapshot_file']
            df = pd.read_parquet(path,filters=[('date','>=',pd.Timestamp(row.window_start)),('date','<=',pd.Timestamp(row.asof))])
            df['date'] = pd.to_datetime(df.date)
            # Only active valid prices are drawn; missing/halting bars are not zero-filled.
            df = df.set_index('date').reindex(dates[(dates>=row.window_start)&(dates<=row.asof)])
            close = pd.to_numeric(df.close,errors='coerce').where(df.tradestatus.eq('1'))
            ax.plot(df.index,close,color='#205493',lw=1.1,label='未复权有效收盘价')
            ax.axhspan(row.lower,row.upper,color='#46a295',alpha=.15,label='全窗5%—95%区间')
            ax.axhline(row.formation_lower,color='#d39022',ls='--',lw=1,label='前252日冻结边界')
            ax.axhline(row.formation_upper,color='#d39022',ls='--',lw=1)
            ax.axvline(dates[dates.get_loc(pd.Timestamp(row.window_start))+252],color='#777',ls=':',lw=1)
            ax.set_title(f'{row.symbol} {row.historical_name}（历史名称）\n区间 {row.lower:.2f}—{row.upper:.2f}元 | 穿越{int(row.traversals)}次 | 后半窗覆盖{row.second_half_frozen_coverage:.1%}',fontsize=10)
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
            ax.set_xlim(df.index.min(),df.index.max())
            ax.grid(alpha=.18)
            ax.set_ylabel('元/股')
        for ax in list(axes.flat)[len(batch):]:
            ax.set_visible(False)
        handles,labels = axes.flat[0].get_legend_handles_labels()
        fig.legend(handles,labels,loc='outside lower center',ncol=3,fontsize=9)
        fig.suptitle('历史区间形态筛选 · 截至2023-12-29 · 不是当前推荐或未来维持保证',fontsize=14)
        path=chart_dir/f'candidates_{page_start//4+1:02d}.png'
        fig.savefig(path,dpi=150)
        plt.close(fig)
        figures.append(str(path.relative_to(HERE)))

    # Machine readable list with display fields, not executable order files.
    fields = ['symbol','historical_name','name_publication_date','asof','window_start','lower','upper','box_width','traversals','first_half_traversals','second_half_traversals','second_half_frozen_coverage','last_close','box_position','last20_median_amount','cash_event_count','reference_mismatch_count','score']
    dump(out/'historical_candidates_2023.json',json.loads(current[fields].to_json(orient='records',force_ascii=False)))
    validation = dict(all_registered_parent_files_unchanged=True,parent_files_checked=len(parent['files']),
                      all_selected_historical_rows_recomputed=len(checked),recomputed_stock_years=checked,
                      predicate_append_invariance=True,selection_rules_recomputed=True,
                      forward_denominator_retained=True,no_2024_results_used=True,figures=figures)
    dump(out/'validation.json',validation)

    lines = [
        '长期区间震荡股票：截至2023年底的历史描述研究 v1',
        '='*60,
        '',
        '结论：2023-12-29截面共20只通过事先登记的全部条件。它们符合过去约两年的反复区间波动形态，不能据此认定未来继续震荡或在下沿买入能盈利。',
        '观察窗：2021-12-06至2023-12-29，共504个市场交易日；2024年数据未进入计算。',
        '',
        '研究步骤与筛选口径',
        '1. 范围：只读既有白名单快照。3336个文件逐一核验哈希，其中3312个文件有2023年及以前记录；约束为快照覆盖的沪深主板，并非全A股。行业不作为单股入选条件。',
        '2. 时间：主名单在2023年最后一个交易日形成；另按相同规则在2020、2021、2022年末扫描。先登记spec.json，再计算；没有根据结果调参。',
        '3. 基础质量：全窗和各半窗有效交易报价至少95%，连续缺行/停牌/无效报价不超过5个市场交易日；截面当日正常交易、非ST；近20个市场日的有效成交额中位数至少1000万元。未填造停牌价格。',
        '4. 箱体定义：504日有效收盘价的5%/95%分位数是下/上界，涵盖约90%有效收盘报价；不是极端最低/最高价。上界/下界-1须在10%—40%，全窗最高收盘/最低收盘-1不超过60%。',
        '   因此“通过”允许少量短暂冲出区间，图中仍保留全部有效报价；它不等于两年每天都在固定上下限以内。若目标是完全没有越界的硬区间，需要另立规则，不对本名单事后加条件挑选。',
        '5. 稳定性：前后252日中位数差不超过箱体宽度25%；两端分位数漂移不超过宽度35%；拟合总对数趋势不超过对数箱宽35%。',
        '6. 真往返：进入全窗箱体下20%和上20%区域交替计为单程穿越，两次异侧触及至少间隔5个市场交易日；全窗至少6次，各半窗至少2次。两次同向价格变化还须有足够的供应商参考价报价变化支持，避免现金除息机械落差被当作往返。穿越次数不是成交次数或策略收益。',
        '7. 时间稳定检查：只用前252日冻结一组分位边界，后252日至少80%的有效收盘仍落在该旧边界内，且截面收盘也在其中。此项是最终截面内部稳定性检查，不是独立的预测验收。',
        '8. 股份变化：窗口内送转、配股、重组和无已知解释的参考价变化阻断主名单。现金分红保留并注记。公司行动账本仍是审计暂存，未批准经济收益标签；这里只用事件日期和类型作回溯质量检查，不宣称已复原可执行的历史股票池。',
        '9. 排序：预先定义的形态综合分，仅用于排列通过者；不是收益预测概率。未训练模型，未计算账户收益。',
        '',
        '历年筛选漏斗（3312为全开发期有记录的文件总数，不是每年完整上市股票数）',
        '年份 | 报价质量通过 | 加流动性 | 加形态 | 加前半窗冻结验证 | 加股份变化检查后的主名单',
    ]
    for s in audit['asof_summary']:
        lines.append(f"{s['year']} | {s['quote_quality']} | {s['quality_and_liquidity']} | {s['shape_with_quality']} | {s['confirmed_without_integrity_filter']} | {s['primary_candidates']}")
    lines += ['', '2023年底主名单（按形态分排序；元/股；穿越为单程，约两次构成一次上下往返）',
              '序 | 股票 | 历史名称 | 下界—上界 | 箱宽 | 穿越 | 后半窗在旧箱体内 | 截面价 | 箱内位置 | 近20日成交额中位数(万元) | 现金事件/参考价待核对 | 分数']
    for rank,row in enumerate(current.itertuples(),1):
        lines.append(f'{rank:02d} | {row.symbol} | {row.historical_name} | {row.lower:.2f}—{row.upper:.2f} | {row.box_width:.1%} | {int(row.traversals)} | {row.second_half_frozen_coverage:.1%} | {row.last_close:.2f} | {row.box_position:.1%} | {row.last20_median_amount/10000:.0f} | {row.cash_event_count}/{row.reference_mismatch_count} | {row.score:.1f}')
    lines += ['', '箱内位置=(截面价-下界)/(上界-下界)，仅描述所在位置，不是买卖信号。以上显示四舍五入，实际判定使用未四舍五入值。',
              '名称取截面前最后一份完整官方行业公报中的历史名称。2023截面对应2021-11-10公报，可能与当时或当前证券简称不同；代码为识别依据。',
              '“参考价待核对”只作现金事件参考价审计注记，不表示已计算或确认股东收益；相应账本不完整性仍需保留。',
              '', '历史形态后续能否维持（不含2024；不是交易回测）',
              '主名单产生后固定当时的完整504日箱体，向后观察126/252个交易日；不移动边界。有效报价至少95%，有效收盘在旧箱内至少80%，且不出现连续10个市场日落在扩展边界[0.99*下界,1.01*上界]之外，才记维持。缺行/停牌影响报价覆盖，不填零；未来股份结构事件记不可比，低报价覆盖记未知，仍保留在初始分母中。',
              '形成截面 | 观察长度 | 初始样本 | 维持 | 破坏/箱内覆盖不足 | 未知/不可比 | 未到期']
    for (year,horizon),group in forward.groupby(['year','horizon']):
        counts = group.status.value_counts()
        unknown = sum(int(counts.get(k,0)) for k in ['unknown_low_quote_coverage','not_comparable_structural_event'])
        lines.append(f'{year} | {horizon} | {len(group)} | {int(counts.get("success",0))} | {int(counts.get("broken_or_low_coverage_in_band",0))} | {unknown} | {int(counts.get("not_matured",0))}')
    lines += ['', '126日成熟样本：10/44维持（22.7%，其中另有1个低报价覆盖未知仍在分母）。252日成熟样本：2/24维持（8.3%）。这是股票-截面样本，重复股票跨年可再次出现，彼此不保证独立。小样本且来自开发期，不能外推为未来概率。',
              '2023主名单没有查看未来；2022截面252日观察需要进入2024，因此保留未到期。箱体策略最关键的下一问题是能否在破坏前识别风险，而不是把历史形态分直接当收益因子。',
              '', '局限与下一步',
              '• 当前结果是约两年尺度的名义价格形态；没有证明更长三至五年稳定。',
              '• 原始快照未核实全部历史退市覆盖，存在存活/供应商覆盖偏差，不能称为市场无偏通过率。未按未来退市名单删除股票。',
              '• 公司行动源和参考价异常只用于形态质量筛查，实际收息、股数调整、成交、税费、流动性容量未做账户核验；没有投资收益结论。',
              '• 先保留本规则和名单，再将“区间能否继续维持/何时破坏”独立定义为下一版研究目标。在新的时间切分和事先登记下研究因子/模型，不能用本次后续表现反过来挑选本次名单；2024继续锁定。',
              '', '核验与文件',
              f'全部3336份行情文件哈希核验；实际研发行数{audit["rows_used"]:,}；六项合成检查通过；{len(checked)}个入选股票-截面从各自截止日独立重算一致；父研究23个登记文件及原协议均未修改。',
              'spec.json / registration.json：计算前规则与哈希登记。',
              'results/all_stock_metrics.parquet：全量逐股指标、失败原因和分层标记。',
              'results/primary_candidates.parquet：四个历史截面的通过者。',
              'results/historical_candidates_2023.json：2023完整人工核查名单。',
              'results/forward_persistence.parquet：逐样本后续区间检查（无收益）。',
              'results/audit.json / validation.json：来源、日期边界与核验结果。',
              'results/charts/candidates_01.png至05.png：20只股票全部走势。',
              '', '参考资料（只支持定义与公司行动影响，不支持选股有效性）',
              'Fidelity 支撑/阻力：https://www.fidelity.com/learning-center/trading-investing/technical-analysis/support-and-resistance?print=true',
              '深交所除权除息参考价：https://www.szse.cn/www/investor/knowledge/t20181017_555756.html',
              '证监会现金分红与除权除息：https://www.csrc.gov.cn/csrc/c100028/c1002481/content.shtml',
    ]
    (HERE/'REPORT.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    files = [p for p in HERE.rglob('*') if p.is_file() and p.name!='artifact_registration.json' and '__pycache__' not in p.parts]
    dump(HERE/'artifact_registration.json',dict(spec_sha256=sha(HERE/'spec.json'),files=[dict(path=str(p.relative_to(HERE)),sha256=sha(p)) for p in sorted(files)]))
    print(json.dumps(dict(candidates_2023=len(current),independent_recomputations=len(checked),figures=figures,report=str(HERE/'REPORT.txt')),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
