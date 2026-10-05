import json
from app.config import Settings


def test_readiness_is_offline_and_hides_values(monkeypatch,capsys):
    from app.cli.readiness import main
    def forbidden(*a,**k): raise AssertionError('Readiness must not connect or write')
    import sqlalchemy,httpx
    monkeypatch.setattr(sqlalchemy,'create_engine',forbidden)
    monkeypatch.setattr(httpx.Client,'request',forbidden)
    config=Settings(_env_file=None,database_url='postgresql+psycopg://hidden-user:hidden-password@db/hidden-db',internal_api_key='hidden-key',instagram_access_token='hidden-ig',tiktok_access_token='hidden-tt',tiktok_refresh_token='hidden-refresh',dash_domain='hidden-domain.test')
    assert main([],settings=config)==0
    output=capsys.readouterr().out
    for value in ('hidden-user','hidden-password','hidden-db','hidden-key','hidden-ig','hidden-tt','hidden-refresh','hidden-domain.test'): assert value not in output
    report=json.loads(output)
    assert report['access_verified'] is False
    assert report['database']=='configured_not_connected'
    assert report['scheduler']=='disabled'
    assert any('dry-run' in step for step in report['next_steps'])


def test_missing_defaults_and_invalid_config_are_safe(capsys,tmp_path,monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("INTERNAL_API_KEY", raising=False)
    from app.cli.readiness import main
    assert main([],settings=Settings(_env_file=None))==2
    report=json.loads(capsys.readouterr().out)
    assert report['database']=='missing_explicit_url'
    assert report['instagram']['token']=='missing' and report['tiktok']['token']=='missing'
    assert any('INTERNAL_API_KEY' in step for step in report['next_steps'])
    env=tmp_path/'.env';env.write_text('INSTAGRAM_API_VERSION=hidden-invalid-value\n')
    before=env.read_bytes()
    assert main(['--env-file',str(env)])==2
    output=capsys.readouterr().out
    assert 'hidden-invalid-value' not in output and 'invalid' in output
    assert env.read_bytes()==before


def test_non_postgres_and_scheduler_dependency(capsys):
    from app.cli.readiness import main
    assert main([],settings=Settings(_env_file=None,database_url='sqlite:///test_dash',scheduler_enabled=True))==2
    report=json.loads(capsys.readouterr().out)
    assert report['database']=='postgresql_required'
    assert report['scheduler']=='enabled_config_incomplete'


def test_invalid_database_url_never_echoes_values(capsys):
    from app.cli.readiness import main
    assert main([],settings=Settings(_env_file=None,database_url='hidden-secret-url'))==2
    output=capsys.readouterr().out
    assert 'hidden-secret-url' not in output
    assert json.loads(output)['database']=='invalid_url'


def test_local_runtime_does_not_require_server_domain_or_provider_authorization(capsys):
    from app.cli.readiness import main
    config = Settings(_env_file=None, database_url='postgresql+psycopg://dash:fake@db/dash', internal_api_key='fake-private-key')
    assert main([], settings=config) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['configuration_complete'] is True
    assert report['access_verified'] is False
    assert report['instagram']['token'] == 'missing'
    assert main(['--server'], settings=config) == 2


def test_readiness_distinguishes_desktop_from_web_without_claiming_access():
    from app.cli.readiness import report
    config=Settings(_env_file=None,tiktok_client_key='fake',tiktok_client_secret='fake-secret',tiktok_oauth_mode='desktop',tiktok_redirect_uri='http://127.0.0.1:8765/tiktok/callback/')
    result=report(config)
    assert result['tiktok']['mode']=='desktop'
    assert result['tiktok']['callback']=='http_loopback_configuration_unverified'
    assert not result['access_verified']
    config.tiktok_oauth_mode='web';config.tiktok_redirect_uri='https://example.com/callback'
    assert report(config)['tiktok']['callback']=='public_https_configuration_unverified'


def test_private_store_readiness_is_offline_and_does_not_open_secret_file(tmp_path,monkeypatch):
    from app.cli.readiness import report
    from app.connectors.tiktok.credentials import CredentialStore
    monkeypatch.setattr(CredentialStore,'read',lambda *a:(_ for _ in ()).throw(AssertionError('Readiness must not read secrets')))
    config=Settings(_env_file=None,tiktok_credential_store=tmp_path/'.tiktok-credentials',tiktok_auto_refresh_enabled=True)
    result=report(config)
    assert result['tiktok']['token']=='private_store_unverified' and result['tiktok']['auto_refresh']=='enabled_configuration_unverified'
    assert result['network']=='not_attempted' and not result['access_verified']
