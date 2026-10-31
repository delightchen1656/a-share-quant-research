from pathlib import Path
import math
import numpy as np
from common import AUDIT,dump,fee,sha
from execution import buy_order,sell_order,entitlement,ordinary_label


def main():
    checks={}
    assert math.isclose(fee(100000,'sell','2023-08-25'),131.)
    assert math.isclose(fee(100000,'sell','2023-08-28'),81.)
    assert math.isclose(fee(100000,'buy','2022-04-28'),32.)
    assert math.isclose(fee(100000,'buy','2022-04-29'),31.)
    assert math.isclose(fee(1000,'buy','2023-01-03'),5.01)
    checks['historical_fees_and_minimum']=True
    bar=dict(active=True,st=False,open=10.,close=10.2,preclose=10.,volume=1e7,amount=1e8)
    fill,why=buy_order(bar,100000,100000,1e7,'2021-01-04')
    assert fill['qty']==9900 and fill['notional']+fill['fee']<=100000 and why is None
    checks['roundlots_and_cash_debit']=True
    b=dict(bar,open=11.)
    assert buy_order(b,100000,100000,1e7,'2021-01-04')[0] is None
    assert buy_order(dict(bar,st=True),100000,100000,1e7,'2021-01-04')[0] is None
    assert buy_order(bar,100000,100000,100,'2021-01-04')[0] is None
    checks['opening_limit_ST_prior_volume']=True
    assert sell_order(bar,9900,'2021-01-04',1e7,'2021-01-04')[0] is None
    assert sell_order(bar,9900,'2021-01-04',1e7,'2021-01-06')[0] is None
    assert sell_order(dict(bar,close=9.),9900,'2021-01-04',1e7,'2021-01-05')[0] is None
    assert sell_order(dict(bar,active=False),9900,'2021-01-04',1e7,'2021-01-05')[0] is None
    assert sell_order(bar,9900,'2021-01-04',1e7,'2021-01-12')[0] is not None
    checks['Tplus1_Tuesday_only_delayed_exit']=True
    e=entitlement(1000,.1,1.,0.)
    assert e==dict(cash=100.,extra_shares=1000)
    assert math.isclose(((1000+e['extra_shares'])*5.5+e['cash'])/10000-1,.11)
    checks['split_cash_economic_unit_vs_wrong_raw_per_share_return']=True
    try:
        entitlement(101,.1,.03,0.)
        raise AssertionError('unverified fractional entitlement must fail')
    except ValueError:
        pass
    checks['fractional_share_unknown_not_fabricated']=True
    assert np.isnan(ordinary_label(10,5.5,True,True,10,5.,0))
    assert np.isnan(ordinary_label(10,11,True,False,10,10,0))
    assert math.isclose(ordinary_label(10,11,True,True,10,10,.03),.07)
    checks['corporate_and_missing_quote_labels_unknown']=True
    # An unpaid entitlement is not included in the spendable-cash argument.
    assert buy_order(bar,100000,0,1e7,'2021-01-04')[0] is None
    checks['receivable_not_spendable_cash']=True
    dump(AUDIT/'minimum_execution_checks.json',dict(passed=True,checks=checks,execution_code_sha256=sha(Path(__file__).parent/'execution.py')))
    print(checks)


if __name__=='__main__':
    main()
