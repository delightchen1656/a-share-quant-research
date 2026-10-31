import pathlib,json
from proxy_engine import simulate
O=pathlib.Path(__file__).parent
c={'id':'code_TP8_SL0_H3_PRIOR_BASELINE','rank':'code','tp':.08,'sl':None,'h':3,'trail':False}
r=simulate(c,detail=True);folds=[]
for y in [2022,2023,2024]:folds.append({'year':y,'result':simulate(c,f'{y}-01-01',f'{y}-12-31')})
(O/'PRIOR_BASELINE_PROXY.json').write_text(json.dumps({'status':'PRICE_PATH_PROXY_NOT_ECONOMIC_NET_RETURN','result':r,'folds':folds},indent=2),encoding='utf-8');print(json.dumps({'total':r['total_return'],'dd':r['max_drawdown'],'annual':r['annual'],'n':r['entered'],'exposure':r['avg_exposure']},indent=2))
