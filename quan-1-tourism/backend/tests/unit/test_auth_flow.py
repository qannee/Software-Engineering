import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.runtime_store import store


@pytest.fixture(autouse=True)
def clear_runtime_auth_state():
    store.audit.clear()
    store.revoked_tokens.clear()
    yield
    store.audit.clear()
    store.revoked_tokens.clear()


def test_login_logout_revokes_token_and_records_auth_events():
    with TestClient(app) as client:
        failed = client.post("/api/v1/admin/auth/login", json={"username": "admin", "password": "wrong-password"})
        assert failed.status_code == 401

        logged_in = client.post("/api/v1/admin/auth/login", json={"username": "admin", "password": "quan1-demo"})
        assert logged_in.status_code == 200
        token = logged_in.json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/v1/admin/auth/me", headers=auth).status_code == 200

        logged_out = client.post("/api/v1/admin/auth/logout", headers=auth)
        assert logged_out.status_code == 200
        assert client.get("/api/v1/admin/auth/me", headers=auth).status_code == 401

        fresh_login = client.post("/api/v1/admin/auth/login", json={"username": "admin", "password": "quan1-demo"})
        audit = client.get("/api/v1/admin/audit", headers={"Authorization": f"Bearer {fresh_login.json()['access_token']}"})
        actions = [item["action"] for item in audit.json()["data"]]
        assert "auth.login.failed" in actions
        assert "auth.login.succeeded" in actions
        assert "auth.logout" in actions

