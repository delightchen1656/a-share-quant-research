"""Fixed frontier between inv-IVOL Q3-G7 core and overnight sleeves."""
from pathlib import Path
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;STUDY=HERE.parent;OUT=STUDY/"reports"/"m13_core_overnight_frontier"
FILES={"core":STUDY/"reports"/"m10_position_risk_weighting"/"inv_ivol_curve.parquet","overnight_stable":STUDY/"reports"/"m13_overnight_path_strategies"/"N1_overnight_stable_curve.parquet","overnight_trend":STUDY/"reports"/"m13_overnight_path_strategies"/"N5_overnight_trend_curve.parquet"}
def main():
 OUT.mkdir(parents=True,exist_ok=True);x=None
 for n,p in FILES.items():
  z=pd.read_parquet(p).sort_values("date");q=pd.DataFrame({"date":z.date,n:z.net_nav.pct_change().fillna(0)});x=q if x is None else x.merge(q,on="date")
 x[list(FILES)].corr().to_csv(OUT/"correlation.csv",encoding="utf-8-sig");rows=[]
 for wc in np.arange(0,1.0001,.05):
  for ws in np.arange(0,1-wc+.0001,.05):
   wt=round(1-wc-ws,10);r=wc*x.core+ws*x.overnight_stable+wt*x.overnight_trend;nav=(1+r).cumprod();days=(x.date.iloc[-1]-x.date.iloc[0]).days
   rows.append({"core":wc,"stable":ws,"trend":wt,"annualized_return":nav.iloc[-1]**(365.25/days)-1,"max_drawdown":(nav/nav.cummax()-1).min(),"sharpe":np.sqrt(252)*r.mean()/r.std()})
 out=pd.DataFrame(rows);out.to_csv(OUT/"results.csv",index=False,encoding="utf-8-sig");print(x[list(FILES)].corr().to_string());print(out.nlargest(20,"sharpe").to_string(index=False))
if __name__=="__main__":main()
