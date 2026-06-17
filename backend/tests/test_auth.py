def test_login_and_me(client):
    r = client.get("/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == "steve@example.com"


def test_bad_password_rejected(client):
    r = client.post(
        "/auth/login", json={"email": "steve@example.com", "password": "wrong"}
    )
    assert r.status_code == 401


def test_protected_route_requires_token(db_session):
    from fastapi.testclient import TestClient
    from app.main import app

    bare = TestClient(app)
    assert bare.get("/properties").status_code in (401, 403)


def test_create_additional_user(client):
    r = client.post(
        "/auth/users",
        json={"email": "wife@example.com", "name": "Wife", "password": "secret1"},
    )
    assert r.status_code == 201
    # duplicate rejected
    r2 = client.post(
        "/auth/users",
        json={"email": "wife@example.com", "name": "Wife", "password": "secret1"},
    )
    assert r2.status_code == 409
