from dotenv import dotenv_values


def test_setup_creates_private_local_credentials_without_provider_tokens(tmp_path, capsys):
    from app.cli.local_setup import main
    target = tmp_path / '.env'
    assert main(['--env-file', str(target)]) == 0
    values = dotenv_values(target)
    assert target.stat().st_mode & 0o777 == 0o600
    assert len(values['INTERNAL_API_KEY']) >= 32
    assert len(values['POSTGRES_PASSWORD']) >= 32
    assert values['POSTGRES_DB'] == 'dash'
    assert values['POSTGRES_PASSWORD'] in values['DATABASE_URL']
    assert values['SCHEDULER_ENABLED'] == 'false'
    assert values['INSTAGRAM_ACCESS_TOKEN'] == values['TIKTOK_ACCESS_TOKEN'] == ''
    output = capsys.readouterr().out
    assert values['INTERNAL_API_KEY'] not in output
    assert values['POSTGRES_PASSWORD'] not in output


def test_setup_preserves_existing_env(tmp_path, capsys):
    from app.cli.local_setup import main
    target = tmp_path / '.env'
    target.write_text('INTERNAL_API_KEY=existing-secret\n')
    before = target.read_bytes()
    mode = target.stat().st_mode
    assert main(['--env-file', str(target)]) == 0
    assert target.read_bytes() == before and target.stat().st_mode == mode
    assert 'existing-secret' not in capsys.readouterr().out


def test_copy_key_uses_stdin_not_arguments(tmp_path, monkeypatch, capsys):
    from app.cli.local_setup import main
    target = tmp_path / '.env'
    target.write_text('INTERNAL_API_KEY=test-hidden-owner-key\n')
    calls = []
    monkeypatch.setattr('app.cli.local_setup.subprocess.run', lambda *a, **kw: calls.append((a, kw)))
    assert main(['--env-file', str(target), '--copy-key']) == 0
    assert calls[0][0] == (['pbcopy'],)
    assert calls[0][1]['input'] == b'test-hidden-owner-key'
    assert 'test-hidden-owner-key' not in capsys.readouterr().out
