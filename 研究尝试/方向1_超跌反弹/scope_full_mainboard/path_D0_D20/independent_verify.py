"""Independent adjusted-price path reference. No accounts or economic ledger."""
import argparse,json,math
from pathlib import Path

def finite(v):
    try:return math.isfinite(float(v))
    except (TypeError,ValueError):return False

def known(v):return v is not None and finite(v)

def reference_path(calendar,signal_date,raw,qfq=None,anchor_valid=True,blocked_days=None,unexplained_days=None,horizon=20):
    """Independent official-session reference, explicit qfq denominator.

    Raw is used as qfq only for synthetic no-action tests. Confirmed suspension
    contributes no new traded high, while an unknown high blocks the prefix.
    Blocker sets are explicit action/reference decisions, never account state.
    """
    qfq=raw if qfq is None else qfq;blocked_days=set(blocked_days or []);unexplained_days=set(unexplained_days or [])
    start=calendar.index(signal_date)+1;entry_day=calendar[start] if start<len(calendar) else None
    entry=raw.get(entry_day,{});qe=qfq.get(entry_day,{})
    eligible=anchor_valid and entry.get('tradestatus') in [1,'1'] and finite(entry.get('volume')) and float(entry['volume'])>0 and finite(entry.get('open')) and float(entry['open'])>0 and finite(qe.get('open')) and float(qe['open'])>0
    anchor=float(qe['open']) if eligible else None
    out=[];prefix_unknown=False;prefix_suspended=False;running=None
    for offset in range(horizon+1):
        index=start+offset;day=calendar[index] if index<len(calendar) else None
        r=raw.get(day,{}) if day is not None else {};q=qfq.get(day,{}) if day is not None else {}
        high=None;close=None;cum=None;suspended=False
        if day is None:reason='right_censored'
        else:
            suspended=r.get('tradestatus') in [0,'0'] or (finite(r.get('volume')) and float(r['volume'])==0)
            active=r.get('tradestatus') in [1,'1'] and finite(r.get('volume')) and float(r['volume'])>0
            goodhigh=active and finite(r.get('high')) and float(r['high'])>0 and finite(q.get('high')) and float(q['high'])>0
            goodclose=active and finite(r.get('close')) and float(r['close'])>0 and finite(q.get('close')) and float(q['close'])>0
            prefix_unknown|=(not suspended and not goodhigh) or day in unexplained_days
            prefix_suspended|=suspended
            blocked=day in blocked_days or day in unexplained_days
            if eligible:
                if goodhigh and not blocked:high=float(q['high'])/anchor-1;running=high if running is None else max(running,high)
                if goodclose and not blocked:close=float(q['close'])/anchor-1
                if running is not None and not prefix_unknown and day not in blocked_days:cum=running
            reason='no_anchor' if not eligible else 'confirmed_suspension' if suspended else 'unknown_quote' if not goodhigh or not goodclose else 'blocked_adjustment' if blocked else 'observed'
        out.append(dict(offset=offset,date=day,anchor=anchor,high_return=high,close_return=close,cumulative_high_return=cum,close_positive=close>0 if close is not None else None,reason=reason,prefix_has_suspension=prefix_suspended,D0_sellable=False if offset==0 else None))
    return out

def aggregate(paths,horizon=20):
    rows=[]
    for offset in range(horizon+1):
        values=[p[offset] for p in paths]
        def vals(key):return [r[key] for r in values if known(r[key])]
        high=vals('high_return');cum=vals('cumulative_high_return');close=vals('close_return')
        rows.append(dict(offset=offset,cohort_N=len(paths),anchor_N=sum(r['anchor'] is not None for r in values),daily_high_N=len(high),cumulative_high_N=len(cum),close_N=len(close),close_positive_N=sum(v>0 for v in close),mean_high_return=sum(high)/len(high) if high else None,mean_cumulative_high_return=sum(cum)/len(cum) if cum else None,mean_close_return=sum(close)/len(close) if close else None,close_positive_win_rate=sum(v>0 for v in close)/len(close) if close else None))
    return rows

def self_test():
    calendar=['2024-01-02','2024-01-03','2024-01-04','2024-01-05']
    def bar(h,c,status=1):return dict(open=10,high=h,close=c,volume=100 if status else 0,tradestatus=status)
    raw={calendar[1]:bar(12,11),calendar[2]:bar(11,9),calendar[3]:bar(13,10)}
    first=reference_path(calendar,calendar[0],raw,horizon=3)
    assert abs(first[0]['high_return']-.2)<1e-12 and abs(first[1]['high_return']-.1)<1e-12
    assert abs(first[1]['cumulative_high_return']-.2)<1e-12 and first[2]['close_positive'] is False
    assert first[3]['reason']=='right_censored' and first[0]['D0_sellable'] is False
    gap=reference_path(calendar,calendar[0],{calendar[1]:bar(12,11),calendar[2]:bar(99,99,0),calendar[3]:bar(13,12)},horizon=3)
    assert gap[1]['high_return'] is None and gap[1]['close_return'] is None
    assert abs(gap[1]['cumulative_high_return']-.2)<1e-12 and abs(gap[2]['cumulative_high_return']-.3)<1e-12 and gap[2]['prefix_has_suspension']
    missing=reference_path(calendar,calendar[0],{calendar[1]:bar(12,11),calendar[3]:bar(13,12)},horizon=3)
    assert missing[2]['high_return'] is not None and missing[2]['cumulative_high_return'] is None
    unanchored=reference_path(calendar,calendar[0],{calendar[1]:bar(10,10,0),calendar[2]:bar(20,20),calendar[3]:bar(30,30)},horizon=3)
    assert all(r['anchor'] is None and r['high_return'] is None for r in unanchored)
    unresolved=reference_path(calendar,calendar[0],raw,unexplained_days=[calendar[2]],horizon=3)
    assert unresolved[2]['cumulative_high_return'] is None
    ag=aggregate([first,gap,unanchored],horizon=3)
    assert ag[1]['cohort_N']==3 and ag[1]['daily_high_N']==1 and ag[1]['close_N']==1 and ag[1]['cumulative_high_N']==2 and ag[3]['daily_high_N']==0
    second=reference_path(calendar,calendar[0],{calendar[1]:bar(10,10),calendar[2]:bar(13,10),calendar[3]:bar(11,10)},horizon=3)
    means=aggregate([first,second],horizon=3)
    assert abs(means[1]['mean_cumulative_high_return']-.25)<1e-12
    assert max(means[0]['mean_high_return'],means[1]['mean_high_return'])<means[1]['mean_cumulative_high_return']
    adjusted=reference_path(calendar,calendar[0],raw,qfq={calendar[1]:{**bar(24,22),'open':20},calendar[2]:{**bar(22,18),'open':20},calendar[3]:{**bar(26,20),'open':20}},horizon=3)
    assert abs(adjusted[0]['high_return']-.2)<1e-12
    return dict(passed=True,tests=['qfq denominator arithmetic','strict calendar mapping','D0 T+1 marker','no delayed suspended entry','suspension invalidates day high/close','confirmed suspension preserves known cumulative high','unknown high prefix blocks cumulative','unexplained adjustment blocks prefix','right censoring retains rows','metric-specific denominators','per-event max before mean'],real_event_labels_generated=False)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--self-test',action='store_true');args=parser.parse_args()
    if not args.self_test:raise SystemExit('Only --self-test is enabled here; real verification has a separate adapter')
    result=self_test();(Path(__file__).resolve().parent/'SYNTHETIC_CHECKS.json').write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps(result))
