"""Read-only verification of finished research artifacts and platform behavior."""
import run as r
from datetime import date,timedelta
from types import SimpleNamespace
p=r.p;pd=r.pd;np=r.np

def main():
    lock=p.json.loads((r.OUT/'frozen.json').read_text())
    report=r.verify(lock)
    rows=p.json.loads((r.OUT/'model_selection_2023.json').read_text())
    assert len(rows)==6
    assert all(x['train_max_label_end']<='2022-12-31' for x in rows)
    grid=p.json.loads((r.OUT/'threshold_selection.json').read_text())
    assert len(grid)==9
    best=max([x for x in grid if x['fills']>=20 and np.isfinite(x['sharpe_rf0'])],key=lambda x:(x['sharpe_rf0'],x['cagr']))
    assert best==lock['selected']
    ex=p.json.loads((r.OUT/'export_validation.json').read_text())
    assert max(ex['maximum_probability_errors'])<1e-10
    ns=p.namespace(r.PLATFORM.read_text(encoding='utf-8'))
    # Test actual exported handle_bar -> _place -> order_target_percent sizing.
    orders=[]
    ns['order_target_percent']=lambda symbol,weight:(orders.append((symbol,weight)) or 'order1')
    ns['get_datetime']=lambda:pd.Timestamp('2023-06-30')
    g=ns['g'];g.buy_done_date=None;g.position_state={};g.model={'max_positions':14}
    g.pending=[('688001.SH',.8)];g.order_locks={};g.order_intent={};g.early_events={};g.submitting=False
    ctx=SimpleNamespace(portfolio=SimpleNamespace(positions={},stock_account=SimpleNamespace(total_value=500000,available_cash=500000)))
    bar=SimpleNamespace(open=300,is_paused=False,high_limit=360,low_limit=240)
    ns['handle_bar'](ctx,{'688001.SH':bar})
    assert orders==[('688001.SH',.1212)]
    ns['handle_bar'](ctx,{'688001.SH':bar});assert len(orders)==1
    g.buy_done_date=None;g.order_locks={};g.pending=[('688002.SH',.8)]
    bar.open=500;bar.high_limit=600;bar.low_limit=400
    ns['handle_bar'](ctx,{'688002.SH':bar});assert len(orders)==1
    for stage in ['2020_2022_fit','2024_confirmation','2025_latest','2020_continuous']:
        folder=r.OUT/stage
        curves=pd.read_parquet(folder/'daily_equity.parquet')
        trades=pd.read_parquet(folder/'trades.parquet')
        metrics=p.json.loads((folder/'metrics.json').read_text())
        assert curves.cash.min()>=-.01 and curves.equity.min()>0
        assert np.isclose(metrics['total_return'],curves.equity.iloc[-1]/500000-1)
        assert trades.qty.between(1,50000).all()
        assert trades.loc[trades.side=='BUY','qty'].ge(200).all()
        for (day,symbol),grp in trades.groupby(['date','symbol']):
            assert not ((grp.side=='BUY').any() and (grp.side!='BUY').any()),(day,symbol)
        assert p.json.loads((folder/'unresolved_actions.json').read_text())==[]
    protocol=p.json.loads((r.HERE/'protocol.json').read_text())
    assert all(p.sha(r.Path(f))==h for f,h in protocol['source_hashes'].items())
    report.update(training_label_boundary=True,selection_2023_only=True,prediction_export_parity=True,
        platform_dynamic_order_test=True,once_daily_test=True,over20pct_skipped=True,
        four_stage_account_and_trade_checks=True,originals_unchanged=True)
    p.save(r.OUT/'verification.json',report)
    print(p.json.dumps(report,indent=2))

if __name__=='__main__':main()
