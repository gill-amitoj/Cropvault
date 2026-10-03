import io
import logging

from PIL import ExifTags, Image

from app import audit, db, images
from tests.conftest import image_bytes, make_experiment, make_user, upload


def test_upload_jpeg_stores_original_thumbnail_and_row(api, fake_storage):
    user = make_user("researcher")
    make_experiment("EXP-2026-001")
    data = image_bytes("JPEG", size=(1280, 960))

    response = upload(
        api,
        user,
        data,
        filename="wheat_01.jpg",
        experiment_code="EXP-2026-001",
        crop_species="wheat",
        station_id="ST01",
        capture_date="2026-05-01",
        tags="Drought, leaf ,drought,",
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["original_filename"] == "wheat_01.jpg"
    assert body["content_type"] == "image/jpeg"
    assert (body["width"], body["height"]) == (1280, 960)
    assert body["size_bytes"] == len(data)
    assert body["sha256"] == images.sha256_hex(data)
    assert body["experiment_code"] == "EXP-2026-001"
    assert body["capture_date"] == "2026-05-01"
    assert body["tags"] == ["drought", "leaf"]
    assert body["uploaded_by"] == user["id"]
    assert body["parent_image_id"] is None and body["derivation"] is None
    assert "storage_key" not in body

    row = db.fetch_one("SELECT storage_key, thumbnail_key FROM images")
    assert row["storage_key"].startswith("originals/") and row["storage_key"].endswith(".jpg")
    assert fake_storage.objects[row["storage_key"]] == (data, "image/jpeg")  # untouched
    thumb_bytes, thumb_type = fake_storage.objects[row["thumbnail_key"]]
    assert thumb_type == "image/jpeg"
    assert Image.open(io.BytesIO(thumb_bytes)).size == (320, 240)


def test_upload_png_and_tiff_get_content_type_from_bytes_not_client(api):
    user = make_user("researcher")
    png = upload(api, user, image_bytes("PNG"), filename="a.jpg", content_type="image/jpeg")
    tiff = upload(
        api, user, image_bytes("TIFF", color=(1, 2, 3)), filename="b.png", content_type="image/png"
    )
    assert png.json()["content_type"] == "image/png"
    assert tiff.json()["content_type"] == "image/tiff"


def test_upload_with_only_a_file_works(api):
    response = upload(api, make_user("admin"), image_bytes())
    assert response.status_code == 201
    assert response.json()["experiment_id"] is None
    assert response.json()["tags"] == []


def test_upload_uses_exif_date_unless_form_date_given(api):
    user = make_user("researcher")
    exif = Image.Exif()
    exif.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.DateTimeOriginal] = "2026:04:20 08:00:00"

    from_exif = upload(api, user, image_bytes(exif=exif))
    from_form = upload(
        api, user, image_bytes(color=(9, 9, 9), exif=exif), capture_date="2026-01-02"
    )

    assert from_exif.json()["capture_date"] == "2026-04-20"
    assert from_exif.json()["exif"]["DateTimeOriginal"] == "2026:04:20 08:00:00"
    assert from_form.json()["capture_date"] == "2026-01-02"


def test_upload_rotated_image_stores_display_dimensions_and_original_bytes(api, fake_storage):
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = 6
    data = image_bytes(size=(400, 200), exif=exif)

    body = upload(api, make_user("researcher"), data).json()

    assert (body["width"], body["height"]) == (200, 400)
    row = db.fetch_one("SELECT storage_key, thumbnail_key FROM images")
    assert fake_storage.objects[row["storage_key"]][0] == data
    thumb = Image.open(io.BytesIO(fake_storage.objects[row["thumbnail_key"]][0]))
    assert thumb.size == (200, 400)


# --- rejected uploads ---------------------------------------------------------------------


def test_text_file_named_jpg_is_400(api, fake_storage):
    response = upload(api, make_user("researcher"), b"not really an image")
    assert response.status_code == 400
    assert response.json() == {"detail": "File is not a valid JPEG, PNG or TIFF image"}
    assert fake_storage.objects == {}


def test_gif_is_400(api):
    gif = image_bytes("GIF", mode="P", color=1)
    response = upload(api, make_user("researcher"), gif, filename="x.gif", content_type="image/gif")
    assert response.status_code == 400
    assert response.json() == {"detail": "Unsupported image format: GIF"}


def test_empty_file_is_400(api):
    response = upload(api, make_user("researcher"), b"")
    assert response.status_code == 400
    assert response.json() == {"detail": "File is empty"}


def test_unknown_experiment_code_is_400_and_nothing_stored(api, fake_storage):
    response = upload(api, make_user("researcher"), image_bytes(), experiment_code="NOPE")
    assert response.status_code == 400
    assert fake_storage.objects == {}


def test_file_over_20_mb_is_rejected_from_content_length(api, fake_storage):
    data = b"\0" * (images.MAX_UPLOAD_BYTES + 1024 * 1024 + 1)
    response = upload(api, make_user("researcher"), data)
    assert response.status_code == 413
    assert fake_storage.objects == {}


def test_file_over_limit_is_rejected_by_route_size_check(api, monkeypatch, fake_storage):
    # Shrink the limit so the body passes the Content-Length middleware but not the route check.
    monkeypatch.setattr(images, "MAX_UPLOAD_BYTES", 1000)
    response = upload(api, make_user("researcher"), image_bytes(size=(300, 300)))
    assert response.status_code == 413
    assert fake_storage.objects == {}


def test_decompression_bomb_is_413(api, monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
    response = upload(api, make_user("researcher"), image_bytes("PNG", size=(100, 100)))
    assert response.status_code == 413
    assert response.json() == {"detail": "Image dimensions are too large"}


# --- duplicates ---------------------------------------------------------------------------


def test_duplicate_upload_is_409_with_existing_id(api, fake_storage):
    user = make_user("researcher")
    data = image_bytes()
    first = upload(api, user, data, filename="one.jpg")

    second = upload(api, make_user("admin"), data, filename="renamed.jpg")

    assert second.status_code == 409
    assert second.json() == {
        "detail": {"message": "Duplicate image", "image_id": first.json()["id"]}
    }
    assert len(fake_storage.objects) == 2  # one original + one thumbnail, not four
    assert db.fetch_one("SELECT count(*) AS n FROM images")["n"] == 1


def test_duplicate_that_slips_past_the_check_still_gives_409(api, fake_storage, monkeypatch):
    """Simulate the race: our pre-check sees nothing, then the UNIQUE constraint fires."""
    user = make_user("researcher")
    data = image_bytes()
    first_id = upload(api, user, data).json()["id"]

    real_fetch_one = db.fetch_one
    calls = {"n": 0}

    def fetch_one_missing_first_check(query, params=()):
        if "WHERE sha256" in query and calls["n"] == 0:
            calls["n"] += 1
            return None
        return real_fetch_one(query, params)

    monkeypatch.setattr(db, "fetch_one", fetch_one_missing_first_check)
    response = upload(api, user, data)

    assert response.status_code == 409
    assert response.json()["detail"]["image_id"] == first_id
    assert len(fake_storage.objects) == 2  # the loser's objects were cleaned up


# --- storage / DB consistency ---------------------------------------------------------


def test_db_failure_after_storage_put_removes_the_objects(api, fake_storage, monkeypatch):
    def broken_audit(*args, **kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(audit, "write_audit", broken_audit)
    try:
        upload(api, make_user("researcher"), image_bytes())
    except RuntimeError:
        pass  # TestClient re-raises server errors; a real client would get 500

    assert fake_storage.objects == {}
    assert db.fetch_one("SELECT count(*) AS n FROM images")["n"] == 0


def test_thumbnail_put_failure_removes_the_original(api, fake_storage):
    fake_storage.fail_put_on = "thumbnails/"
    try:
        upload(api, make_user("researcher"), image_bytes())
    except ConnectionError:
        pass

    assert fake_storage.objects == {}
    assert db.fetch_one("SELECT count(*) AS n FROM images")["n"] == 0


def test_upload_writes_audit_row(api):
    user = make_user("researcher")
    image_id = upload(api, user, image_bytes(), filename="leaf.jpg").json()["id"]
    row = db.fetch_one("SELECT user_id, action, entity_type, entity_id, details FROM audit_log")
    assert row["user_id"] == user["id"]
    assert (row["action"], row["entity_type"], row["entity_id"]) == ("UPLOAD", "image", image_id)
    assert row["details"]["original_filename"] == "leaf.jpg"


def test_cleanup_failure_is_logged_as_orphan(api, fake_storage, monkeypatch, caplog):
    def broken_audit(*args, **kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(audit, "write_audit", broken_audit)
    fake_storage.fail_delete = True
    with caplog.at_level(logging.ERROR):
        try:
            upload(api, make_user("researcher"), image_bytes())
        except RuntimeError:
            pass
    assert caplog.text.count("ORPHAN") == 2
