import pytest
from uuid import uuid4
from sqlalchemy import select
from app.models import ContentRetentionSnapshot,ContentGeoSnapshot
from tests.test_instagram_service import db
from app.schemas import ImportBatch
from app.manual_import import import_batch


def test_ui_snapshot_retention_geo_and_source_separation(client,content):
    body={'platform':'tiktok','platform_content_id':'test-video','source':'tiktok_studio','snapshot_at':'2026-10-03T13:52:00+03:00','views':0,'unique_viewers':2,'watch_time_avg_seconds':'15.78','completion_rate':None,'geography':[{'country_code':'LV','country_name':'Латвия','percentage':25}]}
    response=client.post('/manual-snapshots/content',json=body)
    assert response.status_code==201
    assert response.json()['views']==0 and response.json()['unique_viewers']==2
    assert response.json()['completion_rate'] is None
    assert client.post('/manual-snapshots/retention',json={'platform':'tiktok','platform_content_id':'test-video','snapshot_at':'2026-10-03T13:52:00+03:00','source':'tiktok_studio','drop_off_second':2,'average_watch_seconds':15.78,'completion_rate':4.1}).status_code==201
    history=client.get(f"/content/{content['id']}/retention").json()
    assert history[0]['source']=='tiktok_studio' and float(history[0]['drop_off_second'])==2
    snapshot_id=response.json()['id']
    geo=client.get(f'/content-snapshots/{snapshot_id}/geography').json()
    assert geo[0]['country_code']=='LV' and float(geo[0]['percentage'])==25
    assert len(client.get(f"/content/{content['id']}/history").json())==1


@pytest.mark.parametrize('source',['instagram_api','tiktok_api','instagram_ui'])
def test_ui_import_rejects_api_or_wrong_platform(client,content,source):
    response=client.post('/manual-snapshots/content',json={'platform':'tiktok','platform_content_id':'test-video','source':source,'snapshot_at':'2026-10-03T10:00:00Z','views':1})
    assert response.status_code==422
    assert client.get(f"/content/{content['id']}/history").json()==[]


def test_import_atomic_unknown_id_and_timezone_validation(client,content):
    base={'platform':'tiktok','platform_content_id':'test-video','source':'manual','snapshot_at':'2026-10-03T10:00:00Z','views':1}
    result=client.post('/manual-snapshots/import',json={'version':1,'content_snapshots':[base,{**base,'platform_content_id':'guessed-id'}]})
    assert result.status_code==404
    assert client.get(f"/content/{content['id']}/history").json()==[]
    assert client.post('/manual-snapshots/content',json={**base,'snapshot_at':'2026-10-03T10:00:00'}).status_code==422
    assert client.post('/manual-snapshots/content',json={**base,'geography':[{'country_code':'LV','percentage':101}]}).status_code==422


def test_parent_id_mismatch_is_explicit(client,content):
    result=client.post('/manual-snapshots/content',json={'platform':'tiktok','platform_content_id':'test-video','content_id':str(uuid4()),'snapshot_at':'2026-10-03T10:00:00Z','source':'manual'})
    assert result.status_code==422


def test_retention_and_geography_are_append_only(db):
    from app.models import SocialAccount,Content,ContentSnapshot
    from app.enums import Platform,ContentType,Source
    from app.types import utc_now
    account=SocialAccount(platform=Platform.TIKTOK,username='test',platform_account_id='test-retention');db.add(account);db.flush()
    content=Content(account_id=account.id,platform=Platform.TIKTOK,platform_content_id='test-retention',content_type=ContentType.VIDEO);db.add(content);db.flush()
    snapshot=ContentSnapshot(content_id=content.id,snapshot_at=utc_now(),source=Source.MANUAL);db.add(snapshot);db.flush()
    for row in (ContentRetentionSnapshot(content_id=content.id,snapshot_at=utc_now(),source=Source.MANUAL),ContentGeoSnapshot(content_snapshot_id=snapshot.id,country_code='LV')):
        db.add(row);db.commit()
        row.notes='mutated' if isinstance(row,ContentRetentionSnapshot) else None
        if isinstance(row,ContentGeoSnapshot): row.percentage=1
        with pytest.raises(ValueError,match='append-only'): db.commit()
        db.rollback()


def test_cli_validation_precedes_database_and_errors_hide_input(tmp_path,capsys):
    from app.cli.import_snapshot import main
    def forbidden(): raise AssertionError('Invalid import opened DB')
    path=tmp_path/'invalid.json';path.write_text('{"version":1,"content_snapshots":[{"access_token":"do-not-log-this"}]}')
    assert main([str(path)],engine_factory=forbidden)==1
    assert 'do-not-log-this' not in capsys.readouterr().err
    assert main(['--schema'],engine_factory=forbidden)==0
    assert 'retention_snapshots' in capsys.readouterr().out


def test_duplicate_geography_rolls_back_whole_import(client,content):
    body={'platform':'tiktok','platform_content_id':'test-video','source':'tiktok_studio','snapshot_at':'2026-10-03T10:00:00Z','views':5,'geography':[{'country_code':'LV','percentage':25},{'country_code':'LV','percentage':20}]}
    assert client.post('/manual-snapshots/content',json=body).status_code==409
    assert client.get(f"/content/{content['id']}/history").json()==[]
