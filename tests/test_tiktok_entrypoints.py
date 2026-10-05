from uuid import uuid4
import httpx
from app.config import Settings
from app.collectors_api import get_tiktok_http
from app.connectors.tiktok.client import TikTokClient
from app.cli.collect_tiktok import main
from tests.test_tiktok_service import handler


def test_api_idempotency_and_status(client,monkeypatch):
    monkeypatch.setenv('TIKTOK_ACCESS_TOKEN','test-tiktok-token')
    def mock_client():
        with TikTokClient('test-tiktok-token',transport=httpx.MockTransport(handler)) as http: yield http
    from app.main import app
    app.dependency_overrides[get_tiktok_http]=mock_client
    try:
        job=str(uuid4());first=client.post('/collectors/tiktok/run',json={'run_id':job})
        assert first.status_code==200 and first.json()['status']=='success'
        assert client.post('/collectors/tiktok/run',json={'run_id':job}).json()==first.json()
        assert client.get('/collectors/status').json()['tiktok']['last_success_at']
        assert 'test-tiktok-token' not in first.text
        assert client.post('/collectors/tiktok/run',json={'access_token':'bad'}).status_code==422
        client.headers.pop('X-API-Key')
        assert client.post('/collectors/tiktok/run',json={}).status_code==401
    finally: app.dependency_overrides.pop(get_tiktok_http,None)


def test_cli_dry_run_and_missing_credentials(capsys):
    def forbidden(): raise AssertionError('Dry run opened DB')
    assert main(['--dry-run'],settings=Settings(_env_file=None,tiktok_access_token='test-tiktok-token'),transport=httpx.MockTransport(handler),engine_factory=forbidden)==0
    assert 'test-tiktok-token' not in capsys.readouterr().out
    assert main([],settings=Settings(_env_file=None))==2
