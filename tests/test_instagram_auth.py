from urllib.parse import parse_qs, urlsplit
import httpx
import pytest
from app.config import Settings
from app.connectors.instagram.auth import InstagramAuth, OAuthState
from app.connectors.instagram.errors import InstagramAuthError, InstagramPermissionError


def settings():
    return Settings(_env_file=None,instagram_client_id="123",instagram_client_secret="test-client-secret",instagram_redirect_uri="https://example.com/instagram/callback",instagram_api_version="v26.0")


def test_oauth_url_read_only_and_state():
    auth=InstagramAuth(settings())
    state=OAuthState()
    params=parse_qs(urlsplit(auth.authorization_url(state)).query)
    assert set(params["scope"][0].split(","))=={"instagram_business_basic","instagram_business_manage_insights"}
    assert params["state"]==[state.value]
    assert "publish" not in params["scope"][0]
    state.consume(state.value)
    with pytest.raises(ValueError): state.consume(state.value)


@pytest.mark.parametrize("state_value", ["wrong", ""])
def test_oauth_state_rejects_invalid(state_value):
    with pytest.raises(ValueError): OAuthState().consume(state_value)


def test_oauth_token_exchange_and_permissions(caplog):
    requests=[]
    def handler(request):
        requests.append(request)
        if request.url.host=="api.instagram.com":
            return httpx.Response(200,json={"data":[{"access_token":"short-secret", "user_id":"123", "permissions":"instagram_business_basic,instagram_business_manage_insights"}]})
        return httpx.Response(200,json={"access_token":"long-secret", "expires_in":5184000,"token_type":"bearer"})
    with InstagramAuth(settings(),transport=httpx.MockTransport(handler)) as auth:
        token=auth.exchange_code("one-use-code")
        assert token.access_token.get_secret_value()=="long-secret"
        assert token.expires_in==5184000
        assert "long-secret" not in repr(token)
    assert len(requests)==2
    assert all(secret not in caplog.text for secret in ("test-client-secret","short-secret","long-secret","one-use-code"))


def test_missing_permission_prevents_long_exchange():
    def handler(request): return httpx.Response(200,json={"data":[{"access_token":"secret","user_id":"123","permissions":"instagram_business_basic"}]})
    with InstagramAuth(settings(),transport=httpx.MockTransport(handler)) as auth:
        with pytest.raises(InstagramPermissionError): auth.exchange_code("code")


def test_expired_refresh():
    with InstagramAuth(settings(),transport=httpx.MockTransport(lambda r:httpx.Response(400,json={"error":{"code":190,"error_subcode":463,"message":"expired secret"}}))) as auth:
        with pytest.raises(InstagramAuthError): auth.refresh("secret")


def test_expired_oauth_state():
    state=OAuthState(ttl=-1)
    with pytest.raises(ValueError): state.consume(state.value)


def test_refresh_valid_response():
    with InstagramAuth(settings(),transport=httpx.MockTransport(lambda r:httpx.Response(200,json={"access_token":"renewed-secret","expires_in":5184000}))) as auth:
        assert auth.refresh("old-secret").access_token.get_secret_value()=="renewed-secret"


def test_oauth_exchange_has_no_automatic_retry():
    calls=[]
    def handler(request): calls.append(1);return httpx.Response(500,json={"error":{"code":2}})
    from app.connectors.instagram.errors import InstagramAPIError
    with InstagramAuth(settings(),transport=httpx.MockTransport(handler)) as auth:
        with pytest.raises(InstagramAPIError): auth.exchange_code("single-use-code")
    assert len(calls)==1


def test_token_env_storage_is_private_and_preserves_other_config(tmp_path):
    from app.cli.instagram_auth import save_token
    from app.connectors.instagram.schemas import Token
    target=tmp_path/".env"
    target.write_text("DATABASE_URL=sqlite:///test.db\nINSTAGRAM_ACCESS_TOKEN=old\n")
    save_token(target,Token(access_token="new-secret",expires_in=5184000))
    assert target.stat().st_mode & 0o777 == 0o600
    assert "DATABASE_URL=sqlite:///test.db" in target.read_text()
    assert target.read_text().count("INSTAGRAM_ACCESS_TOKEN=")==1
    assert "new-secret" in target.read_text()


def test_redirect_validation_rejects_wrong_host_or_state():
    from app.cli.instagram_auth import parse_redirect
    state=OAuthState()
    with pytest.raises(ValueError): parse_redirect(f"https://evil.example/callback?code=secret&state={state.value}",settings().instagram_redirect_uri,state)
    assert not state.used


@pytest.mark.parametrize("uri", ["http://example.com/callback","https://localhost/callback","https://127.0.0.1/callback"])
def test_oauth_refuses_insecure_or_private_redirects(uri):
    config=settings();config.instagram_redirect_uri=uri
    with InstagramAuth(config) as auth:
        with pytest.raises(ValueError): auth.authorization_url(OAuthState())


def test_secret_file_refuses_example_and_symlink(tmp_path):
    from app.cli.instagram_auth import save_token
    from app.connectors.instagram.schemas import Token
    token=Token(access_token="new-secret",expires_in=100)
    example=tmp_path/".env.example"
    with pytest.raises(ValueError): save_token(example,token)
    target=tmp_path/"target";target.write_text("unchanged")
    linked=tmp_path/".env";linked.symlink_to(target)
    with pytest.raises(ValueError): save_token(linked,token)
    assert target.read_text()=="unchanged"


@pytest.mark.parametrize("operation", ["exchange", "refresh"])
@pytest.mark.parametrize("invalid", ["", "   ", "wrong_type"])
def test_invalid_long_lived_response_is_safe_and_preserves_env(operation, invalid, tmp_path, caplog):
    from app.cli.instagram_auth import save_token
    from app.connectors.instagram.errors import InstagramInvalidResponseError
    target=tmp_path/".env";original=b"INSTAGRAM_ACCESS_TOKEN=working-secret\n"
    target.write_bytes(original)
    def responses(request):
        if request.url.host=="api.instagram.com":
            return httpx.Response(200,json={"access_token":"short-secret","permissions":"instagram_business_basic,instagram_business_manage_insights"})
        return httpx.Response(200,json={"access_token":invalid if invalid!="wrong_type" else "rejected-secret", "expires_in":100,"token_type":"unsafe-secret-type" if invalid=="wrong_type" else "bearer"})
    with InstagramAuth(settings(),transport=httpx.MockTransport(responses)) as auth:
        with pytest.raises(InstagramInvalidResponseError) as error:
            token=auth.exchange_code("one-use-secret") if operation=="exchange" else auth.refresh("working-secret")
            save_token(target,token)
    assert error.value.operation=="oauth_token_validation"
    assert target.read_bytes()==original
    assert all(secret not in str(error.value)+caplog.text for secret in ("working-secret","rejected-secret","unsafe-secret-type","one-use-secret"))


@pytest.mark.parametrize("value, token_type", [("", "bearer"), ("   ", "bearer"), ("rejected-secret", "invalid")])
def test_save_token_revalidates_before_any_write(tmp_path, value, token_type):
    from pydantic import SecretStr
    from app.cli.instagram_auth import save_token
    from app.connectors.instagram.schemas import Token
    from app.connectors.instagram.errors import InstagramInvalidResponseError
    target=tmp_path/".env";target.write_bytes(b"INSTAGRAM_ACCESS_TOKEN=working-secret\n");before=target.stat()
    token=Token.model_construct(access_token=SecretStr(value),expires_in=100,token_type=token_type)
    with pytest.raises(InstagramInvalidResponseError) as error: save_token(target,token)
    assert error.value.operation=="token_storage_validation"
    assert target.read_bytes()==b"INSTAGRAM_ACCESS_TOKEN=working-secret\n"
    assert target.stat().st_mtime_ns==before.st_mtime_ns
    assert not list(tmp_path.glob(".instagram-secret-*"))


@pytest.mark.parametrize('permissions', [
    'instagram_business_basic,instagram_business_manage_insights,instagram_business_content_publish',
    ['instagram_business_basic','instagram_business_manage_insights','instagram_business_manage_messages'],
    ['instagram_business_basic','instagram_business_manage_insights',{'unsafe':'private-secret'}],
])
def test_extra_or_malformed_grant_is_rejected_before_long_exchange(permissions,tmp_path):
    from app.cli.instagram_auth import save_token
    calls=[];path=tmp_path/'.env';path.write_bytes(b'INSTAGRAM_ACCESS_TOKEN=working\n')
    def provider(request):
        calls.append(request)
        return httpx.Response(200,json={'access_token':'private-short-secret','permissions':permissions})
    with InstagramAuth(settings(),transport=httpx.MockTransport(provider)) as auth:
        with pytest.raises(InstagramPermissionError) as error:save_token(path,auth.exchange_code('private-code'))
    assert len(calls)==1 and path.read_bytes()==b'INSTAGRAM_ACCESS_TOKEN=working\n'
    assert 'private-secret' not in str(error.value) and 'private-code' not in str(error.value)


def test_verified_grant_saved_atomically_and_refresh_preserves_inventory(tmp_path):
    from app.cli.instagram_auth import save_token
    from app.connectors.instagram.schemas import Token
    from app.connectors.instagram.auth import SCOPES
    path=tmp_path/'.env';path.write_text('OTHER=preserved\n')
    save_token(path,Token(access_token='fake-access',expires_in=123),granted_scopes=SCOPES)
    assert 'INSTAGRAM_GRANTED_SCOPES=' in path.read_text() and 'OTHER=preserved' in path.read_text()
    before=path.read_bytes()
    with pytest.raises(ValueError):save_token(path,Token(access_token='fake-access',expires_in=123),granted_scopes=(*SCOPES,'extra'))
    assert path.read_bytes()==before
    save_token(path,Token(access_token='refreshed',expires_in=123))
    assert 'INSTAGRAM_GRANTED_SCOPES=' in path.read_text() and path.stat().st_mode & 0o777==0o600


@pytest.mark.parametrize('suffix',['?code=c&state={state}&code=x','?code=c&state={state}#secret-fragment','?code=c&state={state}&error_description=secret','?code=&state={state}'])
def test_strict_manual_redirect_rejects_ambiguous_callbacks(suffix):
    from app.cli.instagram_auth import parse_redirect
    state=OAuthState()
    with pytest.raises(ValueError):parse_redirect(settings().instagram_redirect_uri+suffix.format(state=state.value),settings().instagram_redirect_uri,state)


def test_meta_documented_fragment_is_not_part_of_code():
    from app.cli.instagram_auth import parse_redirect
    state=OAuthState()
    assert parse_redirect(settings().instagram_redirect_uri+'?code=fake-code&state='+state.value+'#_',settings().instagram_redirect_uri,state)=='fake-code'
