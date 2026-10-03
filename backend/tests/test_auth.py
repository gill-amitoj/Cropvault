import datetime as dt

import jwt

from app import config, db
from tests.conftest import TEST_PASSWORD, make_user


def login(api, email, password=TEST_PASSWORD):
    return api.post("/api/auth/login", json={"email": email, "password": password})


def test_login_returns_token_and_writes_audit(api):
    user = make_user("researcher")

    response = login(api, "Researcher@Example.com")  # email is case-insensitive

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    me = api.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"}
    )
    assert me.json()["id"] == user["id"]
    row = db.fetch_one("SELECT user_id, action, entity_type FROM audit_log")
    assert row == {"user_id": user["id"], "action": "LOGIN", "entity_type": "user"}


def test_login_wrong_password_is_401(api):
    make_user("researcher")
    response = login(api, "researcher@example.com", "wrong-password")
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}


def test_login_unknown_email_is_401_with_same_message(api):
    response = login(api, "nobody@example.com")
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}


def test_login_deactivated_user_is_401_with_same_message(api):
    make_user("researcher", is_active=False)
    response = login(api, "researcher@example.com")
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}


def test_failed_login_writes_no_audit_row(api):
    login(api, "nobody@example.com")
    assert db.fetch_all("SELECT id FROM audit_log") == []


def test_me_returns_current_user_without_password_hash(api):
    user = make_user("viewer")
    response = api.get("/api/auth/me", headers=user["headers"])
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "viewer@example.com"
    assert body["role"] == "viewer"
    assert "password_hash" not in body


def test_me_without_token_is_401(api):
    assert api.get("/api/auth/me").status_code == 401


def test_me_with_token_signed_by_another_secret_is_401(api):
    user = make_user("admin")
    forged = jwt.encode({"sub": str(user["id"])}, "some-other-secret-value-xxxxxxxxxx", "HS256")
    response = api.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


def test_me_with_expired_token_is_401(api):
    user = make_user("admin")
    past = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
    expired = jwt.encode({"sub": str(user["id"]), "exp": past}, config.JWT_SECRET, "HS256")
    response = api.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


def test_me_with_garbage_token_is_401(api):
    response = api.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


def test_user_deactivated_after_login_is_locked_out_immediately(api):
    user = make_user("researcher")
    assert api.get("/api/auth/me", headers=user["headers"]).status_code == 200

    with db.get_connection() as conn:
        conn.execute("UPDATE users SET is_active = FALSE WHERE id = %s", (user["id"],))

    assert api.get("/api/auth/me", headers=user["headers"]).status_code == 401
