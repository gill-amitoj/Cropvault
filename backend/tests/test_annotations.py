import pytest

from app import db
from tests.conftest import image_bytes, make_user, upload

BOX = {
    "label": "lesion",
    "kind": "bbox",
    "geometry": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
}
POLY = {
    "label": "leaf",
    "kind": "polygon",
    "geometry": {"points": [[0.1, 0.1], [0.9, 0.1], [0.5, 0.8]]},
}


@pytest.fixture
def owner(api):
    return make_user("researcher", email="owner@example.com")


@pytest.fixture
def image_id(api, owner):
    return upload(api, owner, image_bytes()).json()["id"]


def annotate(api, user, image_id, body=BOX):
    return api.post(f"/api/images/{image_id}/annotations", json=body, headers=user["headers"])


# --- creating and listing -----------------------------------------------------------------


def test_create_bbox_and_polygon_and_list_them(api, owner, image_id):
    box = annotate(api, owner, image_id, BOX)
    poly = annotate(api, owner, image_id, POLY)

    assert box.status_code == 201 and poly.status_code == 201
    assert box.json()["geometry"] == BOX["geometry"]
    assert poly.json()["geometry"] == {"points": [[0.1, 0.1], [0.9, 0.1], [0.5, 0.8]]}
    assert box.json()["created_by"] == owner["id"]

    listed = api.get(f"/api/images/{image_id}/annotations", headers=owner["headers"]).json()
    assert [a["kind"] for a in listed] == ["bbox", "polygon"]


def test_label_is_trimmed(api, owner, image_id):
    response = annotate(api, owner, image_id, {**BOX, "label": "  rust pustule  "})
    assert response.json()["label"] == "rust pustule"


def test_annotation_on_missing_image_is_404(api, owner):
    assert annotate(api, owner, 9999).status_code == 404
    assert api.get("/api/images/9999/annotations", headers=owner["headers"]).status_code == 404


def test_create_writes_annotate_audit_row(api, owner, image_id):
    annotation_id = annotate(api, owner, image_id).json()["id"]
    row = db.fetch_one(
        "SELECT user_id, entity_type, entity_id, details FROM audit_log WHERE action = 'ANNOTATE'"
    )
    assert row == {
        "user_id": owner["id"],
        "entity_type": "annotation",
        "entity_id": annotation_id,
        "details": {"image_id": image_id, "kind": "bbox", "label": "lesion"},
    }


# --- geometry validation (trap #9: coordinates are fractions 0-1) --------------------------


@pytest.mark.parametrize(
    "geometry",
    [
        {"x": -0.1, "y": 0.2, "width": 0.3, "height": 0.4},  # negative
        {"x": 0.1, "y": 0.2, "width": 0, "height": 0.4},  # zero width
        {"x": 0.8, "y": 0.2, "width": 0.3, "height": 0.4},  # sticks out on the right
        {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.9},  # sticks out at the bottom
        {"x": 0.1, "y": 0.2, "width": 0.3},  # missing height
        {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4, "z": 1},  # unexpected field
        {"x": 120, "y": 40, "width": 300, "height": 200},  # pixels instead of fractions
        {"points": [[0.1, 0.1], [0.2, 0.2], [0.3, 0.1]]},  # polygon shape sent as a bbox
    ],
)
def test_invalid_bbox_is_422(api, owner, image_id, geometry):
    assert annotate(api, owner, image_id, {**BOX, "geometry": geometry}).status_code == 422


@pytest.mark.parametrize(
    "geometry",
    [
        {"points": [[0.1, 0.1], [0.9, 0.1]]},  # only 2 points
        {"points": [[0.1, 0.1], [1.2, 0.1], [0.5, 0.8]]},  # x > 1
        {"points": [[0.1, 0.1], [0.9, 0.1], [0.5]]},  # broken point
        {"points": [[0.5, 0.5]] * 201},  # too many points
        {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},  # bbox shape sent as a polygon
    ],
)
def test_invalid_polygon_is_422(api, owner, image_id, geometry):
    assert annotate(api, owner, image_id, {**POLY, "geometry": geometry}).status_code == 422


def test_box_touching_the_edge_is_allowed(api, owner, image_id):
    edge = {
        "x": 0.3,
        "y": 0.0,
        "width": 0.7,
        "height": 1.0,
    }  # 0.3 + 0.7 rounds to 1.0000000000000002
    assert annotate(api, owner, image_id, {**BOX, "geometry": edge}).status_code == 201


@pytest.mark.parametrize("label", ["", "   ", "x" * 101])
def test_bad_label_is_422(api, owner, image_id, label):
    assert annotate(api, owner, image_id, {**BOX, "label": label}).status_code == 422


def test_unknown_kind_is_422(api, owner, image_id):
    assert annotate(api, owner, image_id, {**BOX, "kind": "circle"}).status_code == 422


# --- RBAC (trap #8) -----------------------------------------------------------------------


def test_viewer_can_see_but_not_create(api, owner, image_id):
    annotate(api, owner, image_id)
    viewer = make_user("viewer")
    assert (
        len(api.get(f"/api/images/{image_id}/annotations", headers=viewer["headers"]).json()) == 1
    )
    response = annotate(api, viewer, image_id)
    assert response.status_code == 403
    assert response.json() == {"detail": "Not allowed for your role"}


def test_researcher_can_annotate_someone_elses_image(api, image_id):
    other = make_user("researcher", email="other@example.com")
    assert annotate(api, other, image_id).status_code == 201


def test_annotations_require_login(api, image_id):
    assert api.get(f"/api/images/{image_id}/annotations").status_code == 401
    assert api.post(f"/api/images/{image_id}/annotations", json=BOX).status_code == 401


@pytest.mark.parametrize("role", ["viewer", "researcher"])
def test_others_cannot_edit_or_delete_your_annotation(api, owner, image_id, role):
    annotation_id = annotate(api, owner, image_id).json()["id"]
    other = make_user(role, email=f"other-{role}@example.com")

    edit = api.patch(
        f"/api/annotations/{annotation_id}", json={"label": "x"}, headers=other["headers"]
    )
    delete = api.delete(f"/api/annotations/{annotation_id}", headers=other["headers"])

    assert edit.status_code == 403 and delete.status_code == 403
    assert db.fetch_one("SELECT label FROM annotations")["label"] == "lesion"


def test_admin_can_edit_and_delete_any_annotation(api, owner, image_id):
    annotation_id = annotate(api, owner, image_id).json()["id"]
    admin = make_user("admin")
    edit = api.patch(
        f"/api/annotations/{annotation_id}", json={"label": "rust"}, headers=admin["headers"]
    )
    assert edit.status_code == 200 and edit.json()["label"] == "rust"
    assert (
        api.delete(f"/api/annotations/{annotation_id}", headers=admin["headers"]).status_code == 204
    )


# --- editing and deleting -----------------------------------------------------------------


def test_owner_edits_label_and_geometry_and_it_is_audited(api, owner, image_id):
    annotation = annotate(api, owner, image_id).json()
    new_box = {"x": 0.5, "y": 0.5, "width": 0.2, "height": 0.2}

    response = api.patch(
        f"/api/annotations/{annotation['id']}",
        json={"label": "rust", "geometry": new_box},
        headers=owner["headers"],
    )

    assert response.status_code == 200
    assert response.json()["label"] == "rust"
    assert response.json()["geometry"] == new_box
    assert response.json()["kind"] == "bbox"
    assert response.json()["updated_at"] > annotation["updated_at"]
    details = db.fetch_one("SELECT details FROM audit_log WHERE action = 'UPDATE'")["details"]
    assert details["label"] == {"from": "lesion", "to": "rust"}
    assert details["geometry"]["to"] == new_box


def test_edit_geometry_is_validated_against_the_existing_kind(api, owner, image_id):
    annotation_id = annotate(api, owner, image_id).json()["id"]  # a bbox
    response = api.patch(
        f"/api/annotations/{annotation_id}",
        json={"geometry": POLY["geometry"]},
        headers=owner["headers"],
    )
    assert response.status_code == 422


def test_edit_with_empty_body_is_422(api, owner, image_id):
    annotation_id = annotate(api, owner, image_id).json()["id"]
    assert (
        api.patch(
            f"/api/annotations/{annotation_id}", json={}, headers=owner["headers"]
        ).status_code
        == 422
    )


def test_owner_deletes_annotation_and_it_is_audited(api, owner, image_id):
    annotation_id = annotate(api, owner, image_id).json()["id"]
    assert (
        api.delete(f"/api/annotations/{annotation_id}", headers=owner["headers"]).status_code == 204
    )
    assert db.fetch_one("SELECT count(*) AS n FROM annotations")["n"] == 0
    row = db.fetch_one("SELECT entity_id, details FROM audit_log WHERE action = 'DELETE'")
    assert row["entity_id"] == annotation_id
    assert row["details"]["label"] == "lesion"


def test_missing_annotation_is_404(api, owner):
    assert (
        api.patch(
            "/api/annotations/9999", json={"label": "x"}, headers=owner["headers"]
        ).status_code
        == 404
    )
    assert api.delete("/api/annotations/9999", headers=owner["headers"]).status_code == 404


def test_deleting_the_image_deletes_its_annotations(api, owner, image_id):
    annotate(api, owner, image_id)
    annotate(api, owner, image_id, POLY)
    assert api.delete(f"/api/images/{image_id}", headers=owner["headers"]).status_code == 204
    assert db.fetch_one("SELECT count(*) AS n FROM annotations")["n"] == 0
