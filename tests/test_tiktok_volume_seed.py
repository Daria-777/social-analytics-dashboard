"""Seed boundary tests use fake credentials and never launch Docker or HTTP."""
import json
from pathlib import Path
import pytest
from tools.seed_tiktok_volume import main


@pytest.fixture
def private_env(tmp_path):
    path = tmp_path / 'owner.env'
    path.write_text('''TIKTOK_ACCESS_TOKEN=fake-sensitive-access
TIKTOK_REFRESH_TOKEN=fake-sensitive-refresh
TIKTOK_OPEN_ID=fake-owner
TIKTOK_SCOPES=user.info.basic,user.info.profile,user.info.stats,video.list
TIKTOK_TOKEN_ISSUED_AT=2026-10-03T19:00:00+00:00
TIKTOK_TOKEN_EXPIRES_IN=86400
TIKTOK_REFRESH_EXPIRES_IN=31536000
''')
    path.chmod(0o600)
    return path


def arguments(path):
    return ['--env-file', str(path), '--confirm-owner', '--confirm-workers-stopped']


def test_no_confirmation_never_launches_docker(monkeypatch, private_env):
    monkeypatch.setattr('subprocess.check_output', lambda *a, **k: pytest.fail('Must not launch Docker'))
    assert main(['--env-file', str(private_env)]) == 1


@pytest.mark.parametrize('bad_input', ['mode', 'symlink', 'malformed', 'extra_scope', 'future_issuance'])
def test_invalid_private_input_never_launches_docker(monkeypatch, private_env, bad_input, capsys):
    if bad_input == 'mode': private_env.chmod(0o644)
    elif bad_input == 'symlink':
        link = private_env.with_name('link.env'); link.symlink_to(private_env); private_env = link
    elif bad_input == 'malformed': private_env.write_text(private_env.read_text().replace('86400', 'fake-sensitive-value'))
    elif bad_input == 'future_issuance': private_env.write_text(private_env.read_text().replace('2026-10-03', '2099-10-03'))
    else: private_env.write_text(private_env.read_text().replace('video.list', 'video.list,video.publish'))
    monkeypatch.setattr('subprocess.check_output', lambda *a, **k: pytest.fail('Must not launch Docker'))
    assert main(arguments(private_env)) == 1
    captured = capsys.readouterr()
    assert 'fake-sensitive' not in captured.out + captured.err


def test_active_workers_refuse_seed(monkeypatch, private_env):
    monkeypatch.setattr('subprocess.check_output', lambda *a, **k: b'running-api-id')
    monkeypatch.setattr('subprocess.run', lambda *a, **k: pytest.fail('Must not mutate running credentials'))
    assert main(arguments(private_env)) == 1


def test_only_token_fields_cross_stdin(monkeypatch, private_env, capsys):
    private_env.write_text(private_env.read_text() + 'POSTGRES_PASSWORD=fake-database-secret\n')
    before = private_env.read_bytes()
    calls = []
    monkeypatch.setattr('subprocess.check_output', lambda *a, **k: b'')
    monkeypatch.setattr('subprocess.run', lambda cmd, **kw: calls.append((cmd, kw)))
    assert main(arguments(private_env)) == 0
    payload = json.loads(calls[-1][1]['input'])
    assert payload['access_token'] == 'fake-sensitive-access'
    assert payload['owner_verified'] is True
    assert 'POSTGRES_PASSWORD' not in payload
    assert all('fake-sensitive' not in str(cmd) for cmd, _ in calls)
    assert private_env.read_bytes() == before
    captured = capsys.readouterr()
    assert 'fake-sensitive' not in captured.out + captured.err
