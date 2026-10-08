from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.runtime_store import store


@pytest.fixture(autouse=True)
def clear_user_state():
    store.users.clear()
    store.user_favorites.clear()
    store.revoked_tokens.clear()
    store.refresh_tokens.clear()
    yield
    store.users.clear()
    store.user_favorites.clear()
    store.revoked_tokens.clear()
    store.refresh_tokens.clear()


def test_registration_and_favorites_are_scoped_to_each_user():
    with TestClient(app) as client:
        first_name, second_name = f"guest-{uuid4().hex[:8]}", f"guest-{uuid4().hex[:8]}"
        first_password, second_password = "a-strong-password", "another-strong-password"
        first = client.post("/api/v1/auth/register", json={"username": first_name, "password": first_password})
        second = client.post("/api/v1/auth/register", json={"username": second_name, "password": second_password})
        assert first.status_code == second.status_code == 201

        first_auth = {"Authorization": f"Bearer {first.json()['access_token']}"}
        second_auth = {"Authorization": f"Bearer {second.json()['access_token']}"}
        poi_id = next(iter(store.pois))
        assert client.put(f"/api/v1/user/favorites/{poi_id}", headers=first_auth).status_code == 201
        assert client.get("/api/v1/user/favorites", headers=first_auth).json()["data"] == [poi_id]
        assert client.get("/api/v1/user/favorites", headers=second_auth).json()["data"] == []

        client.cookies.clear()
        logged_in = client.post("/api/v1/auth/login", json={"username": second_name, "password": second_password})
        assert logged_in.status_code == 200
        refreshed = client.post("/api/v1/auth/refresh")
        assert refreshed.status_code == 200
        logout = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"})
        assert logout.status_code == 200
        assert client.post("/api/v1/auth/refresh").status_code == 401


def test_public_registration_cannot_create_admin_account():
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/register", json={"username": "admin", "password": "a-strong-password"})
        assert response.status_code == 409
