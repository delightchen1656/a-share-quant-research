import unittest
import pandas as pd
from round09_affordability import affordable_select

class AffordabilityTests(unittest.TestCase):
    def test_disabled_reproduces_old_engine_and_enabled_fills_lots(self):
        from unittest.mock import patch
        import research as r
        import execution_pre_affordability as old
        dates=pd.bdate_range('2020-01-02',periods=3)
        prepared={d:pd.DataFrame([dict(symbol=s,date=d,open=p,close=p,preclose=p,volume=1e7,tradestatus='1',isST='0') for s,p in [('A',2000.),('B',10.),('C',20.)]]).set_index('symbol') for d in dates}
        ranks={dates[0]:pd.DataFrame(dict(symbol=list('ABC'),downside=[1.,1.,1.]))}
        results=[]
        for engine,enabled in ((old,False),(r.e,False),(r.e,True)):
            changes=dict(CALENDAR=dates,START=dates[0],END=dates[-1],INITIAL_CASH=100000.,PREPARED=prepared,ACTION_MODE='ledger',ACTION_LEDGER={},RECEIVABLES=[],LOCKED_BONUS=[],UNRESOLVED_ACTIONS=[],DELISTINGS={},DELISTING_EVENTS=[],SELECTION_TRACE=[],SELECTOR=None,STRICT_TARGET=True)
            if engine is r.e:changes['SELECTOR_CONTEXT']=affordable_select if enabled else None
            with patch.multiple(engine,**changes):results.append(engine.simulate(ranks,.05,2,4,.85,1.5,min_adjustment=0))
        for n in (0,1):pd.testing.assert_frame_equal(results[0][n],results[1][n])
        curve,trades=results[2]
        self.assertGreater((curve.stock_value/curve.equity).mean(),.8)
        self.assertTrue((curve.cash>=0).all())
        self.assertEqual(set(trades.symbol),{'B','C'})
        self.assertTrue((trades.quantity%100==0).all())

    def test_expensive_stock_does_not_consume_slot(self):
        ranked=pd.DataFrame({'symbol':list('ABCD')})
        context=dict(equity=100000,exposure=.85,lot=100,slippage=.002,commission=.0003,min_commission=5,
            prices=dict(A=2000,B=900,C=10,D=20))
        self.assertEqual(affordable_select(None,ranked,{},2,4,context),['C','D'])
        self.assertEqual(affordable_select(None,ranked,{'A':100,'D':100},2,4,context),['D','C'])
    def test_no_future_input_and_fee_boundary(self):
        ranked=pd.DataFrame({'symbol':['A','B']})
        c=dict(equity=1000,exposure=1,lot=100,slippage=0,commission=0,min_commission=5,prices={'A':10,'B':9})
        self.assertEqual(affordable_select(None,ranked,{},1,2,c),['B'])

if __name__=='__main__':unittest.main()
