"""Provider calls are mocked; callback HTTP is restricted to an isolated loopback port."""
import hashlib
import http.client
import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit, urlencode
import httpx
import pytest
from app.config import Settings
from app.connectors.tiktok.auth import TikTokAuth, OAuthState
from tests.test_tiktok_auth import token_payload


def desktop_settings(port=8765, **changes):
    return Settings(_env_file=None, tiktok_client_key='desktop-test-key', tiktok_client_secret='desktop-test-secret', tiktok_oauth_mode='desktop', tiktok_redirect_uri=f'http://127.0.0.1:{port}/tiktok/callback/', **changes)


@pytest.mark.parametrize('uri', ['http://127.0.0.1:8765/tiktok/callback/', 'http://localhost:8765/tiktok/callback/'])
def test_desktop_settings_accept_only_explicit_loopback_mode(uri):
    config=desktop_settings();config.tiktok_redirect_uri=uri
    config.require_tiktok_oauth()
    config.tiktok_oauth_mode='web'
    with pytest.raises(ValueError):config.require_tiktok_oauth()


@pytest.mark.parametrize('uri', ['http://example.com:8765/callback/', 'http://0.0.0.0:8765/callback/', 'http://127.0.0.2:8765/callback/', 'http://[::1]:8765/callback/', 'http://127.0.0.1/callback/', 'http://localhost:0/callback/', 'http://localhost:*/callback/', 'http://localhost:65536/callback/', 'http://user:password@localhost:8765/callback/', 'http://localhost:8765/callback/?x=1', 'http://localhost:8765/callback/#x', 'http://localhost.evil.test:8765/callback/', 'https://127.0.0.1:8765/callback/'])
def test_desktop_rejects_unsafe_or_unimplemented_callback(uri):
    config=desktop_settings();config.tiktok_redirect_uri=uri
    with pytest.raises(ValueError): config.require_tiktok_oauth()


def test_desktop_hex_pkce_and_exchange_binding(caplog):
    from app.connectors.tiktok.auth import DesktopPKCE
    pkce=DesktopPKCE();other=DesktopPKCE();state=OAuthState()
    verifier=pkce.verifier.get_secret_value()
    assert verifier!=other.verifier.get_secret_value() and 43<=len(verifier)<=128
    forms=[]
    def provider(request):
        forms.append(parse_qs(request.content.decode()))
        return httpx.Response(200,json=token_payload())
    with TikTokAuth(desktop_settings(),transport=httpx.MockTransport(provider)) as auth:
        authorization_url=auth.authorization_url(state,pkce=pkce)
        query=parse_qs(urlsplit(authorization_url).query)
        assert query['code_challenge']==[hashlib.sha256(verifier.encode()).hexdigest()]
        assert query['code_challenge_method']==['S256']
        assert set(query['scope'][0].split(','))=={'user.info.basic','user.info.profile','user.info.stats','video.list'}
        assert verifier not in authorization_url
        with pytest.raises(ValueError):auth.exchange_code('test-code',pkce=pkce)  # Callback not consumed yet.
        state.consume(state.value)
        with pytest.raises(ValueError):auth.exchange_code('test-code',pkce=other)
        token=auth.exchange_code('test-code',pkce=pkce)
        assert token.open_id=='test-open'
        with pytest.raises(ValueError):auth.exchange_code('test-code',pkce=pkce)
    assert len(forms)==1 and forms[0]['code_verifier']==[verifier]
    assert forms[0]['redirect_uri']==['http://127.0.0.1:8765/tiktok/callback/']
    assert verifier not in caplog.text and 'test-code' not in caplog.text


def test_web_remains_without_pkce_and_cannot_accept_desktop_proof():
    from app.connectors.tiktok.auth import DesktopPKCE
    config=Settings(_env_file=None,tiktok_client_key='test',tiktok_client_secret='secret',tiktok_redirect_uri='https://example.com/callback')
    calls=[]
    with TikTokAuth(config,transport=httpx.MockTransport(lambda r:calls.append(r) or httpx.Response(200,json=token_payload()))) as auth:
        assert 'code_challenge' not in parse_qs(urlsplit(auth.authorization_url(OAuthState())).query)
        with pytest.raises(ValueError):auth.exchange_code('code',pkce=DesktopPKCE())
    assert not calls


@pytest.mark.parametrize('suffix', ['?code=test-code&state=wrong-secret', '?code=test-code&state={state}&state={state}', '?code=test-code&code=other-secret&state={state}', '?code=&state={state}', '?error=denied&error_description=secret-description&state={state}', '?code=test-code&state={state}#fragment'])
def test_desktop_callback_rejects_invalid_without_secret_errors(suffix):
    from app.cli.tiktok_desktop import parse_desktop_redirect
    state=OAuthState();uri=desktop_settings().tiktok_redirect_uri
    with pytest.raises(ValueError) as error:parse_desktop_redirect(uri+suffix.format(state=state.value),uri,state)
    assert all(secret not in str(error.value) for secret in ('test-code','wrong-secret','other-secret','secret-description',state.value))


def test_callback_path_mode_state_are_exact_and_single_use():
    from app.cli.tiktok_desktop import parse_desktop_redirect,DesktopCallback
    config=desktop_settings();state=OAuthState()
    with pytest.raises(ValueError):parse_desktop_redirect(config.tiktok_redirect_uri.rstrip('/')+'?code=c&state='+state.value,config.tiktok_redirect_uri,state)
    assert not state.used
    assert parse_desktop_redirect(config.tiktok_redirect_uri+'?'+urlencode({'code':'test/code=decoded','state':state.value}),config.tiktok_redirect_uri,state)=='test/code=decoded'
    with pytest.raises(ValueError):parse_desktop_redirect(config.tiktok_redirect_uri+'?code=c&state='+state.value,config.tiktok_redirect_uri,state)
    config.tiktok_oauth_mode='web'
    with pytest.raises(ValueError):DesktopCallback(config,OAuthState())


@pytest.fixture
def loopback_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));return probe.getsockname()[1]


def request(port,path,host=None):
    connection=http.client.HTTPConnection('127.0.0.1',port,timeout=2)
    try:
        connection.request('GET',path,headers={'Host':host or f'127.0.0.1:{port}'})
        response=connection.getresponse();body=response.read().decode();return response.status,body
    finally:connection.close()


def test_loopback_server_binds_exact_host_closes_on_success_and_never_logs(loopback_port,capsys):
    from app.cli.tiktok_desktop import DesktopCallback
    state=OAuthState();result=[]
    with DesktopCallback(desktop_settings(loopback_port),state,timeout=2) as callback:
        assert callback.server.server_address==('127.0.0.1',loopback_port)
        worker=threading.Thread(target=lambda:result.append(callback.wait()));worker.start()
        assert request(loopback_port,'/wrong/?code=secret-untrusted')[0]==404
        assert not state.used
        assert request(loopback_port,'/tiktok/callback/?code=secret-untrusted',host='evil.test')[0]==400
        status,body=request(loopback_port,'/tiktok/callback/?'+urlencode({'code':'test-code-secret','state':state.value}))
        assert status==200 and 'test-code-secret' not in body and state.value not in body
        worker.join(2);assert not worker.is_alive() and result==['test-code-secret']
    assert callback.server.fileno()==-1 and not callback.timer.is_alive()
    output=capsys.readouterr();assert 'test-code-secret' not in output.out+output.err and state.value not in output.out+output.err


def test_timeout_closes_even_a_stalled_request(loopback_port):
    from app.cli.tiktok_desktop import DesktopCallback
    failures=[]
    with DesktopCallback(desktop_settings(loopback_port),OAuthState(),timeout=.15) as callback:
        def wait():
            try:callback.wait()
            except TimeoutError:failures.append('timeout')
        worker=threading.Thread(target=wait);worker.start()
        with socket.create_connection(('127.0.0.1',loopback_port),timeout=1) as stalled:
            stalled.sendall(b'GET /tiktok/callback/?code=hidden-code HTTP/1.1\r\nHost: ')
            worker.join(2)
        assert not worker.is_alive() and failures==['timeout']
    assert callback.server.fileno()==-1 and not callback.timer.is_alive()


def test_occupied_port_fails_without_fallback(loopback_port):
    from app.cli.tiktok_desktop import DesktopCallback
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1',loopback_port));occupied.listen(1)
        with pytest.raises(OSError):
            with DesktopCallback(desktop_settings(loopback_port),OAuthState()):pass


@pytest.mark.parametrize('failure', ['timeout','denied','bind','invalid_token','cancel'])
def test_desktop_cli_failure_preserves_env_and_closes(monkeypatch,tmp_path,capsys,failure):
    from app.cli import tiktok_auth as cli
    from app.connectors.tiktok.errors import TikTokInvalidResponseError
    path=tmp_path/'.env';path.write_text('TIKTOK_ACCESS_TOKEN=working-test-token\n')
    before=path.read_bytes();events=[]
    monkeypatch.setattr(cli,'Settings',lambda **_:desktop_settings())
    class Callback:
        def __init__(self,settings,state,**kwargs):self.state=state
        def __enter__(self):
            if failure=='bind':raise OSError('private-bind-detail')
            events.append('open');return self
        def __exit__(self,*_):events.append('closed')
        def wait(self):
            if failure=='timeout':raise TimeoutError('private-timeout-detail')
            if failure=='denied':raise ValueError('private-denial-detail')
            if failure=='cancel':raise KeyboardInterrupt()
            self.state.consume(self.state.value);return 'private-code'
    monkeypatch.setattr(cli,'DesktopCallback',Callback)
    def exchange(self,code,**kwargs):
        assert events[-1]=='closed'
        raise TikTokInvalidResponseError('oauth','invalid_token')
    monkeypatch.setattr(cli.TikTokAuth,'exchange_code',exchange)
    assert cli.main(['--env-file',str(path),'--mode','desktop'])==1
    assert path.read_bytes()==before
    assert events==([] if failure=='bind' else ['open','closed'])
    output=capsys.readouterr()
    assert all(value not in output.out+output.err for value in ('private-code','private-bind-detail','private-timeout-detail','private-denial-detail','working-test-token','desktop-test-secret'))
    if failure=='bind':assert 'https://www.tiktok.com' not in output.out


def test_desktop_cli_success_and_refresh_have_separate_lifecycles(monkeypatch,tmp_path):
    from app.cli import tiktok_auth as cli
    from app.connectors.tiktok.schemas import Token
    path=tmp_path/'.env';path.write_text('OTHER=preserved\n')
    config=desktop_settings(tiktok_refresh_token='test-refresh');events=[]
    monkeypatch.setattr(cli,'Settings',lambda **_:config)
    class Callback:
        def __init__(self,settings,state,**kwargs):self.state=state
        def __enter__(self):events.append('open');return self
        def __exit__(self,*_):events.append('closed')
        def wait(self):self.state.consume(self.state.value);return 'test-code'
    monkeypatch.setattr(cli,'DesktopCallback',Callback)
    def exchange(self,code,**kwargs):
        assert events==['open','closed'] and kwargs['pkce'] is not None
        return Token.model_validate(token_payload())
    monkeypatch.setattr(cli.TikTokAuth,'exchange_code',exchange)
    assert cli.main(['--env-file',str(path),'--mode','desktop'])==0
    assert path.stat().st_mode & 0o777==0o600 and 'OTHER=preserved' in path.read_text()
    events.clear()
    monkeypatch.setattr(cli.TikTokAuth,'refresh',lambda self,token:Token.model_validate(token_payload(refresh_token='rotated-test')))
    assert cli.main(['--env-file',str(path),'--mode','desktop','--refresh'])==0
    assert events==[] and 'rotated-test' in path.read_text()


def test_desktop_exchange_rejects_changed_mode_uri_and_expiry():
    from app.connectors.tiktok.auth import DesktopPKCE
    for mutation in ('mode','uri','expiry'):
        config=desktop_settings();state=OAuthState();pkce=DesktopPKCE();calls=[]
        with TikTokAuth(config,transport=httpx.MockTransport(lambda r:calls.append(r) or httpx.Response(200,json=token_payload()))) as auth:
            auth.authorization_url(state,pkce=pkce);state.consume(state.value)
            if mutation=='mode':config.tiktok_oauth_mode='web'
            elif mutation=='uri':config.tiktok_redirect_uri='http://127.0.0.1:8766/tiktok/callback/'
            else:state.deadline=time.monotonic()-1
            with pytest.raises(ValueError):auth.exchange_code('test-code',pkce=pkce)
        assert calls==[]


def test_malformed_http_and_denial_do_not_echo_oauth_data(loopback_port,capsys):
    from app.cli.tiktok_desktop import DesktopCallback
    state=OAuthState();failures=[]
    with DesktopCallback(desktop_settings(loopback_port),state,timeout=2) as callback:
        def wait():
            try:callback.wait()
            except ValueError:failures.append('rejected')
        worker=threading.Thread(target=wait);worker.start()
        with socket.create_connection(('127.0.0.1',loopback_port),timeout=1) as malformed:
            malformed.sendall(b'GET /tiktok/callback/?code=private-malformed-secret BAD-VERSION\r\n\r\n')
            assert b'private-malformed-secret' not in malformed.recv(8192)
        status,body=request(loopback_port,'/tiktok/callback/?'+urlencode({'error':'denied','error_description':'private-denial-secret','state':state.value}))
        assert status==400 and 'private-denial-secret' not in body
        worker.join(2);assert failures==['rejected'] and not worker.is_alive()
    output=capsys.readouterr();assert 'private-malformed-secret' not in output.out+output.err and 'private-denial-secret' not in output.out+output.err
    assert callback.server.fileno()==-1
