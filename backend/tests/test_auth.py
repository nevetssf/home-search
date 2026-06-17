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


def test_change_password(client):
    # wrong current password is rejected
    bad = client.patch(
        "/auth/me/password",
        json={"current_password": "nope", "new_password": "brandnew1"},
    )
    assert bad.status_code == 400

    ok = client.patch(
        "/auth/me/password",
        json={"current_password": "password123", "new_password": "brandnew1"},
    )
    assert ok.status_code == 204

    # old password no longer works; new one does
    assert client.post(
        "/auth/login",
        json={"email": "steve@example.com", "password": "password123"},
    ).status_code == 401
    assert client.post(
        "/auth/login",
        json={"email": "steve@example.com", "password": "brandnew1"},
    ).status_code == 200


def test_delete_user_and_self_guard(client):
    me = client.get("/auth/me").json()
    # cannot delete self
    assert client.delete(f"/auth/users/{me['id']}").status_code == 400
    # can delete another user
    other = client.post(
        "/auth/users",
        json={"email": "guest@example.com", "name": "Guest", "password": "secret1"},
    ).json()
    assert client.delete(f"/auth/users/{other['id']}").status_code == 204
    assert len(client.get("/auth/users").json()) == 1
