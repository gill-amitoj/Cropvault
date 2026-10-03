import pytest

from app import db
from tests.conftest import make_user

NEW_USER = {"email": "new@example.com", "password": "password123", "role": "viewer"}


# --- RBAC: only admins can manage users -------------------------------------------------


@pytest.mark.parametrize("role", ["researcher", "viewer"])
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/users", None),
        ("post", "/api/users", NEW_USER),
        ("patch", "/api/users/1", {"role": "admin"}),
    ],
)
def test_non_admin_cannot_manage_users(api, role, method, path, body):
    user = make_user(role)
    response = api.request(method, path, json=body, headers=user["headers"])
    assert response.status_code == 403
    assert response.json() == {"detail": "Not allowed for your role"}


@pytest.mark.parametrize(
    ("method", "path"), [("get", "/api/users"), ("post", "/api/users"), ("patch", "/api/users/1")]
)
def test_user_endpoints_require_login(api, method, path):
    assert api.request(method, path, json=NEW_USER).status_code == 401


def test_researcher_cannot_promote_themselves(api):
    user = make_user("researcher")
    response = api.patch(
        f"/api/users/{user['id']}", json={"role": "admin"}, headers=user["headers"]
    )
    assert response.status_code == 403
    assert (
        db.fetch_one("SELECT role FROM users WHERE id = %s", (user["id"],))["role"] == "researcher"
    )


# --- Admin happy paths ------------------------------------------------------------------


def test_admin_lists_users_without_password_hashes(api):
    admin = make_user("admin")
    make_user("viewer")

    response = api.get("/api/users", headers=admin["headers"])

    assert response.status_code == 200
    assert [u["email"] for u in response.json()] == ["admin@example.com", "viewer@example.com"]
    assert all("password_hash" not in u for u in response.json())


def test_admin_creates_user_who_can_then_log_in(api):
    admin = make_user("admin")

    response = api.post(
        "/api/users", json={**NEW_USER, "email": " New@Example.com "}, headers=admin["headers"]
    )

    assert response.status_code == 201
    assert response.json()["email"] == "new@example.com"
    assert response.json()["role"] == "viewer"
    login = api.post(
        "/api/auth/login", json={"email": "new@example.com", "password": "password123"}
    )
    assert login.status_code == 200
    audit = db.fetch_one("SELECT user_id, action, entity_id, details FROM audit_log")
    assert audit == {
        "user_id": admin["id"],
        "action": "USER_CREATE",
        "entity_id": response.json()["id"],
        "details": {"email": "new@example.com", "role": "viewer"},
    }


def test_create_user_duplicate_email_is_409(api):
    admin = make_user("admin")
    api.post("/api/users", json=NEW_USER, headers=admin["headers"])
    response = api.post("/api/users", json=NEW_USER, headers=admin["headers"])
    assert response.status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {**NEW_USER, "role": "superuser"},
        {**NEW_USER, "password": "short"},
        {**NEW_USER, "email": "not-an-email"},
        {"email": "x@example.com"},
    ],
)
def test_create_user_invalid_body_is_422(api, body):
    admin = make_user("admin")
    assert api.post("/api/users", json=body, headers=admin["headers"]).status_code == 422


def test_admin_changes_role_and_it_is_audited(api):
    admin = make_user("admin")
    target = make_user("viewer")

    response = api.patch(
        f"/api/users/{target['id']}", json={"role": "researcher"}, headers=admin["headers"]
    )

    assert response.status_code == 200
    assert response.json()["role"] == "researcher"
    audit = db.fetch_one("SELECT action, entity_id, details FROM audit_log")
    assert audit == {
        "action": "ROLE_CHANGE",
        "entity_id": target["id"],
        "details": {"from": "viewer", "to": "researcher"},
    }


def test_admin_deactivates_user_who_is_then_locked_out(api):
    admin = make_user("admin")
    target = make_user("researcher")

    response = api.patch(
        f"/api/users/{target['id']}", json={"is_active": False}, headers=admin["headers"]
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert api.get("/api/auth/me", headers=target["headers"]).status_code == 401
    audit = db.fetch_one("SELECT action, details FROM audit_log")
    assert audit == {"action": "UPDATE", "details": {"is_active": {"from": True, "to": False}}}


def test_admin_cannot_change_their_own_role_or_status(api):
    admin = make_user("admin")
    for body in ({"role": "viewer"}, {"is_active": False}):
        response = api.patch(f"/api/users/{admin['id']}", json=body, headers=admin["headers"])
        assert response.status_code == 400


def test_patch_unknown_user_is_404(api):
    admin = make_user("admin")
    response = api.patch("/api/users/9999", json={"role": "viewer"}, headers=admin["headers"])
    assert response.status_code == 404


def test_patch_with_empty_body_is_422(api):
    admin = make_user("admin")
    target = make_user("viewer")
    response = api.patch(f"/api/users/{target['id']}", json={}, headers=admin["headers"])
    assert response.status_code == 422
