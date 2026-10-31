"""Pre-2025 box-only pattern research: descriptive contrasts plus purged temporal screening."""
from pathlib import Path
import datetime,hashlib,json,math
import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score,roc_auc_score

HERE=Path(__file__).resolve().parent
INPUT=HERE/'inputs_pre2025'
NAMES={
 'decline_return':'前20日下跌幅度','base_return':'横盘首尾涨幅','base_width':'横盘高低宽度',
 'base_volume_ratio':'横盘均量/下跌段均量','signal_volume_ratio':'信号量/横盘均量',
 'base_bull_max_to_signal':'箱内最大阳线量/信号量','base_bear_max_to_signal':'箱内最大阴线量/信号量',
 'base_up_volume_share':'箱内阳线成交量占比','base_up_day_share':'箱内阳线天数占比',
 'base_volume_cv':'箱内成交量变异系数','base_late_volume_ratio':'箱内后7日/前8日均量',
 'base_range_compression':'箱内末5日/首5日价格宽度','signal_body_ratio':'信号实体/振幅',
 'signal_upper_shadow':'信号上影/振幅','signal_return':'信号日收盘涨幅','signal_gap':'信号日开盘跳幅',
 'signal_box_position':'信号收盘相对箱体位置','signal_range_expansion':'信号振幅/箱内日均振幅',
 'dist_ma20':'信号收盘/MA20−1','dist_ma60':'信号收盘/MA60−1','ma20_slope':'MA20近5日变化',
 'ma60_slope':'MA60近10日变化','ma20_ma60_gap':'MA20/MA60−1','pre_return60':'信号前60日涨跌',
 'pre_return120':'信号前120日涨跌','dist_high120':'距此前120日最高价','dist_low120':'距此前120日最低价',
 'atr14_pct':'ATR14/信号价','volatility20':'此前20日日收益波动','base_below_ma60_share':'箱内低于MA60天数占比',
 'log_amount20':'此前20日平均成交额对数','gap_up_count':'箱内向上跳空次数','gap_down_count':'箱内向下跳空次数',
 'gap_unfilled_count':'截至信号日未补缺口数'}
CORE=['decline_return','base_return','base_width','base_volume_ratio','signal_volume_ratio','base_bull_max_to_signal',
      'base_up_volume_share','base_late_volume_ratio','base_range_compression','signal_box_position',
      'signal_range_expansion','dist_ma20','dist_ma60','ma60_slope','pre_return60','pre_return120',
      'dist_high120','atr14_pct','volatility20','log_amount20']
RULE_FEATURES=['base_return','base_width','base_volume_ratio','signal_volume_ratio','base_bull_max_to_signal',
               'base_up_volume_share','dist_ma60','pre_return60','atr14_pct','signal_range_expansion']

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def ratio(a,b):return float(a/b) if np.isfinite(a) and np.isfinite(b) and b!=0 else np.nan
def features(q,r,t):
    # Truncate FIRST. The function cannot consume a future bar even accidentally.
    q=q.iloc[:t+1];r=r.iloc[:t+1];v=pd.to_numeric(r.volume,errors='coerce')
    c=q.close.astype(float);h=q.high.astype(float);l=q.low.astype(float);o=q.open.astype(float)
    base=slice(t-15,t);decl=slice(t-35,t-15)
    b=q.iloc[base];rv=r.iloc[base];bv=v.iloc[base];up=rv.close>rv.open
    span=float(r.high.iloc[t]-r.low.iloc[t]);raw_body=float(r.close.iloc[t]-r.open.iloc[t])
    ma20=c.rolling(20,min_periods=20).mean();ma60=c.rolling(60,min_periods=60).mean()
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    def width(frame):return ratio(frame.high.max(),frame.low.min())-1
    result=dict(decline_return=ratio(c.iloc[t-16],c.iloc[t-36])-1,base_return=ratio(c.iloc[t-1],c.iloc[t-15])-1,
        base_width=width(b),base_volume_ratio=ratio(bv.mean(),v.iloc[decl].mean()),signal_volume_ratio=ratio(v.iloc[t],bv.mean()),
        base_bull_max_to_signal=ratio(bv[up].max() if up.any() else 0,v.iloc[t]),
        base_bear_max_to_signal=ratio(bv[~up].max() if (~up).any() else 0,v.iloc[t]),
        base_up_volume_share=ratio(bv[up].sum(),bv.sum()),base_up_day_share=float(up.mean()),base_volume_cv=ratio(bv.std(),bv.mean()),
        base_late_volume_ratio=ratio(bv.iloc[-7:].mean(),bv.iloc[:8].mean()),base_range_compression=ratio(width(b.iloc[-5:]),width(b.iloc[:5])),
        signal_body_ratio=ratio(raw_body,span),signal_upper_shadow=ratio(r.high.iloc[t]-r.close.iloc[t],span),
        signal_return=ratio(r.close.iloc[t],r.preclose.iloc[t])-1,signal_gap=ratio(r.open.iloc[t],r.preclose.iloc[t])-1,
        signal_box_position=ratio(c.iloc[t]-b.low.min(),b.high.max()-b.low.min()),
        signal_range_expansion=ratio(h.iloc[t]-l.iloc[t],(b.high-b.low).mean()),
        dist_ma20=ratio(c.iloc[t],ma20.iloc[t])-1,dist_ma60=ratio(c.iloc[t],ma60.iloc[t])-1,
        ma20_slope=ratio(ma20.iloc[t],ma20.iloc[t-5])-1,ma60_slope=ratio(ma60.iloc[t],ma60.iloc[t-10])-1,
        ma20_ma60_gap=ratio(ma20.iloc[t],ma60.iloc[t])-1,pre_return60=ratio(c.iloc[t-1],c.iloc[t-61])-1,
        pre_return120=ratio(c.iloc[t-1],c.iloc[t-121])-1,
        dist_high120=ratio(c.iloc[t],h.iloc[max(0,t-120):t].max())-1,
        dist_low120=ratio(c.iloc[t],l.iloc[max(0,t-120):t].min())-1,
        atr14_pct=ratio(tr.iloc[t-13:t+1].mean(),c.iloc[t]),volatility20=float(c.pct_change(fill_method=None).iloc[t-20:t].std()),
        base_below_ma60_share=float((c.iloc[base]<ma60.iloc[base]).mean()),
        log_amount20=float(np.log1p(pd.to_numeric(r.amount,errors='coerce').iloc[t-20:t].mean())))
    gu=gd=unfilled=0
    for j in range(t-14,t):
        if l.iloc[j]>h.iloc[j-1]+1e-8 and r.low.iloc[j]>r.high.iloc[j-1]+1e-8:
            gu+=1;unfilled+=int(l.iloc[j:t+1].min()>h.iloc[j-1]+1e-8)
        if h.iloc[j]<l.iloc[j-1]-1e-8 and r.high.iloc[j]<r.low.iloc[j-1]-1e-8:
            gd+=1;unfilled+=int(h.iloc[j:t+1].max()<l.iloc[j-1]-1e-8)
    result.update(gap_up_count=gu,gap_down_count=gd,gap_unfilled_count=unfilled)
    return {k:float(x) if np.isfinite(x) else np.nan for k,x in result.items()}

def label(q,r,t):
    if t+60>=len(q):return dict(label_status='boundary_purged')
    p=q.iloc[t+1:t+61];raw=r.iloc[t+1:t+61]
    valid=raw.tradestatus.astype(str).eq('1')&pd.to_numeric(raw.volume,errors='coerce').gt(0)
    for col in ['open','high','low','close']:valid &= p[col].gt(0)&np.isfinite(p[col])
    if not valid.all():return dict(label_status='missing_or_suspended_path')
    entry=float(p.open.iloc[0]);peak=float(p.high.max());gain=peak/entry-1
    return dict(label_status='complete',entry_open=entry,peak_gain60=gain,y=int(gain>.60+1e-10),
        label_end=str(p.index[-1].date()),peak_date=str(p.high.idxmax().date()))

def build_table():
    manifest=json.loads((INPUT/'MANIFEST.json').read_text(encoding='utf-8'))
    assert manifest['boundary']=='2024-12-31'
    for name,key in [('events.parquet','events_sha256'),('calendar.parquet','calendar_sha256')]:assert sha(INPUT/name)==manifest[key]
    e=pd.read_parquet(INPUT/'events.parquet');dates=pd.DatetimeIndex(pd.read_parquet(INPUT/'calendar.parquet').date)
    assert dates.max()<=pd.Timestamp('2024-12-31') and e.signal_date.le('2024-12-31').all()
    lookup={(r['code'],r['mode']):r for r in manifest['files']};rows=[]
    for code,group in e.groupby('code'):
        frames={}
        for mode in ['qfq','raw']:
            record=lookup[(code,mode)];path=(INPUT/record['relative_path']).resolve()
            assert path.is_relative_to(INPUT.resolve()) and sha(path)==record['sha256']
            f=pd.read_parquet(path);assert pd.to_datetime(f.date).max()<=dates.max()
            frames[mode]=f.set_index('date').reindex(dates)
            for col in ['open','high','low','close','preclose','volume','amount']:
                if col in frames[mode]:frames[mode][col]=pd.to_numeric(frames[mode][col],errors='coerce')
        q=frames['qfq'];r=frames['raw']
        for event in group.to_dict('records'):
            t=dates.get_loc(pd.Timestamp(event['signal_date']))
            rows.append(dict(event_id=event['event_id'],code=code,name=event['name'],date=event['signal_date'],year=int(event['year']),
                is_leader=bool(event['is_leader']),**features(q,r,t),**label(q,r,t)))
    return pd.DataFrame(rows).sort_values(['date','code']).reset_index(drop=True)

def rules(frame):
    return {
        '横盘收涨':frame.base_return>0,
        '信号量至少1.5倍':frame.signal_volume_ratio>=1.5,
        '横盘收涨且信号量至少1.5倍':(frame.base_return>0)&(frame.signal_volume_ratio>=1.5),
        '箱内阳线最大量超过信号量':frame.base_bull_max_to_signal>1,
        '箱内阳线量占比至少60%':frame.base_up_volume_share>=.6,
        '箱宽不超过8%':frame.base_width<=.08,
        '横盘均量至少下跌段1.5倍':frame.base_volume_ratio>=1.5,
        '收盘在MA20之上':frame.dist_ma20>=0,
        'MA60斜率非负':frame.ma60_slope>=0}

def wilson(k,n):
    if n==0:return 0
    z=1.96;p=k/n
    return (p+z*z/(2*n)-z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)

def fit_rule(train):
    candidates=[];minimum=max(12,math.ceil(len(train)*.15))
    for key in RULE_FEATURES:
        for q in [.2,.4,.6,.8]:
            threshold=float(train[key].quantile(q))
            if not np.isfinite(threshold):continue
            for op in ['>=','<=']:
                mask=train[key].ge(threshold) if op=='>=' else train[key].le(threshold)
                n=int(mask.sum());k=int(train.loc[mask,'y'].sum())
                if n>=minimum and k>=2:candidates.append((wilson(k,n),k,n,key,op,threshold))
    if not candidates:return None
    best=max(candidates,key=lambda x:(x[0],x[1],-x[2]))
    return dict(feature=best[3],op=best[4],threshold=best[5],train_n=best[2],train_hits=best[1],wilson_lower=best[0])
def apply_rule(frame,rule):
    if rule is None:return np.zeros(len(frame),dtype=bool)
    return (frame[rule['feature']].ge(rule['threshold']) if rule['op']=='>=' else frame[rule['feature']].le(rule['threshold'])).to_numpy()

def metrics(y,pick,score=None):
    y=np.asarray(y,dtype=int);pick=np.asarray(pick,dtype=bool);n=len(y);hits=int(y[pick].sum());pos=int(y.sum());selected=int(pick.sum())
    out=dict(n=n,positives=pos,base_rate=pos/n if n else None,selected=selected,hits=hits,
        precision=hits/selected if selected else None,recall=hits/pos if pos else None,missed=pos-hits,
        false_positives=selected-hits,coverage=selected/n if n else None)
    out['lift']=out['precision']/out['base_rate'] if selected and pos else None
    if score is not None and 0<pos<n:
        out.update(average_precision=float(average_precision_score(y,score)),roc_auc=float(roc_auc_score(y,score)))
    return out

def models():
    return {
        'logistic':make_pipeline(SimpleImputer(strategy='median'),StandardScaler(),LogisticRegression(C=.2,class_weight='balanced',max_iter=3000,random_state=17)),
        'boosting':make_pipeline(SimpleImputer(strategy='median'),HistGradientBoostingClassifier(max_iter=80,max_leaf_nodes=4,max_depth=2,min_samples_leaf=20,learning_rate=.05,l2_regularization=10,early_stopping=False,random_state=17))}

def evaluate(train,test,fold):
    rows=[];details={};y=test.y.to_numpy(int)
    for name,mask in rules(test).items():
        details['fixed:'+name]=metrics(y,mask)
        for i,pick in zip(test.index,mask):rows.append(dict(index=int(i),fold=fold,method='fixed:'+name,selected=bool(pick),score=None))
    rule=fit_rule(train);pick=apply_rule(test,rule);details['learned_rule']=dict(metrics=metrics(y,pick),frozen_rule=rule)
    for i,p in zip(test.index,pick):rows.append(dict(index=int(i),fold=fold,method='learned_rule',selected=bool(p),score=None))
    for name,model in models().items():
        model.fit(train[CORE],train.y.astype(int));train_score=model.predict_proba(train[CORE])[:,1]
        threshold=float(np.quantile(train_score,.70));score=model.predict_proba(test[CORE])[:,1];pick=score>=threshold
        details[name]=dict(metrics=metrics(y,pick,score),threshold=threshold)
        for i,p,s in zip(test.index,pick,score):rows.append(dict(index=int(i),fold=fold,method=name,selected=bool(p),score=float(s)))
        if name=='logistic':details[name]['coefficients']=dict(zip(CORE,map(float,model[-1].coef_[0])))
    return rows,details

def contrasts(data):
    result=[];yes=data[data.y.eq(1)];no=data[data.y.eq(0)]
    for key,name in NAMES.items():
        a=yes[key].dropna();b=no[key].dropna()
        if not len(a) or not len(b):continue
        u,p=mannwhitneyu(a,b,alternative='two-sided')
        result.append(dict(feature=key,name=name,positive_median=float(a.median()),other_median=float(b.median()),
            positive_mean=float(a.mean()),other_mean=float(b.mean()),rank_auc=float(u/(len(a)*len(b))),p=float(p)))
    result.sort(key=lambda r:r['p']);m=len(result);last=1.
    for i in range(m-1,-1,-1):last=min(last,result[i]['p']*m/(i+1));result[i]['q_bh']=last
    return result

def main():
    stamp=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%d_%H%M%S')
    out=HERE/'holdout_restricted'/('run_'+stamp);out.mkdir(parents=True)
    spec=dict(boundary='2024-12-31',scope='ALL current mainboard box events; no leader or keep filter',
        target='max adjusted HIGH D1..D60 / adjusted OPEN D1 - 1 > 0.60; full60 valid; no extreme pruning',
        target_type='adjusted PRICE shape label, not cash/share economic return; no split-unadjusted raw exit/entry ratio',
        features=list(NAMES),ml_features=CORE,learned_rule_features=RULE_FEATURES,learned_rule_quantiles=[.2,.4,.6,.8],
        learned_rule_selection='max train-only Wilson lower bound; one condition; n>=max(12,15%train), positives>=2',
        model_hyperparameters='Logistic C=.2 balanced; HGB80iters depth2 leaves4 minleaf20 L2=10 LR=.05; fixed no grid',
        screening_threshold='70th percentile of TRAIN scores; fixed before test; no ranking entire future validation year',
        validation='annual walkforward 2021..2024; train label_end < validation Jan1; min35train and3positives; no random row split',
        frozen_check='train labels mature before 2023 Jan1, then one fixed rule/model evaluated on 2023 and2024 without updating',
        no_read_after2024=True,features_asof='D0 close inclusive; no D1 open / future extreme / peak time / symbol as model features',
        important_limits=['current universe retrospective survivorship','prior outcomes seen; exploratory not fresh blind',
            'overlapping market windows and repeated issuers correlated','many feature contrasts; BH correction; descriptive differences not causal'],
        input_manifest_sha256=sha(INPUT/'MANIFEST.json'),code_sha256=sha(__file__))
    dump(out/'REGISTERED_SPEC.json',spec)
    table=build_table();table.to_parquet(out/'features_and_labels.parquet',index=False)
    data=table[table.label_status.eq('complete')].copy();data['y']=data.y.astype(int)
    assert data.label_end.le('2024-12-31').all()
    summary=dict(total_events=len(table),label_status=table.label_status.value_counts().to_dict(),complete=len(data),positives=int(data.y.sum()),
        base_rate=float(data.y.mean()),stocks=data.code.nunique(),by_year={str(y):dict(n=len(g),positives=int(g.y.sum()),base_rate=float(g.y.mean())) for y,g in data.groupby('year')})
    dump(out/'DESCRIPTIVE.json',dict(summary=summary,contrasts=contrasts(data),
        fixed_rules={key:metrics(data.y,mask) for key,mask in rules(data).items()}))
    data[data.y.eq(1)][['event_id','code','name','date','year','peak_gain60','peak_date','label_end','is_leader']].to_parquet(out/'positive_events.parquet',index=False)
    predictions=[];folds={}
    for year in [2021,2022,2023,2024]:
        start=f'{year}-01-01';train=data[data.label_end.lt(start)];test=data[data.year.eq(year)]
        if len(train)<35 or train.y.sum()<3 or test.empty:folds[str(year)]=dict(skipped=True,train_n=len(train),train_pos=int(train.y.sum()));continue
        rows,detail=evaluate(train,test,str(year));predictions+=rows
        folds[str(year)]=dict(train_n=len(train),train_pos=int(train.y.sum()),train_label_max=train.label_end.max(),test_n=len(test),results=detail)
        print('Evaluated',year,'train',len(train),'test',len(test),flush=True)
    pred=pd.DataFrame(predictions).merge(data.reset_index(names='index')[['index','event_id','code','date','year','y','peak_gain60']],on='index',validate='many_to_one')
    pred.to_parquet(out/'walkforward_predictions.parquet',index=False)
    pooled={}
    for method,g in pred.groupby('method'):
        score=g.score.to_numpy() if g.score.notna().all() else None
        pooled[method]=metrics(g.y,g.selected,score)
    train=data[data.label_end.lt('2023-01-01')];test=data[data.year.ge(2023)]
    rows,frozen=evaluate(train,test,'frozen_before_2023')
    fp=pd.DataFrame(rows).merge(data.reset_index(names='index')[['index','event_id','code','date','year','y','peak_gain60']],on='index',validate='many_to_one')
    fp.to_parquet(out/'frozen_2023_2024_predictions.parquet',index=False)
    frozen_by_year={method:{str(y):metrics(g.y,g.selected,g.score.to_numpy() if g.score.notna().all() else None) for y,g in group.groupby('year')} for method,group in fp.groupby('method')}
    report=dict(summary=summary,walkforward=pooled,folds=folds,frozen_before2023=frozen,frozen_by_year=frozen_by_year,
        frozen_train_n=len(train),frozen_train_positives=int(train.y.sum()))
    dump(out/'RESULTS.json',report)
    (HERE/'holdout_restricted/LATEST.json').write_text(json.dumps(dict(path=str(out),code_sha256=sha(__file__)),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(output=str(out),summary=summary,walkforward=pooled,frozen_before2023={k:v for k,v in frozen.items() if not k.startswith('fixed:')}),ensure_ascii=False,allow_nan=False))

if __name__=='__main__':main()
