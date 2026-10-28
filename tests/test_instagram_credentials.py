from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
import httpx
import pytest
from app.config import Settings
from app.connectors.instagram.credentials import Credential, CredentialStore, CredentialError, resolve_settings
from app.connectors.instagram.auth import SCOPES

NOW = datetime(2026, 10, 23, tzinfo=timezone.utc)


def record(**updates):
    return Credential.model_validate(dict(dict(access_token='fake-old-secret', expires_in=60*86400,
        issued_at=NOW-timedelta(days=54), user_id='123', scopes=list(SCOPES)), **updates))


def config(path, **updates):
    return Settings(_env_file=None, instagram_credential_store=path,
        instagram_auto_refresh_enabled=True, instagram_user_id='123', **updates)


def seed(tmp_path, value=None):
    store = CredentialStore(tmp_path/'.instagram-credentials')
    store.seed(value or record())
    return store


def renewal(request):
    assert str(request.url).startswith('https://graph.instagram.com/refresh_access_token?')
    assert request.url.params['grant_type'] == 'ig_refresh_token'
    return httpx.Response(200, json={'access_token':'fake-new-secret','token_type':'bearer','expires_in':60*86400})


def test_refresh_persists_new_token_for_independent_readers(tmp_path, caplog):
    store=seed(tmp_path); settings=config(store.directory)
    resolved=resolve_settings(settings, allow_refresh=True, now=NOW, transport=httpx.MockTransport(renewal))
    assert resolved.require_instagram_token()=='fake-new-secret'
    assert resolve_settings(settings, now=NOW).require_instagram_token()=='fake-new-secret'
    assert store.read().issued_at==NOW
    assert store.path.stat().st_mode & 0o777 == 0o600
    assert store.directory.stat().st_mode & 0o777 == 0o700
    assert all(value not in caplog.text for value in ['fake-old-secret','fake-new-secret'])


@pytest.mark.parametrize('days', [0, 0.5, 1, 52])
def test_fresh_tokens_never_call_refresh(tmp_path, days):
    store=seed(tmp_path, record(issued_at=NOW-timedelta(days=days)))
    def forbidden(request): raise AssertionError('Fresh token was refreshed')
    resolve_settings(config(store.directory), allow_refresh=True, now=NOW, transport=httpx.MockTransport(forbidden))


@pytest.mark.parametrize('payload', [
    {'access_token':'','expires_in':5184000},
    {'access_token':'  ','expires_in':5184000},
    {'access_token':'bad','token_type':'mac','expires_in':5184000},
    {'access_token':'bad','expires_in':0},
])
def test_invalid_refresh_never_replaces_working_token(tmp_path, payload, caplog):
    store=seed(tmp_path); before=store.path.read_bytes()
    resolved=resolve_settings(config(store.directory), allow_refresh=True, now=NOW,
        transport=httpx.MockTransport(lambda r:httpx.Response(200,json=payload)))
    assert resolved.require_instagram_token()=='fake-old-secret'
    assert store.path.read_bytes()==before
    assert 'fake-old-secret' not in caplog.text


@pytest.mark.parametrize('status,body', [(401,{'error':{'code':190}}),(503,{}),(429,{'error':{'code':4}})])
def test_refresh_error_keeps_current_token_without_http_retry(tmp_path,status,body):
    store=seed(tmp_path); calls=[]; before=store.path.read_bytes()
    def fail(request): calls.append(1);return httpx.Response(status,json=body)
    resolved=resolve_settings(config(store.directory),allow_refresh=True,now=NOW,transport=httpx.MockTransport(fail))
    assert resolved.require_instagram_token()=='fake-old-secret'
    assert calls==[1] and store.path.read_bytes()==before


def test_concurrent_workers_only_refresh_once(tmp_path):
    store=seed(tmp_path); calls=[]
    def renew(request): calls.append(1);return renewal(request)
    def worker(_):return resolve_settings(config(store.directory),allow_refresh=True,now=NOW,transport=httpx.MockTransport(renew)).require_instagram_token()
    with ThreadPoolExecutor(2) as pool: result=list(pool.map(worker,range(2)))
    assert result==['fake-new-secret']*2 and calls==[1]


def test_expired_token_is_not_refreshed(tmp_path):
    store=seed(tmp_path,record(issued_at=NOW-timedelta(days=61)))
    with pytest.raises(CredentialError):resolve_settings(config(store.directory),allow_refresh=True,now=NOW)


def test_wrong_owner_and_unverified_grants_refused(tmp_path):
    store=seed(tmp_path)
    with pytest.raises(CredentialError):resolve_settings(Settings(_env_file=None,instagram_credential_store=store.directory,instagram_user_id='999'),now=NOW)
    value=json.loads(store.path.read_text());value['scopes'].append('instagram_business_manage_messages');store.path.write_text(json.dumps(value))
    with pytest.raises(CredentialError):store.read()


def test_symlink_or_public_token_file_refused(tmp_path):
    store=seed(tmp_path);store.path.chmod(0o644)
    with pytest.raises(CredentialError):store.read()
    store.path.chmod(0o600);target=tmp_path/'copy';store.path.rename(target);store.path.symlink_to(target)
    with pytest.raises(CredentialError):store.read()


def test_failed_atomic_replace_leaves_old_token(tmp_path,monkeypatch):
    store=seed(tmp_path); before=store.path.read_bytes()
    def fail(*args):raise OSError('disk error')
    monkeypatch.setattr(os,'replace',fail)
    with pytest.raises(CredentialError):
        resolve_settings(config(store.directory),allow_refresh=True,now=NOW,transport=httpx.MockTransport(renewal))
    assert store.path.read_bytes()==before
    assert not list(store.directory.glob('.credential-*'))


def test_legacy_env_stays_opt_in_and_docker_runtime_cannot_refresh_on_host(monkeypatch,tmp_path):
    settings=Settings(_env_file=None,instagram_access_token='env-secret')
    assert resolve_settings(settings).require_instagram_token()=='env-secret'
    with pytest.raises(CredentialError):resolve_settings(settings.model_copy(update={'instagram_auto_refresh_enabled':True}))
    store=seed(tmp_path)
    import app.connectors.instagram.credentials as module
    monkeypatch.setattr(module.sys,'platform','darwin')
    with pytest.raises(CredentialError):resolve_settings(config(store.directory,instagram_renewal_runtime='docker'),allow_refresh=True,now=NOW)


def test_api_dependency_reads_rotated_token_without_env_or_restart(tmp_path,monkeypatch):
    from app.collectors_api import get_instagram_settings
    import app.collectors_api as api
    # Keep the record fresh relative to the actual test clock; this makes no HTTP call.
    store=seed(tmp_path,record(issued_at=datetime.now(timezone.utc)))
    monkeypatch.setattr(api,'Settings',lambda:config(store.directory))
    assert get_instagram_settings().require_instagram_token()=='fake-old-secret'
    with store.locked():store._write(record(access_token='rotated',issued_at=datetime.now(timezone.utc)))
    assert get_instagram_settings().require_instagram_token()=='rotated'


def test_store_only_is_configured_for_scheduler_without_network(tmp_path):
    from app.scheduler import configured
    from app.enums import Platform
    store=seed(tmp_path)
    assert configured(config(store.directory),Platform.INSTAGRAM)


def test_cli_invalid_store_fails_safely_before_database(tmp_path,capsys):
    from app.cli.collect_instagram import main
    def forbidden():raise AssertionError('DB accessed before credential validation')
    assert main([],settings=config(tmp_path/'.instagram-credentials'),engine_factory=forbidden)==2
    assert 'fake-old-secret' not in capsys.readouterr().err


def test_bootstrap_refuses_wrong_owner_without_saving(tmp_path,monkeypatch,capsys):
    import io
    from app.cli.instagram_credentials import main
    value=record(issued_at=datetime.now(timezone.utc)).model_dump(mode='json')
    value['access_token']='seed-secret'
    monkeypatch.setattr('sys.stdin',io.TextIOWrapper(io.BytesIO(json.dumps(value).encode())))
    transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'user_id':'999','username':'demo.account'}))
    assert main(['--seed-stdin'],settings=config(tmp_path/'.instagram-credentials'),transport=transport)==1
    assert not (tmp_path/'.instagram-credentials/credentials.json').exists()
    output=capsys.readouterr()
    assert 'seed-secret' not in output.out+output.err


def test_bootstrap_validates_owner_then_seeds_once(tmp_path,monkeypatch,capsys):
    import io
    from app.cli.instagram_credentials import main
    value=record(issued_at=datetime.now(timezone.utc)).model_dump(mode='json');value['access_token']='seed-secret'
    transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'user_id':'123','username':'demo.account'}))
    settings=config(tmp_path/'.instagram-credentials')
    for expected in [0,1]:
        monkeypatch.setattr('sys.stdin',io.TextIOWrapper(io.BytesIO(json.dumps(value).encode())))
        assert main(['--seed-stdin'],settings=settings,transport=transport)==expected
    output=capsys.readouterr()
    assert 'seed-secret' not in output.out+output.err
    assert CredentialStore(settings.instagram_credential_store).read().access_token.get_secret_value()=='seed-secret'
