"""Mini test suite for user auth: register, login and token verification against a real (if
in-memory) database — not mocked, since CRUD correctness is exactly what's being tested here.
See conftest.py's db_session fixture.
"""

from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


def test_register_then_login_then_me(db_session: object) -> None:
    r = client.post("/api/auth/register", json={"email": "demo@example.com", "password": "hunter2hunter2"})
    assert r.status_code == 200
    token = r.json()["access_token"]

    r = client.post("/api/auth/login", json={"email": "demo@example.com", "password": "hunter2hunter2"})
    assert r.status_code == 200

    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json() == {"id": 1, "email": "demo@example.com"}


def test_register_rejects_a_duplicate_email(db_session: object) -> None:
    body = {"email": "dup@example.com", "password": "hunter2hunter2"}
    assert client.post("/api/auth/register", json=body).status_code == 200
    assert client.post("/api/auth/register", json=body).status_code == 409


def test_login_rejects_a_wrong_password(db_session: object) -> None:
    client.post("/api/auth/register", json={"email": "pw@example.com", "password": "hunter2hunter2"})
    r = client.post("/api/auth/login", json={"email": "pw@example.com", "password": "wrong-password"})
    assert r.status_code == 401


def test_me_requires_a_bearer_token(db_session: object) -> None:
    assert client.get("/api/auth/me").status_code == 401


def test_me_rejects_a_malformed_token(db_session: object) -> None:
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401
