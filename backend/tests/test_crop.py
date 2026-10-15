import io
import logging

import pytest
from PIL import ExifTags, Image, ImageOps

from app import audit, db, images
from tests.conftest import make_experiment, make_user, upload


def two_colour_png(size=(200, 100)) -> bytes:
    """Left half red, right half blue: lets tests check WHICH pixels ended up in a crop."""
    img = Image.new("RGB", size, (255, 0, 0))
    img.paste((0, 0, 255), (size[0] // 2, 0, size[0], size[1]))
    buffer = io.BytesIO()
    img.save(buffer, "PNG")
    return buffer.getvalue()


def stored_bytes(fake_storage, image_id):
    key = db.fetch_one("SELECT storage_key FROM images WHERE id = %s", (image_id,))["storage_key"]
    return fake_storage.objects[key][0]


@pytest.fixture
def owner(api):
    return make_user("researcher", email="owner@example.com")


@pytest.fixture
def parent(api, owner):
    make_experiment("EXP-2026-001")
    return upload(
        api, owner, two_colour_png(), filename="leaf.png", content_type="image/png",
        experiment_code="EXP-2026-001", crop_species="Wheat", station_id="ST01",
        capture_date="2026-05-01", tags="rust,leaf",
    ).json()  # fmt: skip


def crop(api, user, image_id, x=100, y=0, width=100, height=100):
    return api.post(
        f"/api/images/{image_id}/crop",
        json={"x": x, "y": y, "width": width, "height": height},
        headers=user["headers"],
    )


# --- the crop itself (trap #6: a NEW image linked to its parent) ---------------------------


def test_crop_creates_linked_derived_image_with_parent_metadata(api, owner, parent):
    response = crop(api, owner, parent["id"])

    assert response.status_code == 201, response.text
    child = response.json()
    assert child["id"] != parent["id"]
    assert child["parent_image_id"] == parent["id"]
    assert child["derivation"] == "crop"
    assert (child["width"], child["height"]) == (100, 100)
    assert child["content_type"] == "image/png"  # same format as the parent
    assert child["original_filename"] == "leaf_crop_100_0_100x100.png"
    for field in ("experiment_code", "crop_species", "station_id", "capture_date", "tags"):
        assert child[field] == parent[field]
    assert child["uploaded_by"] == owner["id"]


def test_crop_contains_exactly_the_requested_pixels(api, owner, parent, fake_storage):
    right_half = crop(api, owner, parent["id"], x=100, width=100).json()
    left_half = crop(api, owner, parent["id"], x=0, width=100).json()

    right = Image.open(io.BytesIO(stored_bytes(fake_storage, right_half["id"]))).convert("RGB")
    left = Image.open(io.BytesIO(stored_bytes(fake_storage, left_half["id"]))).convert("RGB")
    assert right.getcolors() == [(100 * 100, (0, 0, 255))]  # all blue
    assert left.getcolors() == [(100 * 100, (255, 0, 0))]  # all red


def test_parent_bytes_are_unchanged(api, owner, parent, fake_storage):
    before = stored_bytes(fake_storage, parent["id"])
    crop(api, owner, parent["id"])
    assert stored_bytes(fake_storage, parent["id"]) == before
    assert (
        db.fetch_one("SELECT sha256 FROM images WHERE id = %s", (parent["id"],))["sha256"]
        == parent["sha256"]
    )


def test_crop_of_rotated_photo_uses_display_orientation(api, owner, fake_storage):
    # Stored 300x150 but EXIF says rotate 90 deg, so it DISPLAYS as 150x300.
    stored = Image.new("RGB", (300, 150), (255, 0, 0))
    stored.paste((0, 0, 255), (0, 0, 150, 150))  # left half of the STORED image is blue
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = 6
    buffer = io.BytesIO()
    stored.save(buffer, "PNG", exif=exif)
    data = buffer.getvalue()
    photo = upload(api, owner, data, filename="phone.png", content_type="image/png").json()
    assert (photo["width"], photo["height"]) == (150, 300)

    response = crop(api, owner, photo["id"], x=0, y=0, width=150, height=150)  # top of the display

    assert response.status_code == 201
    expected = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).crop((0, 0, 150, 150))
    got = Image.open(io.BytesIO(stored_bytes(fake_storage, response.json()["id"])))
    assert got.convert("RGB").tobytes() == expected.convert("RGB").tobytes()
    assert ImageOps.exif_transpose(got).size == (150, 150)  # stored upright, no rotation needed


def test_jpeg_parent_gives_jpeg_crop(api, owner, fake_storage):
    buffer = io.BytesIO()
    Image.new("RGB", (200, 200), (30, 120, 40)).save(buffer, "JPEG")
    photo = upload(api, owner, buffer.getvalue()).json()
    child = crop(api, owner, photo["id"], x=10, y=10, width=50, height=50).json()
    assert child["content_type"] == "image/jpeg"
    assert stored_bytes(fake_storage, child["id"])[:3] == b"\xff\xd8\xff"


def test_crop_gets_a_thumbnail(api, owner, parent, fake_storage):
    child = crop(api, owner, parent["id"]).json()
    response = api.get(f"/api/images/{child['id']}/thumbnail", headers=owner["headers"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"


def test_crop_is_audited(api, owner, parent):
    child = crop(api, owner, parent["id"]).json()
    row = db.fetch_one("SELECT user_id, entity_id, details FROM audit_log WHERE action = 'CROP'")
    assert row == {
        "user_id": owner["id"],
        "entity_id": child["id"],
        "details": {
            "parent_image_id": parent["id"],
            "region": {"x": 100, "y": 0, "width": 100, "height": 100},
        },
    }


# --- duplicates and validation ------------------------------------------------------------


def test_same_crop_twice_is_409_with_existing_id(api, owner, parent, fake_storage):
    first = crop(api, owner, parent["id"]).json()
    objects_before = len(fake_storage.objects)

    second = crop(api, make_user("admin"), parent["id"])

    assert second.status_code == 409
    assert second.json()["detail"]["image_id"] == first["id"]
    assert len(fake_storage.objects) == objects_before


@pytest.mark.parametrize(
    ("region", "status"),
    [
        ({"x": 150, "width": 100}, 400),  # runs off the right edge (image is 200 wide)
        ({"y": 50, "height": 100}, 400),  # runs off the bottom (image is 100 tall)
        ({"width": 10}, 422),  # smaller than the 16 px minimum
        ({"x": -1}, 422),  # negative
        ({"x": 1.5}, 422),  # not a whole pixel
    ],
)
def test_bad_crop_region(api, owner, parent, region, status):
    body = {"x": 0, "y": 0, "width": 50, "height": 50, **region}
    response = api.post(f"/api/images/{parent['id']}/crop", json=body, headers=owner["headers"])
    assert response.status_code == status


def test_crop_of_missing_image_is_404(api, owner):
    assert crop(api, owner, 9999).status_code == 404


def test_crop_must_use_display_size_not_stored_size(api, owner):
    stored = Image.new("RGB", (300, 150), (255, 0, 0))
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = 6
    buffer = io.BytesIO()
    stored.save(buffer, "PNG", exif=exif)
    photo = upload(api, owner, buffer.getvalue(), filename="p.png", content_type="image/png").json()
    # 200 wide fits the STORED width (300) but not the DISPLAYED width (150).
    assert crop(api, owner, photo["id"], x=0, y=0, width=200, height=100).status_code == 400


# --- RBAC (trap #8) -----------------------------------------------------------------------


def test_viewer_cannot_crop(api, parent):
    response = crop(api, make_user("viewer"), parent["id"])
    assert response.status_code == 403
    assert db.fetch_one("SELECT count(*) AS n FROM images")["n"] == 1


def test_researcher_can_crop_someone_elses_image_and_owns_the_crop(api, parent):
    other = make_user("researcher", email="other@example.com")
    child = crop(api, other, parent["id"]).json()
    assert child["uploaded_by"] == other["id"]


def test_crop_requires_login(api, parent):
    response = api.post(
        f"/api/images/{parent['id']}/crop", json={"x": 0, "y": 0, "width": 50, "height": 50}
    )
    assert response.status_code == 401


# --- consistency (trap #7) ----------------------------------------------------------------


def test_parent_cannot_be_deleted_while_crop_exists(api, owner, parent):
    child = crop(api, owner, parent["id"]).json()
    assert api.delete(f"/api/images/{parent['id']}", headers=owner["headers"]).status_code == 409
    assert api.delete(f"/api/images/{child['id']}", headers=owner["headers"]).status_code == 204
    assert api.delete(f"/api/images/{parent['id']}", headers=owner["headers"]).status_code == 204


def test_db_failure_during_crop_removes_stored_objects(
    api, owner, parent, fake_storage, monkeypatch
):
    objects_before = dict(fake_storage.objects)

    def broken_audit(*args, **kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(audit, "write_audit", broken_audit)
    with pytest.raises(RuntimeError):
        crop(api, owner, parent["id"])

    assert fake_storage.objects == objects_before
    assert db.fetch_one("SELECT count(*) AS n FROM images")["n"] == 1


def test_missing_parent_file_is_404(api, owner, parent, fake_storage, caplog):
    key = db.fetch_one("SELECT storage_key FROM images")["storage_key"]
    del fake_storage.objects[key]
    with caplog.at_level(logging.ERROR):
        assert crop(api, owner, parent["id"]).status_code == 404
    assert "Object missing" in caplog.text


def test_crop_helper_keeps_png_lossless():
    data = two_colour_png()
    out = images.crop_image(images.open_image(data), 100, 0, 100, 100)
    assert Image.open(io.BytesIO(out)).format == "PNG"
