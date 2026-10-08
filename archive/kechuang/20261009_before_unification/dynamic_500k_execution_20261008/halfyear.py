"""Fourteen independent 500k starts using the identical daily proxy."""
import backtest as b
import inspect,json,html
HERE=b.HERE;OUT=HERE/'halfyear_results';p=b.p;s=b.s;np=b.np

def main():
    OUT.mkdir(exist_ok=True)
    # Reuse data/model preparation without re-running or overwriting the prior account.
    src=inspect.getsource(b.main)
    src=src[src.index('    OUT.mkdir'):src.index('    result=executor')]
    env=dict(b.__dict__);env['OUT']=OUT
    exec('def prepare():\n'+src+'    return panels,meta,actions,cand,original_hash\n',env)
    panels,meta,actions,cand,source_hash=env['prepare']()
    engine=inspect.getsource(b.executor).replace("'2020-01-01',END,actions",'START,END,actions')
    rows=[]
    for year in range(2020,2027):
        for month in ['01','07']:
            start=f'{year}-{month}-01'
            scope=dict(b.__dict__);scope.update(START=start,OUT=OUT)
            exec(engine,scope)
            result=scope['executor'](panels,meta,actions)(cand)
            s.save_run(start,result)
            r,c,t,d=result;tx=t[t.side!='WRITE_OFF']
            commission=float(np.maximum(5,tx.amount*.0003).sum())
            stamp=float(tx.loc[tx.side!='BUY','amount'].sum()*.001)
            assert np.isclose(tx.fee.sum(),commission+stamp)
            nav=c.equity.to_numpy()/500000
            assert c.cash.min()>=-.01 and np.isclose(nav[-1]-1,r['total_return'])
            assert np.isclose((nav/np.maximum.accumulate(np.r_[1,nav])[1:]-1).min(),r['max_drawdown'])
            assert tx.loc[tx.side=='BUY','qty'].ge(200).all() and tx.qty.le(50000).all()
            rows.append(dict(r,requested_start=start,commission=commission,stamp_tax=stamp,total_fees=commission+stamp))
            p.save(OUT/'comparison.json',rows)
            print('RESULT',start,r['cagr'],flush=True)
    previous=json.loads((HERE/'backtest_results/summary.json').read_text(encoding='utf-8'))
    for key in ['final_asset','cagr','max_drawdown','sharpe_rf0','avg_exposure','fills','total_fees']:
        assert np.isclose(rows[0][key],previous[key])
    assert p.sha(b.SOURCE)==source_hash
    p.save(OUT/'verification.json',{'passed':True,'accounts':14,'cash':500000,'end':b.END,'prior_full_period_reproduced':True,'source_unchanged':True})
    protocol=json.loads((HERE/'backtest_results/protocol.json').read_text(encoding='utf-8'))
    protocol['starts']=[r['requested_start'] for r in rows];p.save(OUT/'protocol.json',protocol)
    table=[]
    for r in rows:
        vals=[r['requested_start'],f"{r['final_asset']/10000:,.2f}",f"{r['total_return']:.2%}",f"{r['cagr']:.2%}",f"{-r['max_drawdown']:.2%}",f"{r['sharpe_rf0']:.2f}",f"{r['avg_exposure']:.2%}",f"{r['total_fees']:,.2f}"]
        table.append('<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in vals)+'</tr>')
    (HERE/'halfyear_report.html').write_text('<!doctype html><meta charset="utf-8"><style>body{font:16px Microsoft YaHei;margin:32px}td,th{padding:10px;border-bottom:1px solid #ccc;text-align:right}</style><h1>旧模型动态仓位50万元：半年起点对照</h1><p>每组独立空仓投入50万元，不追加；非交易日起点顺延。统一截至2026-09-30，不含10月8日行情。非平台实测。</p><table><tr>'+''.join('<th>'+x+'</th>' for x in ['起点','最终资产万元','累计收益','年化','最大回撤','Sharpe','平均仓位','交易费用元'])+'</tr>'+''.join(table)+'</table><p>费用为佣金与印花税之和，已扣入资产，不含滑点及分红税。继承上次固定税费等近似；Sharpe无风险利率0；不足一年年化仅作换算。旧模型、静态股票池保留。开盘价代理退出，无法模拟订单回报和异常暂停；公司行动处理不同于旧平台状态，不是完整平台复刻。</p>',encoding='utf-8')
    print('COMPLETE',flush=True)

if __name__=='__main__':main()
