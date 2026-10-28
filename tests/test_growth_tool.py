import json
import httpx
import pytest


def test_growth_tool_allowlist_and_safe_failure(tmp_path,capsys):
    from app.cli.growth_tool import main
    config=tmp_path/'connection.json';config.write_text(json.dumps({'base_url':'https://dash.example','api_key':'only-growth-key'}));config.chmod(0o600)
    seen=[]
    def handle(request):
        seen.append(request)
        assert request.headers['X-API-Key']=='only-growth-key'
        return httpx.Response(200,json={'content_id':'test'})
    assert main(['--config',str(config),'resolve','--platform','tiktok','--platform-content-id','test-video'],transport=httpx.MockTransport(handle))==0
    assert json.loads(capsys.readouterr().out)['status']=='CONFIRMED'
    assert seen[0].url.path=='/growth/content/resolve'
    def failure(request):return httpx.Response(500,json={'detail':'only-growth-key secret backend exception'})
    assert main(['--config',str(config),'resolve','--platform','tiktok','--platform-content-id','test-video'],transport=httpx.MockTransport(failure))==1
    output=capsys.readouterr().out
    assert 'CONFIRMED' not in output and 'only-growth-key' not in output
    config.chmod(0o644)
    assert main(['--config',str(config),'resolve','--platform','tiktok','--platform-content-id','test-video'],transport=httpx.MockTransport(handle))==1
    config.chmod(0o600);config.write_text(json.dumps({'base_url':'http://dash.example','api_key':'only-growth-key'}))
    assert main(['--config',str(config),'resolve','--platform','tiktok','--platform-content-id','test-video'],transport=httpx.MockTransport(handle))==1
