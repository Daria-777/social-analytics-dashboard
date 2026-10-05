"""Only the isolated callback socket uses TCP; provider exchange is mocked."""
import threading
from urllib.parse import urlencode
import httpx
import pytest
from app.cli.loopback_callback import LoopbackCallback
from app.cli.instagram_auth import parse_redirect
from app.connectors.instagram.auth import OAuthState,InstagramAuth,SCOPES
from tests.test_instagram_auth import settings
from tests.test_tiktok_desktop import loopback_port,request


def test_https_callback_forwarded_only_to_dedicated_loopback(loopback_port):
    config=settings();config.instagram_redirect_uri='https://tunnel.example/instagram/callback/'
    state=OAuthState();results=[]
    with LoopbackCallback(f'http://127.0.0.1:{loopback_port}/instagram/callback/',config.instagram_redirect_uri,state,parse_redirect,timeout=2) as callback:
        worker=threading.Thread(target=lambda:results.append(callback.wait()));worker.start()
        assert request(loopback_port,'/accounts')[0]==404
        assert request(loopback_port,'/instagram/callback/?code=private-code',host='evil.example')[0]==400
        status,body=request(loopback_port,'/instagram/callback/?'+urlencode({'code':'private-code','state':state.value}))
        assert status==200 and 'private-code' not in body and state.value not in body
        worker.join(2);assert not worker.is_alive() and results==['private-code']
    assert callback.server.server_address==('127.0.0.1',loopback_port) and callback.server.fileno()==-1
    calls=[]
    def provider(request):
        calls.append(request)
        return httpx.Response(200,json={'access_token':'fake-short','permissions':list(SCOPES)} if len(calls)==1 else {'access_token':'fake-long','expires_in':123})
    with InstagramAuth(config,transport=httpx.MockTransport(provider)) as auth:
        assert auth.exchange_code(results[0]).access_token.get_secret_value()=='fake-long'
        assert set(auth.granted_scopes)==set(SCOPES)
    assert b'https%3A%2F%2Ftunnel.example%2Finstagram%2Fcallback%2F' in calls[0].content


@pytest.mark.parametrize('failure',['bind','timeout','cancel'])
def test_instagram_cli_listener_failure_preserves_env(monkeypatch,tmp_path,capsys,failure):
    from app.cli import instagram_auth as cli
    path=tmp_path/'.env';path.write_bytes(b'INSTAGRAM_ACCESS_TOKEN=working\n');events=[]
    monkeypatch.setattr(cli,'Settings',lambda **_:settings())
    class Callback:
        def __init__(self,*a,**k):pass
        def __enter__(self):
            if failure=='bind':raise OSError('private-detail')
            events.append('open');return self
        def __exit__(self,*_):events.append('closed')
        def wait(self):
            if failure=='timeout':raise TimeoutError('private-detail')
            raise KeyboardInterrupt()
    monkeypatch.setattr(cli,'LoopbackCallback',Callback)
    assert cli.main(['--env-file',str(path),'--callback-port','8766'])==1
    assert path.read_bytes()==b'INSTAGRAM_ACCESS_TOKEN=working\n'
    assert events==([] if failure=='bind' else ['open','closed'])
    output=capsys.readouterr();assert 'private-detail' not in output.out+output.err


def test_instagram_cli_success_closes_listener_before_exchange_and_records_grant(monkeypatch,tmp_path):
    from app.cli import instagram_auth as cli
    from app.connectors.instagram.schemas import Token
    path=tmp_path/'.env';path.write_text('OTHER=kept\n');events=[]
    monkeypatch.setattr(cli,'Settings',lambda **_:settings())
    class Callback:
        def __init__(self,local_uri,expected_uri,state,parser,**kwargs):self.state=state
        def __enter__(self):events.append('open');return self
        def __exit__(self,*_):events.append('closed')
        def wait(self):self.state.consume(self.state.value);return 'fake-code'
    monkeypatch.setattr(cli,'LoopbackCallback',Callback)
    def exchange(self,code):
        assert events==['open','closed']
        self.granted_scopes=SCOPES
        return Token(access_token='fake-long',expires_in=123)
    monkeypatch.setattr(cli.InstagramAuth,'exchange_code',exchange)
    assert cli.main(['--env-file',str(path),'--callback-port','8766'])==0
    assert 'INSTAGRAM_GRANTED_SCOPES=' in path.read_text() and 'OTHER=kept' in path.read_text()
    assert path.stat().st_mode & 0o777==0o600


def test_reserved_api_port_is_rejected_before_listener_or_exchange(monkeypatch,tmp_path):
    from app.cli import instagram_auth as cli
    monkeypatch.setattr(cli,'Settings',lambda **_:settings())
    monkeypatch.setattr(cli,'LoopbackCallback',lambda *a,**k:pytest.fail('Must not bind API port'))
    path=tmp_path/'.env';path.write_text('unchanged')
    assert cli.main(['--env-file',str(path),'--callback-port','8000'])==1
    assert path.read_text()=='unchanged'
