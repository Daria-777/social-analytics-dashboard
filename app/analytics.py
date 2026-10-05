"""Derived values are responses, never stored as raw observations."""
from decimal import Decimal
from statistics import mean,median

RATE_FIELDS={'like_rate':('likes','views'),'comment_rate':('comments','views'),'share_rate':('shares','views'),'save_rate':('saves','views'),'follow_conversion':('followers_gained','unique_viewers'),'profile_visit_rate':('profile_visits','unique_viewers')}
AGES=(1,6,24,48,72,168)


def ratio(numerator,denominator,scale=1):
    if numerator is None or denominator is None or denominator<=0: return None
    return Decimal(numerator)/Decimal(denominator)*Decimal(scale)


def derived_metrics(content,snapshot):
    result={name:ratio(getattr(snapshot,numerator),getattr(snapshot,denominator)) for name,(numerator,denominator) in RATE_FIELDS.items()}
    result['average_watch_pct']=ratio(snapshot.watch_time_avg_seconds,content.duration_seconds,100)
    result['returning_viewer_rate']=ratio(snapshot.returning_viewers_pct,100)
    return result


def sample_guard(n):
    return 'insufficient_sample' if n<5 else 'directional_only' if n<10 else 'observational_signal'


def summary(values):
    available=[Decimal(str(v)) for v in values if v is not None]
    return {'mean':mean(available) if available else None,'median':median(available) if available else None,'n':len(available),'guardrail':sample_guard(len(available))}


def velocity(content,snapshots):
    candidates=[]
    if content.published_at is not None:
        for snapshot in snapshots:
            if snapshot.metric_scope!='lifetime' or snapshot.source_period_start is not None or snapshot.source_period_end is not None: continue
            age=(snapshot.snapshot_at-content.published_at).total_seconds()/3600
            if age>=0: candidates.append((age,snapshot))
    result=[]
    for requested in AGES:
        actual,row=min(candidates,key=lambda pair:(abs(pair[0]-requested),pair[0],str(pair[1].id))) if candidates else (None,None)
        result.append({'requested_age_hours':requested,'actual_age_hours':actual,'deviation_hours':actual-requested if actual is not None else None,'views':row.views if row else None,'snapshot_id':str(row.id) if row and row.id else None,'snapshot_at':row.snapshot_at if row else None,'source':row.source if row else None})
    return result
