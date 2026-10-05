from app.dashboard_auth import session_token,valid_session


def test_cookie_expiration_and_key_rotation():
    token=session_token('test-only-key',100)
    assert valid_session(token,'test-only-key',now=99)
    assert not valid_session(token,'test-only-key',now=100)
    assert not valid_session(token,'different-key',now=99)
    assert not valid_session('bad','test-only-key',now=99)


def test_dashboard_no_secrets_cookie_auth_and_csrf(client,content):
    page=client.get('/dashboard')
    assert page.status_code==200 and 'test-only-key' not in page.text
    assert "frame-ancestors 'none'" in page.headers['Content-Security-Policy']
    client.headers.pop('X-API-Key')
    assert client.get('/accounts').status_code==401
    assert client.post('/dashboard/session',json={'api_key':'test-only-key'},headers={'Origin':'https://wrong.example'}).status_code==403
    response=client.post('/dashboard/session',json={'api_key':'test-only-key'},headers={'Origin':'http://testserver'})
    assert response.status_code==200
    cookie=response.headers['Set-Cookie']
    assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie and 'test-only-key' not in cookie
    assert client.get('/accounts').status_code==200
    assert client.patch(f"/content/{content['id']}/tags",json={'series':'csrf-attempt'}).status_code==403
    assert client.patch(f"/content/{content['id']}/tags",json={'series':'safe'},headers={'Origin':'http://testserver'}).status_code==200
    assert 'access_token' not in client.get('/dashboard/config').text
    assert client.post('/dashboard/logout',headers={'Origin':'http://testserver'}).status_code==200
    assert client.get('/accounts').status_code==401


def test_session_errors_do_not_echo_key(client):
    client.headers.pop('X-API-Key')
    response=client.post('/dashboard/session',json={'api_key':'do-not-echo-this'},headers={'Origin':'http://testserver'})
    assert response.status_code==401 and 'do-not-echo-this' not in response.text
    assert client.get('/dashboard/assets/../config.py').status_code==404


def test_dashboard_assets_allowlist_and_script_modules(client):
    page=client.get('/dashboard')
    assert 'type="module"' in page.text
    for name in ('dashboard.js','dashboard-core.js','dashboard-detail.js','dashboard-forms.js','dashboard-preview.js','dashboard-presentation.js','dashboard-charts.js','platform-instagram.svg','platform-tiktok.svg','collection-automatic.svg','collection-manual.svg','dashboard.css','favicon.svg'):
        response=client.get('/dashboard/assets/'+name)
        assert response.status_code==200 and response.content
        assert response.headers['X-Content-Type-Options']=='nosniff'
    assert client.get('/dashboard/assets/config.py').status_code==422
    icon=client.get('/favicon.ico')
    assert icon.status_code==200 and icon.headers['content-type'].startswith('image/svg+xml')
    assert '/dashboard/assets/favicon.svg' in page.text


def test_experiment_patch_validates_before_any_write(client,content):
    row=client.post('/experiments',json={'name':'test experiment','started_at':'2026-10-03T12:00:00Z'}).json()
    assert client.patch('/experiments/'+row['id'],json={'ended_at':'2026-10-02T12:00:00Z','name':'should not save'}).status_code==422
    assert client.get('/experiments').json()[0]['name']=='test experiment'
    assert client.patch('/experiments/'+row['id'],json={'status':'running'}).status_code==200
    assert client.post('/content-experiments',json={'content_id':content['id'],'experiment_id':row['id'],'variant':'B'}).status_code==201
    linked=client.get('/content/'+content['id']+'/experiments').json()
    assert linked['links'][0]['variant']=='B'
    assert linked['links'][0]['experiment']['status']=='running'


def test_run_history_exposes_safe_counters_only(client):
    from uuid import uuid4
    from datetime import datetime,timezone
    from app.models import CollectorRun
    from app.database import get_session
    dependency=client.app.dependency_overrides[get_session]
    generator=dependency();db=next(generator)
    try:
        db.add(CollectorRun(id=uuid4(),platform='instagram',started_at=datetime.now(timezone.utc),status='failed',error_message_safe='private provider detail',summary={'content_snapshots':0,'raw_payload':{'access_token':'not-to-be-returned'}}));db.commit()
    finally:
        generator.close()
    response=client.get('/collectors/runs').json()[0]
    assert response['summary']['content_snapshots']==0
    assert 'private provider detail' not in str(response)
    assert 'not-to-be-returned' not in str(response)
    assert client.get('/collectors/runs?limit=501').status_code==422


def test_trusted_proxy_secure_cookie_and_csrf(client,content):
    import asyncio,httpx
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    from app.dashboard_auth import COOKIE
    async def scenario():
        wrapped=ProxyHeadersMiddleware(client.app,trusted_hosts=['172.30.252.2'])
        trusted=httpx.ASGITransport(app=wrapped,client=('172.30.252.2',1234))
        async with httpx.AsyncClient(transport=trusted,base_url='http://dash.test') as proxy:
            headers={'Origin':'https://dash.test','X-Forwarded-Proto':'https'}
            response=await proxy.post('/dashboard/session',json={'api_key':'test-only-key'},headers=headers)
            assert response.status_code==200 and '; Secure' in response.headers['set-cookie']
            headers['Cookie']=COOKIE+'='+response.cookies[COOKIE]
            assert (await proxy.patch('/content/'+content['id']+'/tags',json={'series':'proxy-safe'},headers=headers)).status_code==200
            assert (await proxy.patch('/content/'+content['id']+'/tags',json={'series':'forged-origin'},headers={**headers,'Origin':'https://evil.test'})).status_code==403
        untrusted=httpx.ASGITransport(app=wrapped,client=('203.0.113.10',1234))
        async with httpx.AsyncClient(transport=untrusted,base_url='http://dash.test') as direct:
            # A client outside the proxy allowlist cannot change request.scheme.
            assert (await direct.post('/dashboard/session',json={'api_key':'test-only-key'},headers={'Origin':'https://dash.test','X-Forwarded-Proto':'https'})).status_code==403
    asyncio.run(scenario())


def test_server_template_exposes_only_proxy():
    import json
    from pathlib import Path
    config=json.loads(Path('compose.server.yaml').read_text())
    services=config['services']
    assert {name for name,s in services.items() if s.get('ports')}=={'proxy'}
    assert services['scheduler']['profiles']==['scheduler']
    assert services['proxy']['networks']['edge']['ipv4_address']=='${DASH_PROXY_IP:-172.30.252.2}'
    command=services['api']['command']
    assert command[command.index('--forwarded-allow-ips')+1]=='${DASH_PROXY_IP:-172.30.252.2}'
    assert 'edge' not in services['db']['networks']
    assert 'postgres_data:/var/lib/postgresql/data' in services['db']['volumes']


import pytest
@pytest.mark.parametrize('platform',['instagram','tiktok'])
def test_provider_expiry_is_visible_in_existing_status(client,monkeypatch,platform,caplog):
    from uuid import uuid4
    import httpx
    from app.collectors_api import get_instagram_http,get_tiktok_http
    from app.connectors.instagram.client import InstagramClient
    from app.connectors.tiktok.client import TikTokClient
    from app.cli import secret_env
    def no_write(*args,**kwargs): raise AssertionError('Collector must not refresh/write credentials')
    monkeypatch.setattr(secret_env,'save_env',no_write)
    token='test-only-expired-provider-token'
    monkeypatch.setenv(platform.upper()+'_ACCESS_TOKEN',token)
    if platform=='instagram':
        payload={'error':{'code':190,'message':token,'type':'OAuthException'}}
        http=InstagramClient(token,'v26.0',transport=httpx.MockTransport(lambda r:httpx.Response(401,json=payload)),max_retries=0)
        dependency=get_instagram_http;kind='InstagramAuthError'
    else:
        payload={'error':{'code':'access_token_invalid','message':token}}
        http=TikTokClient(token,transport=httpx.MockTransport(lambda r:httpx.Response(401,json=payload)),max_retries=0)
        dependency=get_tiktok_http;kind='TikTokAuthError'
    client.app.dependency_overrides[dependency]=lambda:http
    try:
        result=client.post('/collectors/'+platform+'/run',json={'run_id':str(uuid4())}).json()
        assert result['status']=='failed' and result['content_snapshots']==0
        status=client.get('/collectors/status').json()[platform]
        assert status['last_status']=='failed' and status['last_error_type']==kind
        assert status['last_success_at'] is None
        history=client.get('/collectors/runs').json()
        assert history[0]['error_type']==kind
        assert token not in str(result)+str(status)+str(history)+caplog.text
    finally:
        client.app.dependency_overrides.pop(dependency);http.close()


def test_remember_browser_has_bounded_signed_expiry_and_can_logout(client, monkeypatch):
    from app.dashboard_auth import COOKIE
    monkeypatch.setenv('DASHBOARD_SESSION_HOURS', '8')
    monkeypatch.setattr('app.dashboard_api.time.time', lambda: 100000)
    client.headers.pop('X-API-Key')
    for option, seconds in (({}, 8 * 3600), ({'remember_browser': False}, 8 * 3600), ({'remember_browser': True}, 30 * 86400)):
        response = client.post('/dashboard/session', json={'api_key': 'test-only-key', **option}, headers={'Origin': 'http://testserver'})
        assert response.status_code == 200
        token = response.cookies[COOKIE]
        assert int(token.split('.')[0]) == 100000 + seconds
        assert f'Max-Age={seconds}' in response.headers['set-cookie']
        assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=strict' in response.headers['set-cookie']
        assert valid_session(token, 'test-only-key', now=100000 + seconds - 1)
        assert not valid_session(token, 'test-only-key', now=100000 + seconds)
        assert not valid_session(token, 'rotated-test-key', now=100001)
        assert client.get('/accounts').status_code == 200
        assert client.post('/dashboard/logout', headers={'Origin': 'http://testserver'}).status_code == 200
        assert client.get('/accounts').status_code == 401
        # Send the cookie explicitly so rejection is proved by the server,
        # independent of the browser/client cookie jar expiry.
        with monkeypatch.context() as clock:
            clock.setattr('app.dashboard_api.time.time', lambda: 100000 + seconds)
            assert client.get('/accounts', headers={'Cookie': COOKIE + '=' + token}).status_code == 401


def test_remember_browser_rejects_ambiguous_flags_without_creating_session(client):
    for value in ('false', 'true', 1, None):
        response = client.post('/dashboard/session', json={'api_key': 'test-only-key', 'remember_browser': value}, headers={'Origin': 'http://testserver'})
        assert response.status_code == 422
        assert 'set-cookie' not in response.headers


def test_public_information_pages_match_current_read_only_app(client):
    client.headers.pop('X-API-Key')
    for route, title in (('/terms', 'Условия использования'), ('/privacy', 'Конфиденциальность')):
        response=client.get(route)
        assert response.status_code==200 and title in response.text
        assert 'text/html' in response.headers['content-type']
        assert 'test-only-key' not in response.text
        assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
        assert 'TikTok' in response.text and 'Instagram' in response.text
    privacy=client.get('/privacy').text
    assert 'защищённая сессия браузера' in ' '.join(privacy.split()) and '30 дней' in privacy
    assert '0700' not in privacy and '0600' not in privacy and 'flock' not in privacy
    assert 'автоматического удаления' in ' '.join(privacy.split())
    assert client.get('/accounts').status_code==401
