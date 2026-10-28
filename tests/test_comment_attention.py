from datetime import datetime,timezone,timedelta
from uuid import uuid4,UUID

BASE=datetime(2026,10,23,tzinfo=timezone.utc)


def post(client,platform='instagram'):
    account=client.post('/accounts',json={'platform':platform,'username':'test','platform_account_id':str(uuid4())}).json()
    return client.post('/content',json={'account_id':account['id'],'platform':platform,'platform_content_id':str(uuid4()),'content_type':'video'}).json()


def snapshot(client,p,count,hour=0,**updates):
    # Collector-only scope metadata is intentionally unavailable in public snapshot input.
    from app.main import app
    from app.database import get_session
    from app.models import ContentSnapshot
    from app.enums import Source,DataStatus
    values={'content_id':UUID(p['id']),'source':p['platform']+'_api','metric_scope':'lifetime',
        'snapshot_at':BASE+timedelta(hours=hour),'snapshot_status':'confirmed','comments':count,**updates}
    values['source']=Source(values['source']);values['snapshot_status']=DataStatus(values['snapshot_status'])
    for key in ['source_period_start','source_period_end']:
        if isinstance(values.get(key),str):values[key]=datetime.fromisoformat(values[key])
    session=app.dependency_overrides[get_session]();db=next(session)
    try:
        row=ContentSnapshot(**values);db.add(row);db.commit()
        return {'id':str(row.id)}
    finally:session.close()


def feed(client):
    response=client.get('/comments/attention')
    assert response.status_code==200
    return response.json()['rows']


def test_existing_comment_is_initial_attention_not_claimed_new(client):
    p=post(client);s=snapshot(client,p,1)
    row=feed(client)[0]
    assert row['content']['id']==p['id'] and row['snapshot_id']==s['id']
    assert row['comments']==1 and row['new_comments'] is None


def test_review_persists_and_growth_returns_until_explicit_review(client):
    p=post(client);first=snapshot(client,p,1)
    body={'content_id':p['id'],'snapshot_id':first['id']}
    assert client.post('/comments/review',json=body).status_code==200
    assert feed(client)==[]
    snapshot(client,p,4,1)
    assert feed(client)[0]['new_comments']==3
    snapshot(client,p,4,2)
    assert feed(client)[0]['new_comments']==3  # Another hourly collection never clears attention.
    assert client.post('/comments/review',json=body).status_code==200
    assert feed(client)[0]['new_comments']==3  # An old browser view cannot acknowledge unseen comments.


def test_stale_review_cannot_move_baseline_backwards(client):
    p=post(client);old=snapshot(client,p,1);new=snapshot(client,p,3,1)
    for row in [new,old,new]:
        assert client.post('/comments/review',json={'content_id':p['id'],'snapshot_id':row['id']}).status_code==200
    assert feed(client)==[]
    snapshot(client,p,4,2)
    assert feed(client)[0]['new_comments']==1


def test_same_measurement_time_uses_created_time_and_old_review_cannot_undo_it(client):
    p=post(client);old=snapshot(client,p,1);new=snapshot(client,p,2)
    for s in [old,new,old]:
        assert client.post('/comments/review',json={'content_id':p['id'],'snapshot_id':s['id']}).status_code==200
    assert feed(client)==[]


def test_unknown_zero_manual_period_and_anomaly_do_not_invent_notifications(client):
    for count in [None,0]:snapshot(client,post(client),count)
    p=post(client)
    snapshot(client,p,5,source='instagram_ui',snapshot_status='manual')
    snapshot(client,p,6,1,metric_scope='range',source_period_start=BASE.isoformat(),source_period_end=(BASE+timedelta(days=1)).isoformat())
    snapshot(client,p,100,2,snapshot_status='anomalous')
    assert feed(client)==[]


def test_latest_known_count_is_dated_and_not_cleared_by_missing_metric(client):
    p=post(client);known=snapshot(client,p,2)
    snapshot(client,p,None,1)
    assert feed(client)[0]['snapshot_id']==known['id']


def test_decrease_not_new_and_platforms_stay_separate(client):
    ig=post(client);tt=post(client,'tiktok');first=snapshot(client,ig,3)
    client.post('/comments/review',json={'content_id':ig['id'],'snapshot_id':first['id']})
    snapshot(client,ig,2,1);snapshot(client,tt,1)
    assert [r['content']['platform'] for r in feed(client)]==['tiktok']


def test_review_rejects_other_publication_and_untrusted_source(client):
    a=post(client);b=post(client);s=snapshot(client,b,1)
    assert client.post('/comments/review',json={'content_id':a['id'],'snapshot_id':s['id']}).status_code==422
    manual=snapshot(client,a,1,source='instagram_ui',snapshot_status='manual')
    assert client.post('/comments/review',json={'content_id':a['id'],'snapshot_id':manual['id']}).status_code==422
    client.headers.pop('X-API-Key')
    assert client.get('/comments/attention').status_code==401
    assert client.post('/comments/review',json={'content_id':a['id'],'snapshot_id':s['id']}).status_code==401
