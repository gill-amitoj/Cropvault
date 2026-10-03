import pytest

from app import db
from tests.conftest import make_user


def add_audit_rows(user_id, count):
    with db.get_connection() as conn:
        for i in range(count):
            conn.execute(
                "INSERT INTO audit_log (user_id, action, entity_type, entity_id) "
                "VALUES (%s, 'LOGIN', 'user', %s)",
                (user_id, i),
            )


@pytest.mark.parametrize("role", ["researcher", "viewer"])
def test_non_admin_cannot_view_audit_log(api, role):
    user = make_user(role)
    response = api.get("/api/audit", headers=user["headers"])
    assert response.status_code == 403


def test_audit_log_requires_login(api):
    assert api.get("/api/audit").status_code == 401


def test_admin_sees_audit_log_newest_first_with_user_email(api):
    admin = make_user("admin")
    add_audit_rows(admin["id"], 3)

    body = api.get("/api/audit", headers=admin["headers"]).json()

    assert body["total"] == 3
    assert [item["entity_id"] for item in body["items"]] == [2, 1, 0]
    assert body["items"][0]["user_email"] == "admin@example.com"


def test_audit_log_pagination(api):
    admin = make_user("admin")
    add_audit_rows(admin["id"], 30)

    first = api.get("/api/audit", headers=admin["headers"]).json()
    second = api.get("/api/audit?page=2", headers=admin["headers"]).json()

    assert (first["page_size"], len(first["items"]), first["total"]) == (24, 24, 30)
    assert len(second["items"]) == 6


@pytest.mark.parametrize("query", ["page=0", "page_size=0", "page_size=101"])
def test_audit_log_bad_pagination_is_422(api, query):
    admin = make_user("admin")
    assert api.get(f"/api/audit?{query}", headers=admin["headers"]).status_code == 422
