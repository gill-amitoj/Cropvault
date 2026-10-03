import pytest

from tests.conftest import make_user

EXPERIMENT = {"code": "EXP-TEST-1", "title": "Barley root imaging"}


@pytest.mark.parametrize("role", ["admin", "researcher", "viewer"])
def test_every_role_can_list_experiments(api, role):
    user = make_user(role)
    response = api.get("/api/experiments", headers=user["headers"])
    assert response.status_code == 200


def test_list_experiments_requires_login(api):
    assert api.get("/api/experiments").status_code == 401


@pytest.mark.parametrize("role", ["admin", "researcher"])
def test_admin_and_researcher_can_create_experiment(api, role):
    user = make_user(role)

    response = api.post("/api/experiments", json=EXPERIMENT, headers=user["headers"])

    assert response.status_code == 201
    assert response.json()["code"] == "EXP-TEST-1"
    assert response.json()["created_by"] == user["id"]
    listed = api.get("/api/experiments", headers=user["headers"]).json()
    assert [e["code"] for e in listed] == ["EXP-TEST-1"]


def test_viewer_cannot_create_experiment(api):
    viewer = make_user("viewer")
    response = api.post("/api/experiments", json=EXPERIMENT, headers=viewer["headers"])
    assert response.status_code == 403


def test_duplicate_experiment_code_is_409(api):
    user = make_user("researcher")
    api.post("/api/experiments", json=EXPERIMENT, headers=user["headers"])
    response = api.post("/api/experiments", json=EXPERIMENT, headers=user["headers"])
    assert response.status_code == 409


def test_experiment_with_empty_title_is_422(api):
    user = make_user("researcher")
    response = api.post(
        "/api/experiments", json={"code": "EXP-X", "title": ""}, headers=user["headers"]
    )
    assert response.status_code == 422
