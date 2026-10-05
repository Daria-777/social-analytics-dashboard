from datetime import datetime,timezone,timedelta
from decimal import Decimal
import pytest
from app.analytics import ratio,sample_guard,derived_metrics,velocity
from app.models import Content,ContentSnapshot
from app.enums import Source,ContentType,Platform


@pytest.mark.parametrize('numerator,denominator,expected',[(None,10,None),(1,None,None),(0,0,None),(0,2,Decimal(0)),(2,4,Decimal('.5'))])
def test_ratio_null_and_zero(numerator,denominator,expected): assert ratio(numerator,denominator)==expected


def test_no_reach_substitution_and_no_anomaly_clamping():
    content=Content(duration_seconds=10)
    snapshot=ContentSnapshot(views=0,unique_viewers=2,reach=5,watch_time_avg_seconds=Decimal('15.78'),followers_gained=1)
    values=derived_metrics(content,snapshot)
    assert values['like_rate'] is None and values['follow_conversion']==Decimal('.5')
    assert values['average_watch_pct']==Decimal('157.8')
    snapshot.unique_viewers=None
    assert derived_metrics(content,snapshot)['follow_conversion'] is None


@pytest.mark.parametrize('n,expected',[(0,'insufficient_sample'),(4,'insufficient_sample'),(5,'directional_only'),(9,'directional_only'),(10,'observational_signal')])
def test_sample_guard(n,expected): assert sample_guard(n)==expected


def test_velocity_nearest_age_exposes_deviation_and_excludes_range():
    published=datetime(2026,1,1,tzinfo=timezone.utc)
    content=Content(published_at=published)
    snapshots=[ContentSnapshot(snapshot_at=published+timedelta(hours=25.3),source=Source.TIKTOK_API,metric_scope='lifetime',views=250),ContentSnapshot(snapshot_at=published+timedelta(hours=24),source=Source.TIKTOK_API,metric_scope='range',source_period_start=published,source_period_end=published+timedelta(hours=1),views=999)]
    point=velocity(content,snapshots)[2]
    assert point['requested_age_hours']==24 and point['actual_age_hours']==25.3
    assert round(point['deviation_hours'],1)==1.3 and point['views']==250


def test_comparison_keeps_sources_separate_and_edits_only_tags(client,content):
    for source,views in [('tiktok_api',10),('tiktok_studio',20)]:
        response=client.post('/content-snapshots',json={'content_id':content['id'],'snapshot_at':'2026-01-01T12:00:00Z','source':source,'views':views,'likes':0})
        assert response.status_code==201
    result=client.get('/analytics/content-comparison').json()
    assert {row['snapshot']['source'] for row in result['rows']}=={'tiktok_api','tiktok_studio'}
    assert all(group['sample_size']==1 for group in result['groups'])
    assert all(group['guardrail']=='insufficient_sample' for group in result['groups'])
    result=client.get('/analytics/content-comparison?source=tiktok_api').json()
    assert len(result['rows'])==1 and result['rows'][0]['snapshot']['views']==10
    before=client.get(f"/content/{content['id']}/history").json()
    assert client.patch(f"/content/{content['id']}/tags",json={'hook_type':'conflict','series':'test-series'}).status_code==200
    assert client.get('/analytics/content-comparison?series=test-series').json()['rows']
    assert client.patch(f"/content/{content['id']}/tags",json={'platform_content_id':'different'}).status_code==422
    assert client.get(f"/content/{content['id']}/history").json()==before


def test_summary_numeric_json_strings_keep_null_sample_size():
    from app.analytics import summary
    assert summary(['4.1',None,'0'])=={'mean':Decimal('2.05'),'median':Decimal('2.05'),'n':2,'guardrail':'insufficient_sample'}


def test_latest_observation_per_source_period_and_aggregate_units(client,content):
    base={'platform':'tiktok','platform_content_id':'test-video','source':'tiktok_studio','metric_scope':'lifetime','completion_rate':4.1,'snapshot_at':'2026-01-01T12:00:00Z','views':10}
    assert client.post('/manual-snapshots/content',json=base).status_code==201
    assert client.post('/manual-snapshots/content',json={**base,'snapshot_at':'2026-01-02T12:00:00Z','views':20}).status_code==201
    result=client.get('/analytics/content-comparison?source=tiktok_studio').json()
    assert len(result['rows'])==1 and result['rows'][0]['snapshot']['views']==20
    group=result['groups'][0]
    assert group['comparable_period'] is True and group['sample_size']==1
    assert group['metrics']['completion_rate']['mean']==4.1 and group['metrics']['completion_rate']['n']==1
    assert client.post('/manual-snapshots/content',json={**base,'metric_scope':'range'}).status_code==422
