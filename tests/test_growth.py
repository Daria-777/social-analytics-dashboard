from uuid import uuid4
import pytest


def headers(monkeypatch):
    monkeypatch.setenv('GROWTH_API_KEY','growth-test-key')
    return {'X-API-Key':'growth-test-key'}


def test_resolve_scoped_security(client,content,monkeypatch):
    h=headers(monkeypatch)
    url='/growth/content/resolve?platform=tiktok&platform_content_id=test-video'
    assert client.get(url,headers=h).status_code==200
    assert client.get(url,headers=h).json()['content_id']==content['id']
    assert client.get(url.replace('tiktok','instagram'),headers=h).status_code==404
    assert client.get(url.replace('test-video','unknown'),headers=h).status_code==404
    assert client.get(url,headers={'X-API-Key':'wrong'}).status_code==401
    assert client.get('/accounts',headers=h).status_code==401
    assert client.post('/collectors/tiktok/run',headers=h,json={}).status_code==401
    with client as c:
        c.headers.pop('X-API-Key',None)
        assert c.get(url).status_code==401


def observation(client,content):
    client.patch(f"/content/{content['id']}/tags",json={'internal_title':'Test'})
    # Actual observation at age 30h, not a synthetic 24h checkpoint.
    row=client.post('/manual-snapshots/content',json={'platform':'tiktok','platform_content_id':'test-video','source':'tiktok_studio','snapshot_at':'2026-10-02T06:00:00Z','metric_scope':'lifetime','views':0,'shares':None})
    assert row.status_code==201
    return row.json()['id']


def analysis(snapshot):
    return dict(agent_run_id=str(uuid4()),analysis_snapshot_at='2026-10-02T07:00:00Z',data_cutoff_at='2026-10-02T06:00:00Z',agent_version='test/1',performance_verdict='Insufficient data',data_quality='partial',diagnosis='No baseline',hypothesis_status='INCONCLUSIVE',confidence='LOW',supporting_evidence=[],contrary_evidence=[],missing_data=['baseline'],competing_explanations=[],learning='Await comparable observations',next_experiment={'keep':'topic','change':'hook','why':'test','primary_metric':'views','success_signal':'predefined baseline','measurement_plan':'72h observed age','decision_after_test':'review'},scenarist_learning_brief='Test another hook',visual_learning_brief='Keep layout',snapshot_ids=[snapshot],retention_snapshot_ids=[])


def test_analysis_history_provenance_idempotency(client,content,monkeypatch):
    h=headers(monkeypatch);sid=observation(client,content);body=analysis(sid)
    url=f"/growth/content/{content['id']}/analyses"
    first=client.post(url,headers=h,json=body)
    assert first.status_code==201,first.text
    assert first.json()['provenance']['snapshots'][0]['shares'] is None
    assert first.json()['provenance']['snapshots'][0]['views']==0
    assert client.post(url,headers=h,json=body).json()['id']==first.json()['id']
    assert client.post(url,headers=h,json={**body,'diagnosis':'different'}).status_code==409
    assert client.post(url,headers=h,json={**body,'agent_run_id':str(uuid4())}).status_code==201
    rows=client.get(url,headers=h).json()
    assert len(rows)==2 and rows[0]['created_at']>=rows[1]['created_at']
    assert client.patch(url+'/'+first.json()['id'],headers=h,json={}).status_code==404
    assert client.post(url,headers=h,json={**body,'agent_run_id':str(uuid4()),'snapshot_ids':[str(uuid4())]}).status_code==422
    assert client.post(url,headers=h,json={**body,'agent_run_id':str(uuid4()),'data_cutoff_at':'2026-10-01T00:00:00Z'}).status_code==422
    assert client.post(url,headers=h,json={**body,'analysis_snapshot_at':'2026-10-02T07:00:00'}).status_code==422


def test_agent_import_atomic_replay_and_new_measurement(client,content,monkeypatch):
    headers(monkeypatch)
    h={'X-API-Key':'test-only-key'}
    assert client.post('/growth/observations/import',headers={'X-API-Key':'growth-test-key'},json={}).status_code==401
    record={'platform':'tiktok','platform_content_id':'test-video','source':'tiktok_studio','snapshot_at':'2026-10-02T06:00:00Z','views':0,'shares':None,'metric_scope':'lifetime'}
    body={'agent_run_id':str(uuid4()),'batch':{'content_snapshots':[record]}}
    url='/growth/observations/import'
    first=client.post(url,headers=h,json=body)
    assert first.status_code==201,first.text
    assert client.post(url,headers=h,json=body).json()==first.json()
    assert client.post(url,headers=h,json={**body,'batch':{'content_snapshots':[{**record,'views':1}]}}).status_code==409
    assert len(client.get(f"/content/{content['id']}/history").json())==1
    assert client.post(url,headers=h,json={**body,'agent_run_id':str(uuid4()),'batch':{'content_snapshots':[{**record,'snapshot_at':'2026-10-02T07:00:00Z'}]}}).status_code==201
    assert len(client.get(f"/content/{content['id']}/history").json())==2
    bad={**body,'agent_run_id':str(uuid4()),'batch':{'content_snapshots':[record,{**record,'platform_content_id':'missing'}]}}
    assert client.post(url,headers=h,json=bad).status_code==404
    assert len(client.get(f"/content/{content['id']}/history").json())==2


def test_context_real_age_and_separation(client,monkeypatch):
    h=headers(monkeypatch)
    a=client.post('/accounts',json={'platform':'tiktok','username':'dash.in.progress','platform_account_id':'age-account'}).json()
    c=client.post('/content',json={'platform':'tiktok','platform_content_id':'age-post','account_id':a['id'],'content_type':'video','published_at':'2026-10-01T00:00:00Z'}).json()
    for source,views in [('tiktok_studio',0),('manual',999)]:
        assert client.post('/manual-snapshots/content',json={'platform':'tiktok','platform_content_id':'age-post','source':source,'snapshot_at':'2026-10-02T06:00:00Z','metric_scope':'lifetime','views':views}).status_code==201
    r=client.get(f"/growth/content/{c['id']}/context",headers=h)
    assert r.status_code==200,r.text
    data=r.json()
    assert all(s['publication_age_hours']==30 for s in data['snapshots'])
    assert {s['source'] for s in data['snapshots']}=={'manual','tiktok_studio'}
    assert all(s['shares'] is None for s in data['snapshots'])
    assert 'raw_payload' not in str(data)


def test_growth_ui_asset_and_owner_cookie(client,content):
    assert 'detail-growth' in client.get('/dashboard').text
    asset=client.get('/dashboard/assets/dashboard-growth.js')
    assert asset.status_code==200
    assert 'innerHTML' not in asset.text
    sid=observation(client,content)
    body=analysis(sid)
    client.headers.pop('X-API-Key')
    assert client.post('/dashboard/session',json={'api_key':'test-only-key'},headers={'Origin':'http://testserver'}).status_code==200
    url=f"/growth/content/{content['id']}/analyses"
    assert client.post(url,json=body).status_code==403
    assert client.post(url,json=body,headers={'Origin':'http://testserver'}).status_code==201
    assert len(client.get(url).json())==1


def test_growth_rejects_foreign_evidence_and_preserves_interpretation(client,content,monkeypatch):
    h=headers(monkeypatch);sid=observation(client,content);body=analysis(sid)
    other=client.post('/content',json={'account_id':content['account_id'],'platform':'tiktok','platform_content_id':'other','content_type':'video'}).json()
    url=f"/growth/content/{content['id']}/analyses"
    assert client.post(f"/growth/content/{other['id']}/analyses",headers=h,json=body).status_code==422
    first=client.post(url,headers=h,json=body).json()
    client.patch(f"/content/{content['id']}/tags",json={'internal_title':'Changed later'})
    assert client.get(url,headers=h).json()[0]['provenance']['content_at_analysis']['internal_title']=='Test'
    assert client.post('/manual-snapshots/content',json={'platform':'tiktok','platform_content_id':'test-video','source':'tiktok_studio','snapshot_at':'2026-10-03T06:00:00Z','views':100}).status_code==201
    assert client.get(url,headers=h).json()[0]['provenance']==first['provenance']


def test_analysis_orm_append_only(client,content):
    from app.models import GrowthAnalysis
    from app.database import get_session
    from app.main import app
    sid=observation(client,content)
    result=client.post(f"/growth/content/{content['id']}/analyses",json=analysis(sid)).json()
    session=app.dependency_overrides[get_session]()
    db=next(session)
    try:
        row=db.get(GrowthAnalysis,__import__('uuid').UUID(result['id']))
        row.confidence='HIGH'
        with pytest.raises(ValueError,match='append-only'):db.commit()
        db.rollback()
        row=db.get(GrowthAnalysis,__import__('uuid').UUID(result['id']));db.delete(row)
        with pytest.raises(ValueError,match='append-only'):db.commit()
        db.rollback()
    finally:session.close()
