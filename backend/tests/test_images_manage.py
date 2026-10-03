import logging

import pytest

from app import db
from tests.conftest import image_bytes, make_experiment, make_user, upload


@pytest.fixture
def owner(api):
    return make_user("researcher", email="owner@example.com")


@pytest.fixture
def image_id(api, owner):
    return upload(api, owner, image_bytes(), filename="leaf.jpg", crop_species="wheat").json()["id"]


# --- RBAC (trap #8: every forbidden case expects 403) -----------------------------------


def test_viewer_cannot_upload(api, fake_storage):
    response = upload(api, make_user("viewer"), image_bytes())
    assert response.status_code == 403
    assert fake_storage.objects == {}


def test_upload_requires_login(api):
    response = api.post("/api/images", files={"file": ("a.jpg", image_bytes(), "image/jpeg")})
    assert response.status_code == 401


@pytest.mark.parametrize("role", ["viewer", "researcher"])
def test_others_cannot_edit_image(api, image_id, role):
    other = make_user(role, email=f"other-{role}@example.com")
    response = api.patch(
        f"/api/images/{image_id}", json={"crop_species": "barley"}, headers=other["headers"]
    )
    assert response.status_code == 403
    assert db.fetch_one("SELECT crop_species FROM images")["crop_species"] == "wheat"


@pytest.mark.parametrize("role", ["viewer", "researcher"])
def test_others_cannot_delete_image(api, image_id, role, fake_storage):
    other = make_user(role, email=f"other-{role}@example.com")
    response = api.delete(f"/api/images/{image_id}", headers=other["headers"])
    assert response.status_code == 403
    assert db.fetch_one("SELECT count(*) AS n FROM images")["n"] == 1
    assert len(fake_storage.objects) == 2


@pytest.mark.parametrize("role", ["admin", "researcher", "viewer"])
def test_every_role_can_view_image_metadata_file_and_thumbnail(api, image_id, role):
    user = make_user(role, email=f"looker-{role}@example.com")
    assert api.get(f"/api/images/{image_id}", headers=user["headers"]).status_code == 200
    assert api.get(f"/api/images/{image_id}/file", headers=user["headers"]).status_code == 200
    assert api.get(f"/api/images/{image_id}/thumbnail", headers=user["headers"]).status_code == 200


@pytest.mark.parametrize("suffix", ["", "/file", "/thumbnail"])
def test_viewing_requires_login(api, image_id, suffix):
    assert api.get(f"/api/images/{image_id}{suffix}").status_code == 401


# --- metadata edits -----------------------------------------------------------------------


def test_owner_edits_metadata_and_it_is_audited(api, owner, image_id):
    make_experiment("EXP-2026-002")
    response = api.patch(
        f"/api/images/{image_id}",
        json={
            "crop_species": "barley",
            "experiment_code": "EXP-2026-002",
            "capture_date": "2026-06-30",
            "tags": ["Rust", "rust", " leaf "],
        },
        headers=owner["headers"],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["crop_species"] == "barley"
    assert body["experiment_code"] == "EXP-2026-002"
    assert body["capture_date"] == "2026-06-30"
    assert body["tags"] == ["rust", "leaf"]
    row = db.fetch_one("SELECT details FROM audit_log WHERE action = 'UPDATE'")
    assert row["details"]["crop_species"] == {"from": "wheat", "to": "barley"}
    assert row["details"]["capture_date"] == {"from": None, "to": "2026-06-30"}


def test_null_clears_a_field_and_omitted_fields_stay(api, owner, image_id):
    api.patch(f"/api/images/{image_id}", json={"station_id": "ST09"}, headers=owner["headers"])
    response = api.patch(
        f"/api/images/{image_id}", json={"crop_species": None}, headers=owner["headers"]
    )
    assert response.json()["crop_species"] is None
    assert response.json()["station_id"] == "ST09"


def test_admin_can_edit_anyones_image(api, image_id):
    admin = make_user("admin")
    response = api.patch(
        f"/api/images/{image_id}", json={"station_id": "ST02"}, headers=admin["headers"]
    )
    assert response.status_code == 200


def test_edit_with_unknown_experiment_is_400(api, owner, image_id):
    response = api.patch(
        f"/api/images/{image_id}", json={"experiment_code": "NOPE"}, headers=owner["headers"]
    )
    assert response.status_code == 400


def test_edit_with_empty_body_is_422(api, owner, image_id):
    assert (
        api.patch(f"/api/images/{image_id}", json={}, headers=owner["headers"]).status_code == 422
    )


def test_edit_cannot_touch_the_file_or_checksum(api, owner, image_id):
    before = db.fetch_one("SELECT sha256, storage_key FROM images")
    api.patch(
        f"/api/images/{image_id}",
        json={"sha256": "0" * 64, "storage_key": "evil", "crop_species": "oat"},
        headers=owner["headers"],
    )
    assert db.fetch_one("SELECT sha256, storage_key FROM images") == before


def test_get_unknown_image_is_404(api):
    user = make_user("viewer")
    for suffix in ("", "/file", "/thumbnail"):
        assert api.get(f"/api/images/9999{suffix}", headers=user["headers"]).status_code == 404


# --- streaming ----------------------------------------------------------------------------


def test_file_streams_exact_original_bytes(api, owner):
    data = image_bytes("PNG", size=(50, 50))
    image_id = upload(api, owner, data, filename="plot 7.png").json()["id"]

    response = api.get(f"/api/images/{image_id}/file", headers=owner["headers"])

    assert response.content == data
    assert response.headers["content-type"] == "image/png"
    assert "plot%207.png" in response.headers["content-disposition"]


def test_thumbnail_streams_jpeg(api, owner, image_id):
    response = api.get(f"/api/images/{image_id}/thumbnail", headers=owner["headers"])
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content[:2] == b"\xff\xd8"  # JPEG magic bytes


def test_missing_object_in_storage_is_404(api, owner, image_id, fake_storage):
    fake_storage.objects.clear()
    response = api.get(f"/api/images/{image_id}/file", headers=owner["headers"])
    assert response.status_code == 404


# --- delete -------------------------------------------------------------------------------


def test_owner_deletes_image_row_objects_and_audits(api, owner, image_id, fake_storage):
    response = api.delete(f"/api/images/{image_id}", headers=owner["headers"])

    assert response.status_code == 204
    assert db.fetch_one("SELECT count(*) AS n FROM images")["n"] == 0
    assert fake_storage.objects == {}
    row = db.fetch_one("SELECT action, entity_id, details FROM audit_log WHERE action = 'DELETE'")
    assert row["entity_id"] == image_id
    assert row["details"]["original_filename"] == "leaf.jpg"


def test_admin_can_delete_anyones_image(api, image_id):
    admin = make_user("admin")
    assert api.delete(f"/api/images/{image_id}", headers=admin["headers"]).status_code == 204


def test_delete_unknown_image_is_404(api):
    admin = make_user("admin")
    assert api.delete("/api/images/9999", headers=admin["headers"]).status_code == 404


def test_object_delete_failure_still_deletes_row_and_logs_orphan(
    api, owner, image_id, fake_storage, caplog
):
    fake_storage.fail_delete = True
    with caplog.at_level(logging.ERROR):
        response = api.delete(f"/api/images/{image_id}", headers=owner["headers"])

    assert response.status_code == 204
    assert db.fetch_one("SELECT count(*) AS n FROM images")["n"] == 0
    assert caplog.text.count("ORPHAN") == 2  # original + thumbnail


def test_original_with_crops_cannot_be_deleted(api, owner, image_id, fake_storage):
    with db.get_connection() as conn:
        conn.execute(
            """INSERT INTO images (original_filename, storage_key, content_type, size_bytes,
                   width, height, sha256, uploaded_by, parent_image_id, derivation)
               VALUES ('crop.jpg', 'originals/crop.jpg', 'image/jpeg', 10, 5, 5, %s, %s, %s,
                       'crop')""",
            ("f" * 64, owner["id"], image_id),
        )

    response = api.delete(f"/api/images/{image_id}", headers=owner["headers"])

    assert response.status_code == 409
    assert "Delete those first" in response.json()["detail"]
    assert len(fake_storage.objects) == 2  # nothing removed from storage
