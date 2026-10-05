from uuid import uuid4
import pytest


def test_null_zero_and_anomaly_are_preserved(client, content):
    payload = {"content_id": content["id"], "snapshot_at": "2026-10-03T13:52:00+03:00", "source": "tiktok_studio", "views": 0, "unique_viewers": 2, "watch_time_avg_seconds": 15.78, "snapshot_status": "anomalous", "raw_payload": {"views": 0, "ui": "--"}}
    response = client.post("/content-snapshots", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["views"] == 0
    assert data["unique_viewers"] == 2
    assert float(data["watch_time_avg_seconds"]) == 15.78
    assert data["likes"] is None
    assert data["raw_payload"] == payload["raw_payload"]
    assert data["snapshot_at"] == "2026-10-03T10:52:00Z"


def test_history_keeps_sources_and_old_rows(client, content):
    for source, views, time in [("tiktok_api", 856, "13:52"), ("tiktok_studio", 887, "13:52"), ("tiktok_api", 900, "14:52")]:
        result = client.post("/content-snapshots", json={"content_id": content["id"], "snapshot_at": f"2026-10-03T{time}:00+03:00", "source": source, "views": views})
        assert result.status_code == 201
    history = client.get(f'/content/{content["id"]}/history').json()
    assert len(history) == 3
    assert sorted(row["views"] for row in history) == [856, 887, 900]
    filtered = client.get(f'/content/{content["id"]}/history', params={"source": "tiktok_api", "date_to": "2026-10-03T11:00:00Z"}).json()
    assert [row["views"] for row in filtered] == [856]


def test_content_is_unique_per_platform(client, content):
    response = client.post("/content", json={"account_id": content["account_id"], "platform": "tiktok", "platform_content_id": "test-video", "content_type": "video"})
    assert response.status_code == 409


def test_rejects_platform_mismatch(client, content):
    response = client.post("/content", json={"account_id": content["account_id"], "platform": "instagram", "platform_content_id": "other", "content_type": "reel"})
    assert response.status_code == 422


@pytest.mark.parametrize("patch", [{"snapshot_at": "2026-10-03T13:52:00"}, {"views": -1}, {"completion_rate": 101}, {"source": "instagram_api"}, {"views": "--"}])
def test_rejects_invalid_snapshot(client, content, patch):
    payload = {"content_id": content["id"], "snapshot_at": "2026-10-03T13:52:00+03:00", "source": "tiktok_api"}
    assert client.post("/content-snapshots", json=payload | patch).status_code == 422


def test_unknown_parent_is_404(client):
    assert client.post("/content-snapshots", json={"content_id": str(uuid4()), "snapshot_at": "2026-10-03T10:00:00Z", "source": "manual"}).status_code == 404


def test_account_snapshot_and_period(client, content):
    payload = {"account_id": content["account_id"], "snapshot_at": "2026-10-03T10:00:00Z", "source": "tiktok_studio", "source_period_start": "2026-09-29T00:00:00Z", "source_period_end": "2026-10-03T00:00:00Z", "followers": 0}
    result = client.post("/account-snapshots", json=payload)
    assert result.status_code == 201
    assert result.json()["followers"] == 0
    assert result.json()["profile_views"] is None
    history = client.get(f'/accounts/{content["account_id"]}/history').json()
    assert len(history) == 1
    assert history[0]["source_period_start"] == payload["source_period_start"]
    payload["source_period_end"] = "2026-09-01T00:00:00Z"
    assert client.post("/account-snapshots", json=payload).status_code == 422


def test_experiment_link(client, content):
    result = client.post("/experiments", json={"name": "Concrete hook", "hypothesis": "Concrete conflict may improve retention", "metric": "completion_rate"})
    assert result.status_code == 201
    payload = {"content_id": content["id"], "experiment_id": result.json()["id"], "variant": "A"}
    assert client.post("/content-experiments", json=payload).status_code == 201
    assert client.post("/content-experiments", json=payload).status_code == 409


def test_snapshot_mutations_are_not_exposed(client, content):
    for method in (client.patch, client.put, client.delete):
        assert method(f'/content-snapshots/{uuid4()}').status_code in (404, 405)


def test_authentication_required(client):
    client.headers.pop("X-API-Key")
    assert client.post("/accounts", json={}).status_code == 401


def test_unknown_fields_rejected(client, content):
    assert client.post("/content-snapshots", json={"content_id": content["id"], "snapshot_at": "2026-10-03T10:00:00Z", "source": "manual", "viral_score": 90}).status_code == 422


def test_same_id_allowed_on_different_platform(client, content):
    account = client.post("/accounts", json={"platform": "instagram", "username": "demo.account", "platform_account_id": "test-instagram"}).json()
    response = client.post("/content", json={"account_id": account["id"], "platform": "instagram", "platform_content_id": "test-video", "content_type": "reel", "hook_type": "conflict"})
    assert response.status_code == 201
    assert response.json()["hook_type"] == "conflict"
    assert response.json()["series"] is None


def test_history_filters_require_aware_ordered_dates(client, content):
    path = f'/content/{content["id"]}/history'
    assert client.get(path, params={"date_from": "2026-10-03T10:00:00"}).status_code == 422
    assert client.get(path, params={"date_from": "2026-10-04T00:00:00Z", "date_to": "2026-10-03T00:00:00Z"}).status_code == 422


def test_exact_timestamp_does_not_merge_sources_or_observations(client, content):
    payload = {"content_id": content["id"], "snapshot_at": "2026-10-03T10:00:00Z", "source": "manual", "views": 0}
    first = client.post("/content-snapshots", json=payload).json()
    second = client.post("/content-snapshots", json=payload | {"views": 2}).json()
    assert first["id"] != second["id"]
    history = client.get(f'/content/{content["id"]}/history').json()
    assert [row["views"] for row in history] == [0, 2]


def test_unconfigured_auth_fails_closed(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "")
    assert client.get("/accounts").status_code == 503
