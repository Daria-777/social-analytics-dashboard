import httpx
import pytest
from urllib.parse import parse_qs,urlsplit
from pydantic import SecretStr
from app.config import Settings
from app.connectors.tiktok.auth import TikTokAuth,OAuthState
from app.connectors.tiktok.errors import TikTokInvalidResponseError,TikTokPermissionError,TikTokIdentityError
from app.cli.tiktok_auth import save_token


def settings():
    return Settings(_env_file=None,tiktok_client_key='test-key',tiktok_client_secret='test-secret',tiktok_redirect_uri='https://example.com/tiktok/callback')


def token_payload(**changes):
    return {'access_token':'test-access','refresh_token':'test-refresh','expires_in':86400,'refresh_expires_in':31536000,'open_id':'test-open','token_type':'Bearer','scope':'user.info.basic,user.info.profile,video.list',**changes}


def test_oauth_url_and_atomic_rotated_storage(tmp_path,caplog):
    config=settings();state=OAuthState()
    with TikTokAuth(config,transport=httpx.MockTransport(lambda r:httpx.Response(200,json=token_payload()))) as auth:
        query=parse_qs(urlsplit(auth.authorization_url(state)).query)
        assert set(query['scope'][0].split(','))=={'user.info.basic','user.info.profile','user.info.stats','video.list'}
        assert query['state']==[state.value]
        token=auth.exchange_code('test-code')
    path=tmp_path/'.env';path.write_text('DATABASE_URL=unchanged\nTIKTOK_REFRESH_TOKEN=old\n')
    save_token(path,token)
    assert path.stat().st_mode & 0o777==0o600
    assert 'DATABASE_URL=unchanged' in path.read_text()
    assert path.read_text().count('TIKTOK_REFRESH_TOKEN=')==1
    assert "TIKTOK_REFRESH_TOKEN='test-refresh'" in path.read_text()
    assert 'test-access' not in repr(token)+caplog.text


@pytest.mark.parametrize('changes', [{'access_token':''},{'refresh_token':'   '},{'token_type':'unsafe-secret'},{'expires_in':0},{'open_id':''}])
@pytest.mark.parametrize('operation',['exchange','refresh'])
def test_invalid_tokens_never_touch_env(changes,operation,tmp_path):
    path=tmp_path/'.env';path.write_bytes(b'TIKTOK_ACCESS_TOKEN=working\n');before=path.stat().st_mtime_ns
    with TikTokAuth(settings(),transport=httpx.MockTransport(lambda r:httpx.Response(200,json=token_payload(**changes)))) as auth:
        with pytest.raises(TikTokInvalidResponseError) as error:
            token=auth.exchange_code('code') if operation=='exchange' else auth.refresh('refresh')
            save_token(path,token)
    assert path.read_bytes()==b'TIKTOK_ACCESS_TOKEN=working\n' and path.stat().st_mtime_ns==before
    assert 'unsafe-secret' not in str(error.value)


def test_required_scope_and_refresh_identity():
    config=settings();config.tiktok_open_id='another'
    with TikTokAuth(config,transport=httpx.MockTransport(lambda r:httpx.Response(200,json=token_payload(scope='user.info.basic')))) as auth:
        with pytest.raises(TikTokPermissionError): auth.exchange_code('code')
    with TikTokAuth(config,transport=httpx.MockTransport(lambda r:httpx.Response(200,json=token_payload()))) as auth:
        with pytest.raises(TikTokIdentityError): auth.refresh('refresh')


def test_storage_revalidates_constructed_token(tmp_path):
    from app.connectors.tiktok.schemas import Token
    path=tmp_path/'.env';path.write_text('unchanged')
    invalid=Token.model_construct(**{**token_payload(),'access_token':SecretStr(''),'refresh_token':SecretStr('refresh')})
    with pytest.raises(TikTokInvalidResponseError): save_token(path,invalid)
    assert path.read_text()=='unchanged'


@pytest.mark.parametrize('uri',['http://example.com/callback','https://localhost/callback','https://example.com/callback?q=1','https://127.0.0.1/callback'])
def test_invalid_redirect(uri):
    config=settings();config.tiktok_redirect_uri=uri
    with TikTokAuth(config) as auth:
        with pytest.raises(ValueError): auth.authorization_url(OAuthState())


def test_web_callback_keeps_documented_scopes_and_meta_fragment_support():
    from app.cli.instagram_auth import parse_redirect
    state=OAuthState()
    assert parse_redirect(settings().tiktok_redirect_uri+'?code=test-code&state='+state.value+'&scopes=video.list',settings().tiktok_redirect_uri,state,allowed_extra=('scopes',))=='test-code'


INVALID_GRANTS=['user.info.basic,user.info.profile,video.list,video.publish','user.info.basic,user.info.profile,video.list,unknown.scope','','user.info.basic,user.info.profile,video.list,',',user.info.basic,user.info.profile,video.list','user.info.basic,,user.info.profile,video.list','user.info.basic,user.info.profile,video.list,video.list','user.info.basic, user.info.profile,video.list','user.info.basic;user.info.profile;video.list','user.info.basic,user.info.profile,video.list\n']


@pytest.mark.parametrize('scope',INVALID_GRANTS)
@pytest.mark.parametrize('operation',['exchange','refresh','save_constructed','save_mutated'])
def test_read_only_grant_guard_rejects_before_storage(scope,operation,tmp_path,caplog):
    from app.connectors.tiktok.errors import TikTokError
    from app.connectors.tiktok.schemas import Token
    path=tmp_path/'.env';path.write_bytes(b'TIKTOK_ACCESS_TOKEN=working\n');before=path.stat().st_mtime_ns
    with pytest.raises(TikTokError) as error:
        if operation.startswith('save'):
            token=Token.model_construct(**token_payload(scope=scope)) if operation=='save_constructed' else Token.model_validate(token_payload())
            if operation=='save_mutated':token.scope=scope
        else:
            with TikTokAuth(settings(),transport=httpx.MockTransport(lambda r:httpx.Response(200,json=token_payload(scope=scope)))) as auth:
                token=auth.exchange_code('private-code') if operation=='exchange' else auth.refresh('private-refresh')
        save_token(path,token)
    assert path.read_bytes()==b'TIKTOK_ACCESS_TOKEN=working\n' and path.stat().st_mtime_ns==before
    assert all(s not in str(error.value)+caplog.text for s in ('test-access','test-refresh','private-code','private-refresh','unknown.scope','video.publish'))


@pytest.mark.parametrize('scope',['user.info.basic,user.info.profile,video.list','video.list,user.info.stats,user.info.profile,user.info.basic'])
def test_read_only_grants_preserved_exactly_and_stats_optional(scope,tmp_path):
    path=tmp_path/'.env'
    with TikTokAuth(settings(),transport=httpx.MockTransport(lambda r:httpx.Response(200,json=token_payload(scope=scope)))) as auth:token=auth.refresh('fake-refresh')
    save_token(path,token)
    assert token.scope==scope and f"TIKTOK_SCOPES='{scope}'" in path.read_text()
