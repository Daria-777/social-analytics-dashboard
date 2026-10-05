from datetime import datetime, timezone
import pytest
from app.config import Settings
from tests.test_tiktok_credentials import seed


@pytest.mark.parametrize('valid', [True, False])
def test_dashboard_readiness_uses_selected_private_store_without_refresh(client, tmp_path, monkeypatch, valid):
    path = tmp_path / '.tiktok-credentials'
    if valid:
        seed(path, issued_at=datetime.now(timezone.utc))
    settings = Settings(_env_file=None, tiktok_credential_store=path,
                        tiktok_access_token=None if valid else 'stale-legacy-access',
                        tiktok_auto_refresh_enabled=True)
    monkeypatch.setattr('app.dashboard_api.Settings', lambda: settings)
    response = client.get('/dashboard/config')
    assert response.status_code == 200
    assert response.json()['tiktok_ready'] is valid
    assert 'test-access' not in response.text and 'stale-legacy-access' not in response.text
