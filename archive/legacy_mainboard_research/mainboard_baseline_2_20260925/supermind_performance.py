"""SuperMind documented performance definitions, not execution emulation.
Source: https://quant.10jqka.com.cn/view/help/12, performance section.
An unknown platform risk-free rate MUST NOT silently become zero.
"""
import numpy as np
import pandas as pd

def measure(curve,initial_cash=100000.,risk_free_annual=None):
    q=curve.sort_values('date')
    if q.empty or q.date.duplicated().any():raise ValueError('Daily curve must be nonempty with unique dates')
    equity=np.r_[float(initial_cash),q.equity.to_numpy(float)]
    if not np.isfinite(equity).all() or (equity<=0).any():raise ValueError('Positive finite equity required')
    returns=equity[1:]/equity[:-1]-1
    n=len(returns);annual=(equity[-1]/equity[0])**(250./n)-1
    vol=float(np.std(returns,ddof=0)*np.sqrt(250.))
    rf=None if risk_free_annual is None else float(risk_free_annual)
    if rf is not None and not np.isfinite(rf):raise ValueError('Risk-free rate must be finite')
    return dict(final_equity=float(equity[-1]),total_return=float(equity[-1]/equity[0]-1),
        trading_days=n,annualized=float(annual),volatility=vol,
        drawdown=float((equity/np.maximum.accumulate(equity)-1).min()),
        risk_free_annual=rf,sharpe=float((annual-rf)/vol) if rf is not None and vol>0 else None,
        sharpe_status='platform_rf_missing' if rf is None else ('undefined_zero_volatility' if vol==0 else 'formula_applied_with_supplied_rf'))

def screenshot_rf_bounds(annual_pct=12.91,sharpe=.61,volatility=.18):
    # Display rounding intervals, not a measured Treasury rate or vendor setting.
    a0,a1=(annual_pct-.005)/100,(annual_pct+.005)/100
    s0,s1=sharpe-.005,sharpe+.005;v0,v1=volatility-.005,volatility+.005
    return (a0-s1*v1,a1-s0*v0)
