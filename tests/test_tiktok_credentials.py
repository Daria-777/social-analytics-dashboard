"""Private store tests use fake credentials and mocked OAuth only."""
from datetime import datetime,timedelta,timezone
import os
from pathlib import Path
import httpx
import pytest
from app.config import Settings
from tests.test_tiktok_auth import token_payload

NOW=datetime(2026,10,3,12,tzinfo=timezone.utc)


def config(path,**changes):
    return Settings(_env_file=None,tiktok_credential_store=path,**{'tiktok_auto_refresh_enabled':True,'tiktok_client_key':'fake-key','tiktok_client_secret':'fake-secret',**changes})


def seed(path,*,issued_at=NOW,expires_in=86400):
    from app.connectors.tiktok.credentials import CredentialStore,Credential
    from app.connectors.tiktok.schemas import Token
    record=Credential.from_token(Token.model_validate(token_payload(expires_in=expires_in)),issued_at=issued_at,owner_confirmed=True)
    CredentialStore(path).seed(record);return record


def test_store_private_atomic_reload_and_no_other_config(tmp_path):
    from app.connectors.tiktok.credentials import CredentialStore,resolve_settings
    path=tmp_path/'.tiktok-credentials';seed(path)
    assert path.stat().st_mode & 0o777==0o700
    assert (path/'credentials.json').stat().st_mode & 0o777==0o600
    before=(path/'credentials.json').stat().st_ino
    seed(path,issued_at=NOW+timedelta(seconds=1))
    assert (path/'credentials.json').stat().st_ino!=before
    result=resolve_settings(config(path),now=NOW+timedelta(seconds=1))
    assert result.require_tiktok_token()=='test-access' and result.tiktok_open_id=='test-open'
    assert 'INTERNAL_API_KEY' not in (path/'credentials.json').read_text()
    assert CredentialStore(path).read().scope==token_payload()['scope']


def test_expiry_skew_one_refresh_rotation_and_following_reload(tmp_path,caplog):
    from app.connectors.tiktok.credentials import resolve_settings
    path=tmp_path/'.tiktok-credentials';seed(path,expires_in=200);calls=[]
    def provider(request):
        calls.append(request)
        return httpx.Response(200,json=token_payload(access_token='rotated-access',refresh_token='rotated-refresh',scope='video.list,user.info.profile,user.info.basic,user.info.stats'))
    transport=httpx.MockTransport(provider)
    first=resolve_settings(config(path),allow_refresh=True,transport=transport,now=NOW)
    second=resolve_settings(config(path),allow_refresh=True,transport=transport,now=NOW)
    assert len(calls)==1 and first.require_tiktok_token()==second.require_tiktok_token()=='rotated-access'
    assert second.tiktok_refresh_token.get_secret_value()=='rotated-refresh' and 'user.info.stats' in second.tiktok_scopes
    assert all(secret not in caplog.text for secret in ('rotated-access','rotated-refresh','fake-secret','test-refresh'))


@pytest.mark.parametrize('changes',[{'access_token':''},{'scope':'user.info.basic,user.info.profile,video.list,video.publish'},{'open_id':'wrong-owner'},{'expires_in':0},{'expires_in':10**100}])
def test_invalid_renewal_preserves_store(tmp_path,changes):
    from app.connectors.tiktok.credentials import resolve_settings
    from app.connectors.tiktok.errors import TikTokError
    path=tmp_path/'.tiktok-credentials';seed(path,expires_in=1);before=(path/'credentials.json').read_bytes()
    with pytest.raises(TikTokError):resolve_settings(config(path),allow_refresh=True,transport=httpx.MockTransport(lambda r:httpx.Response(200,json=token_payload(**changes))),now=NOW)
    assert (path/'credentials.json').read_bytes()==before


def test_plan_read_and_disabled_refresh_never_call_http(tmp_path):
    from app.connectors.tiktok.credentials import resolve_settings
    path=tmp_path/'.tiktok-credentials';seed(path,expires_in=1)
    transport=httpx.MockTransport(lambda r:pytest.fail('Must not refresh'))
    assert resolve_settings(config(path),transport=transport,now=NOW).require_tiktok_token()=='test-access'
    assert resolve_settings(config(path,tiktok_auto_refresh_enabled=False),allow_refresh=True,transport=transport,now=NOW).require_tiktok_token()=='test-access'


def test_env_legacy_is_default_and_enabled_missing_store_fails_closed():
    from app.connectors.tiktok.credentials import resolve_settings
    from app.connectors.tiktok.errors import TikTokError
    legacy=Settings(_env_file=None,tiktok_access_token='legacy-fake')
    assert resolve_settings(legacy) is legacy
    legacy.tiktok_auto_refresh_enabled=True
    with pytest.raises(TikTokError):resolve_settings(legacy,allow_refresh=True)


def test_malformed_private_file_and_symlinks_are_safe(tmp_path):
    from app.connectors.tiktok.credentials import CredentialStore
    from app.connectors.tiktok.errors import TikTokError
    path=tmp_path/'.tiktok-credentials';seed(path)
    file=path/'credentials.json';file.write_text('private-malformed-token')
    with pytest.raises(TikTokError) as error:CredentialStore(path).read()
    assert 'private-malformed-token' not in str(error.value)
    file.unlink();file.symlink_to(tmp_path/'outside')
    with pytest.raises(TikTokError):CredentialStore(path).read()


def test_atomic_replace_failure_preserves_old_file(tmp_path,monkeypatch):
    from app.connectors.tiktok.errors import TikTokError
    path=tmp_path/'.tiktok-credentials';seed(path);before=(path/'credentials.json').read_bytes()
    monkeypatch.setattr(os,'replace',lambda *a:(_ for _ in ()).throw(OSError('private-path-detail')))
    with pytest.raises(TikTokError) as error:seed(path,issued_at=NOW+timedelta(seconds=1))
    assert (path/'credentials.json').read_bytes()==before and 'private-path-detail' not in str(error.value)
    assert not list(path.glob('.credential-*'))


def _refresh_worker(path,barrier,queue):
    from app.connectors.tiktok.credentials import resolve_settings
    import time
    def provider(request):
        queue.put('refresh');time.sleep(.1)
        return httpx.Response(200,json=token_payload(access_token='concurrent-new',refresh_token='concurrent-refresh'))
    barrier.wait(timeout=5)
    try:queue.put(resolve_settings(config(path),allow_refresh=True,transport=httpx.MockTransport(provider),now=NOW).require_tiktok_token())
    except Exception:queue.put('failure')


def test_two_independent_processes_refresh_once_and_reload_rotated_token(tmp_path):
    import multiprocessing
    path=tmp_path/'.tiktok-credentials';seed(path,expires_in=1)
    context=multiprocessing.get_context('spawn');barrier=context.Barrier(2);queue=context.Queue()
    workers=[context.Process(target=_refresh_worker,args=(path,barrier,queue)) for _ in range(2)]
    try:
        for worker in workers:worker.start()
        for worker in workers:worker.join(5)
        assert all(not worker.is_alive() and worker.exitcode==0 for worker in workers)
        results=[queue.get(timeout=2) for _ in range(3)]
        assert sorted(results)==['concurrent-new','concurrent-new','refresh']
    finally:
        for worker in workers:
            if worker.is_alive():worker.terminate();worker.join(2)
        queue.close()


@pytest.mark.parametrize('change',[{'owner_verified':False},{'grant_verified':False},{'issued_at':'2026-10-03T12:00:00'},{'refresh_expires_in':0},{'unknown':'private-secret'},{'expires_in':10**100}])
def test_unverified_or_malformed_metadata_never_refreshes(tmp_path,change):
    import json
    from app.connectors.tiktok.credentials import resolve_settings
    from app.connectors.tiktok.errors import TikTokError
    path=tmp_path/'.tiktok-credentials';seed(path,expires_in=1);file=path/'credentials.json'
    payload=json.loads(file.read_text());payload.update(change);file.write_text(json.dumps(payload));before=file.read_bytes()
    with pytest.raises(TikTokError) as error:resolve_settings(config(path),allow_refresh=True,now=NOW,transport=httpx.MockTransport(lambda r:pytest.fail('Must not call provider')))
    assert file.read_bytes()==before and 'private-secret' not in str(error.value)


def test_expired_refresh_and_wrong_configured_owner_never_call_oauth(tmp_path):
    from app.connectors.tiktok.credentials import resolve_settings
    from app.connectors.tiktok.errors import TikTokError
    path=tmp_path/'.tiktok-credentials';seed(path,issued_at=NOW-timedelta(days=366),expires_in=1)
    transport=httpx.MockTransport(lambda r:pytest.fail('Must not refresh expired credential'))
    for configuration in (config(path),config(path,tiktok_open_id='another-owner')):
        with pytest.raises(TikTokError):resolve_settings(configuration,allow_refresh=True,now=NOW,transport=transport)


def test_oauth_post_failure_is_not_retried(tmp_path):
    from app.connectors.tiktok.credentials import resolve_settings
    from app.connectors.tiktok.errors import TikTokError
    path=tmp_path/'.tiktok-credentials';seed(path,expires_in=1);calls=[];before=(path/'credentials.json').read_bytes()
    def provider(request):calls.append(1);return httpx.Response(500,json={'error':'server_error','error_description':'private-provider-message'})
    with pytest.raises(TikTokError) as error:resolve_settings(config(path),allow_refresh=True,transport=httpx.MockTransport(provider),now=NOW)
    assert calls==[1] and (path/'credentials.json').read_bytes()==before and 'private-provider-message' not in str(error.value)


def test_insecure_permissions_and_directory_symlink_fail_closed(tmp_path):
    from app.connectors.tiktok.credentials import CredentialStore
    from app.connectors.tiktok.errors import TikTokError
    path=tmp_path/'.tiktok-credentials';seed(path);file=path/'credentials.json';file.chmod(0o644)
    with pytest.raises(TikTokError):CredentialStore(path).read()
    file.chmod(0o600);path.chmod(0o755)
    with pytest.raises(TikTokError):CredentialStore(path).read()
    path.chmod(0o700);parent=tmp_path/'alias';parent.mkdir();(parent/'.tiktok-credentials').symlink_to(path,target_is_directory=True)
    with pytest.raises(TikTokError):CredentialStore(parent/'.tiktok-credentials').read()


def test_cli_uses_rotated_token_before_any_collection_http(tmp_path,monkeypatch,capsys):
    from app.cli.collect_tiktok import main
    from app.connectors.tiktok.credentials import Credential,CredentialStore
    from app.connectors.tiktok.schemas import Token
    from datetime import datetime
    path=tmp_path/'.tiktok-credentials';record=Credential.from_token(Token.model_validate(token_payload(expires_in=1)),issued_at=datetime.now(timezone.utc)-timedelta(seconds=2),owner_confirmed=True);CredentialStore(path).seed(record)
    requests=[]
    def provider(request):
        requests.append(request)
        if request.url.path=='/v2/oauth/token/':return httpx.Response(200,json=token_payload(access_token='entrypoint-rotated'))
        assert request.headers['authorization']=='Bearer entrypoint-rotated'
        if request.url.path=='/v2/user/info/':return httpx.Response(200,json={'data':{'user':{'open_id':'test-open','username':'demo.account'}},'error':{'code':'ok'}})
        return httpx.Response(200,json={'data':{'videos':[],'has_more':False},'error':{'code':'ok'}})
    assert main(['--dry-run'],settings=config(path),transport=httpx.MockTransport(provider),engine_factory=lambda:pytest.fail('Dry run DB'))==0
    assert requests[0].url.path=='/v2/oauth/token/' and len(requests)==3
    assert 'entrypoint-rotated' not in capsys.readouterr().out


def test_api_settings_reload_private_store_and_status_never_refreshes(tmp_path,monkeypatch,client):
    from app import collectors_api as api
    path=tmp_path/'.tiktok-credentials';seed(path)
    monkeypatch.setattr(api,'Settings',lambda:config(path))
    resolve=api.resolve_settings
    monkeypatch.setattr(api,'resolve_settings',lambda settings,**kwargs:resolve(settings,now=NOW,**kwargs))
    assert api.get_tiktok_settings().require_tiktok_token()=='test-access'
    # Status is DB-only, even when a bad/expired credential store is selected.
    (path/'credentials.json').write_text('invalid-private-data')
    assert client.get('/collectors/status').status_code==200
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:api.get_tiktok_settings()
    assert error.value.status_code==503 and 'invalid-private-data' not in error.value.detail


def test_owner_confirmation_required_to_seed_store_without_touching_env(tmp_path,monkeypatch):
    from app.cli import tiktok_auth as cli
    from tests.test_tiktok_auth import settings
    monkeypatch.setattr(cli,'Settings',lambda **_:settings())
    path=tmp_path/'.env';path.write_text('unchanged')
    assert cli.main(['--env-file',str(path),'--credential-store',str(tmp_path/'.tiktok-credentials')])==1
    assert path.read_text()=='unchanged' and not (tmp_path/'.tiktok-credentials').exists()


def test_oauth_seed_store_leaves_env_unchanged_and_records_metadata(tmp_path,monkeypatch):
    from app.cli import tiktok_auth as cli
    from app.connectors.tiktok.credentials import CredentialStore
    from app.connectors.tiktok.schemas import Token
    from tests.test_tiktok_auth import settings
    configuration=settings();monkeypatch.setattr(cli,'Settings',lambda **_:configuration)
    monkeypatch.setattr(cli,'getpass',lambda _:configuration.tiktok_redirect_uri+'?code=fake-code&state='+captured[0].value)
    captured=[]
    original=cli.TikTokAuth.authorization_url
    def authorize(self,state,**kwargs):captured.append(state);return original(self,state,**kwargs)
    monkeypatch.setattr(cli.TikTokAuth,'authorization_url',authorize)
    monkeypatch.setattr(cli.TikTokAuth,'exchange_code',lambda *a,**k:Token.model_validate(token_payload()))
    path=tmp_path/'.env';path.write_text('OWNER_KEY=unchanged\n');store=tmp_path/'.tiktok-credentials'
    assert cli.main(['--env-file',str(path),'--credential-store',str(store),'--confirm-owner'])==0
    assert path.read_text()=='OWNER_KEY=unchanged\n'
    record=CredentialStore(store).read()
    assert record.owner_verified and record.grant_verified and record.open_id=='test-open'


def test_manual_store_refresh_works_with_opt_in_disabled_and_preserves_env(tmp_path,monkeypatch):
    from app.cli import tiktok_auth as cli
    from app.connectors.tiktok.credentials import resolve_settings,CredentialStore
    path=tmp_path/'.tiktok-credentials';seed(path)
    configuration=config(path,tiktok_auto_refresh_enabled=False)
    monkeypatch.setattr(cli,'Settings',lambda **_:configuration)
    calls=[]
    def provider(request):calls.append(1);return httpx.Response(200,json=token_payload(refresh_token='manual-rotation'))
    monkeypatch.setattr(cli,'resolve_settings',lambda settings,**kwargs:resolve_settings(settings,transport=httpx.MockTransport(provider),now=NOW,**kwargs))
    env=tmp_path/'.env';env.write_text('OWNER_KEY=preserved\n')
    assert cli.main(['--env-file',str(env),'--credential-store',str(path),'--refresh'])==0
    assert calls==[1] and env.read_text()=='OWNER_KEY=preserved\n'
    assert CredentialStore(path).read().refresh_token.get_secret_value()=='manual-rotation'


def test_read_refuses_fifo_without_blocking(tmp_path):
    from app.connectors.tiktok.credentials import CredentialStore
    from app.connectors.tiktok.errors import TikTokError
    path=tmp_path/'.tiktok-credentials';path.mkdir(mode=0o700);os.mkfifo(path/'credentials.json',0o600)
    with pytest.raises(TikTokError):CredentialStore(path).read()


def test_oversized_write_is_rejected_before_replacing_credentials(tmp_path):
    from app.connectors.tiktok.credentials import CredentialStore,Credential
    from app.connectors.tiktok.schemas import Token
    from app.connectors.tiktok.errors import TikTokError
    path=tmp_path/'.tiktok-credentials';seed(path);before=(path/'credentials.json').read_bytes()
    record=Credential.from_token(Token.model_validate(token_payload(access_token='fake-large'*10000)),issued_at=NOW,owner_confirmed=True)
    with pytest.raises(TikTokError):CredentialStore(path).seed(record)
    assert (path/'credentials.json').read_bytes()==before


def test_config_only_store_refresh_targets_store_and_never_env(tmp_path,monkeypatch):
    from app.cli import tiktok_auth as cli
    from app.connectors.tiktok.credentials import resolve_settings,CredentialStore
    path=tmp_path/'.tiktok-credentials';seed(path)
    monkeypatch.setattr(cli,'Settings',lambda **_:config(path,tiktok_auto_refresh_enabled=False))
    monkeypatch.setattr(cli,'resolve_settings',lambda settings,**kwargs:resolve_settings(settings,now=NOW,transport=httpx.MockTransport(lambda r:httpx.Response(200,json=token_payload(refresh_token='config-only-rotation'))),**kwargs))
    env=tmp_path/'.env';env.write_text('OWNER_KEY=unchanged\n')
    assert cli.main(['--env-file',str(env),'--refresh'])==0
    assert env.read_text()=='OWNER_KEY=unchanged\n' and CredentialStore(path).read().refresh_token.get_secret_value()=='config-only-rotation'
    assert cli.main(['--env-file',str(env)])==1  # Config-selected store still requires owner confirmation for seed.
    assert env.read_text()=='OWNER_KEY=unchanged\n'


def test_mac_cannot_renew_docker_selected_store_or_seed_without_stopped_workers(tmp_path,monkeypatch):
    from app.connectors.tiktok import credentials
    from app.cli import tiktok_auth as cli
    from app.connectors.tiktok.errors import TikTokError
    path=tmp_path/'.tiktok-credentials';seed(path,expires_in=1);before=(path/'credentials.json').read_bytes()
    configuration=config(path,tiktok_renewal_runtime='docker')
    monkeypatch.setattr(credentials.sys,'platform','darwin')
    with pytest.raises(TikTokError):credentials.resolve_settings(configuration,allow_refresh=True,now=NOW,transport=httpx.MockTransport(lambda r:pytest.fail('Mixed host/guest renewal forbidden')))
    monkeypatch.setattr(cli,'Settings',lambda **_:configuration)
    env=tmp_path/'.env';env.write_text('unchanged')
    assert cli.main(['--env-file',str(env),'--confirm-owner'])==1
    assert (path/'credentials.json').read_bytes()==before and env.read_text()=='unchanged'
