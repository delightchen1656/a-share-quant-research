import pathlib,json
from account_engine import *
from account_audit import audit_result

def fixtures(n=25):
 cal=pd.bdate_range('2020-01-02',periods=n).strftime('%Y-%m-%d').tolist();bars={'000001':{d:Bar(10,10.2,9.8,10,lower_limit=9,upper_limit=11,limit_evidence='synthetic') for d in cal}};fac={'000001':{d:1. for d in cal}};cov={('000001',2020)};sig=[{'code':'000001','date':cal[0]}];return cal,bars,fac,cov,sig

def run(cal,bars,fac,cov,sig,actions=[],**kw):
 r=run_account(sig,cal,bars,fac,actions,cov,cal[0],cal[-1],policy_verified=True,**kw);audit_result(r,sig,cal);return r
checks=[]
# Fees exact historical switches and lot budget.
assert fee(100000,'2020-01-01',True)['total']==Decimal('132.00')
assert fee(100000,'2024-01-01',True)['total']==Decimal('81.00')
assert fit_shares(50000,10,'2020-01-01')==4900;checks.append('fee_switches_and_lot_budget')
# T+1 and conservative same-day barrier ordering.
a,b,f,c,s=fixtures();b['000001'][a[1]]=Bar(10,13,8,10,lower_limit=9,limit_evidence='synthetic');b['000001'][a[2]]=Bar(10,13,8,10,lower_limit=8,limit_evidence='synthetic')
r=run(a,b,f,c,s,tp=.2,sl=.1);assert r['trades'][0]['sell_date']==a[2] and r['trades'][0]['sell_price']==Decimal('9.00');checks.append('T1_and_SL_before_TP')
# Gap stop cannot fill at favorable stop threshold.
a,b,f,c,s=fixtures();b['000001'][a[2]]=Bar(8,8.5,7.5,8,lower_limit=7,limit_evidence='synthetic');r=run(a,b,f,c,s,sl=.1);assert r['trades'][0]['sell_price']==Decimal('8.00');checks.append('gap_stop_open_price')
# Trailing uses previous close, never current high.
a,b,f,c,s=fixtures();b['000001'][a[2]]=Bar(10,11.9,9.5,11,lower_limit=9,limit_evidence='synthetic');r=run(a,b,f,c,s,tp=.5,sl=.1,trail=True);assert r['trades'][0]['sell_date']==a[3];checks.append('trailing_previous_close_only')
# Stock adjustment changes shares, target; dividend separates ex/payment; taxable amounts explicit.
a,b,f,c,s=fixtures();act=Action('x','000001',a[2],a[3],cash_ps=.1,reserve_ps=1,pay_date=a[5],stock_release_date=a[4],stock_acquisition_date=a[3],taxable_stock_income_ps=0,verified=True,evidence='synthetic')
for d in a[3:]:b['000001'][d]=Bar(4.95,5.1,4.9,4.95,lower_limit=4.5,limit_evidence='synthetic');f['000001'][d]=2.
r=run(a,b,f,c,s,[act],tp=.2,sl=.12,horizon=5);assert r['trades'][0]['sell_qty']==9800;assert r['summary']['economic_pnl_residual']==0;assert r['corporate_actions'][0]['cash_gross']==Decimal('490.00');assert any(x['kind']=='dividend_payment' and x['date']==a[5] for x in r['journal']);checks.append('split_and_dividend_timing_reconciles')
# Locked shares cannot be sold; forced exit delayed until stock release.
a,b,f,c,s=fixtures();act=Action('x','000001',a[2],a[3],reserve_ps=1,stock_release_date=a[8],stock_acquisition_date=a[3],taxable_stock_income_ps=0,verified=True,evidence='synthetic')
for d in a[3:]:b['000001'][d]=Bar(5,5.1,4.9,5,lower_limit=4.5,limit_evidence='synthetic');f['000001'][d]=2.
r=run(a,b,f,c,s,[act],horizon=3);assert r['trades'][0]['sell_date']==a[8];checks.append('stock_release_date_delays_exit')
# Signal due date strictly entry plus H official sessions.
a,b,f,c,s=fixtures();r=run(a,b,f,c,s,horizon=10);assert r['trades'][0]['sell_date']==a[11];checks.append('official_calendar_D0_plus_H')
# Funding chronology: fill all slots, force close; a new same-day opening signal cannot consume close proceeds.
a,b,f,c,s=fixtures();s=[]
for i in range(21):
 code=f'{i+1:06d}';b[code]={d:Bar(10,10.1,9.9,10,lower_limit=9,limit_evidence='synthetic') for d in a};f[code]={d:1. for d in a};c.add((code,2020));s.append({'code':code,'date':a[0] if i<20 else a[2]})
r=run(a,b,f,c,s,horizon=2);assert any(z['code']=='000021' and z['reason']=='slots_full' for z in r['skips']);checks.append('close_proceeds_cannot_fund_same_open')
# Audit cannot silently accept unknown corporate state.
a,b,f,c,s=fixtures();f['000001'][a[2]]=2.
try:run(a,b,f,c,s)
except AuditBlocked as e:assert 'factor change' in str(e)
else:raise AssertionError('Expected unexplained factor block')
checks.append('unexplained_factor_blocks')
# Conditional mode preserves unknown quote assets and labels uncertainty; strict mode still blocks.
a,b,f,c,s=fixtures();del b['000001'][a[2]]
try:run(a,b,f,c,s)
except AuditBlocked as exc:assert 'Unknown quote/status gap' in str(exc)
else:raise AssertionError('Unknown quote incorrectly certified')
r=run(a,b,f,c,s,retain_unknown_quotes=True);assert r['summary']['unresolved_quote_events']>0 and r['summary']['economic_status']=='CONDITIONAL_LAST_MARK_UNPRICED_ASSETS';checks.append('unknown_quotes_retained_and_flagged_never_certified')
# Duplicate supplier rows must not duplicate legal cash or stock entitlements.
from action_adapter import canonicalize_records
base={'dividOperateDate':'2020-01-06','dividRegistDate':'2020-01-03','dividPayDate':'2020-01-06','dividCashPsBeforeTax':'0.2','dividStocksPs':'0','dividReserveToStockPs':'0.2','dividStockMarketDate':'2020-01-07'}
dup={**base,'dividCashPsAfterTax':'0.16'}
can,ca=canonicalize_records({'000001.SZ/2020':[base,dup]});assert len(can)==1 and ca[0]['variants']==1 and not can[0]['conflict'];checks.append('identical_entitlements_merged_despite_tax_note')
zero={**base,'dividCashPsBeforeTax':''};can,ca=canonicalize_records({'000001.SZ/2020':[base,zero]});assert len(can)==1 and can[0]['conflict'];checks.append('conflicting_entitlements_block_without_evidence')
rw=pd.DataFrame({'open':[10,9.8],'high':[10,9.8],'low':[10,9.8],'close':[10,9.8],'preclose':[10,9.8],'volume':[1,1],'tradestatus':[1,1]},index=['2020-01-03','2020-01-06']);qf=pd.DataFrame({'close':[9.8,9.8]},index=rw.index)
base2={**base,'dividReserveToStockPs':'0','dividStockMarketDate':''};zero2={**base2,'dividCashPsBeforeTax':''};can,ca=canonicalize_records({'000001.SZ/2020':[base2,zero2]},{'000001':(rw,qf)});assert not can[0]['conflict'] and can[0]['row']['dividCashPsBeforeTax']=='0.2' and ca[0]['resolution']=='unique_rounded_ex_reference_and_factor_match';checks.append('conflict_resolved_only_by_unique_price_factor_evidence')
pathlib.Path(__file__).with_name('SYNTHETIC_TESTS.json').write_text(json.dumps({'passed':checks,'count':len(checks)},indent=2),encoding='utf-8');print('PASS',len(checks),checks)
