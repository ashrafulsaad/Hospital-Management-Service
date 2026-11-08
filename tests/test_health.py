import pytest


@pytest.mark.django_db
def test_health_is_public(client):
    res = client.get("/api/health/")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "database": "connected"}
