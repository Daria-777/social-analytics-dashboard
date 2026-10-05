from uuid import uuid4
import httpx
from app.collectors_api import get_instagram_http
from app.connectors.instagram.client import InstagramClient
from app.cli.collect_instagram import main
from app.config import Settings
from tests.test_instagram_service import handler


def test_collector_endpoints_auth_idempotency_status(client,monkeypatch):
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN","test-token")
    def mock_client():
        with InstagramClient("test-token","v26.0",transport=httpx.MockTransport(handler),max_retries=0) as http:
            yield http
    from app.main import app
    app.dependency_overrides[get_instagram_http]=mock_client
    try:
        empty=client.get("/collectors/status")
        assert empty.status_code==200
        assert empty.json()["instagram"]["last_status"] is None
        job=str(uuid4())
        first=client.post("/collectors/instagram/run",json={"run_id":job})
        assert first.status_code==200
        assert first.json()["status"]=="success"
        assert client.post("/collectors/instagram/run",json={"run_id":job}).json()==first.json()
        status=client.get("/collectors/status").json()["instagram"]
        assert status["last_status"]=="success"
        assert status["last_success_at"]
        assert "test-token" not in first.text
        assert client.post("/collectors/instagram/run",json={"access_token":"must-not-be-accepted"}).status_code==422
        client.headers.pop("X-API-Key")
        assert client.post("/collectors/instagram/run",json={}).status_code==401
        assert client.get("/collectors/status").status_code==401
    finally:
        app.dependency_overrides.pop(get_instagram_http,None)


def test_cli_dry_run_no_database(capsys):
    settings=Settings(_env_file=None,instagram_access_token="test-token")
    def forbidden(): raise AssertionError("Dry run opened DB")
    result=main(["--dry-run"],settings=settings,transport=httpx.MockTransport(handler),engine_factory=forbidden)
    assert result==0
    output=capsys.readouterr().out
    assert "Media discovered: 2" in output
    assert "test-token" not in output


def test_cli_missing_config_fails_safely(capsys):
    assert main([],settings=Settings(_env_file=None))==2
    assert "Configuration" in capsys.readouterr().err
