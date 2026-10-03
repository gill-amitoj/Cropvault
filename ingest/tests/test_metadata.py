import json

import pytest

import watcher


def test_sidecar_name_swaps_the_extension(tmp_path):
    assert watcher.sidecar_path(tmp_path / "leaf01.jpg") == tmp_path / "leaf01.json"


def test_read_sidecar_keeps_known_fields_and_joins_tags(tmp_path):
    sidecar = tmp_path / "leaf01.json"
    sidecar.write_text(
        json.dumps(
            {
                "experiment_code": "EXP-2026-001",
                "crop_species": "Wheat",
                "station_id": "ST01",
                "capture_date": "2026-05-01",
                "tags": ["drought", "leaf"],
                "operator": "ignored",
            }
        )
    )
    assert watcher.read_sidecar(sidecar) == {
        "experiment_code": "EXP-2026-001",
        "crop_species": "Wheat",
        "station_id": "ST01",
        "capture_date": "2026-05-01",
        "tags": "drought,leaf",
    }


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", ""])
def test_bad_sidecar_raises_metadata_error(tmp_path, content):
    sidecar = tmp_path / "leaf01.json"
    sidecar.write_text(content)
    with pytest.raises(watcher.MetadataError):
        watcher.read_sidecar(sidecar)


def test_parse_filename_pattern():
    assert watcher.parse_filename("ST02_Wheat_20260512_001.jpg") == {
        "station_id": "ST02",
        "crop_species": "Wheat",
        "capture_date": "2026-05-12",
    }


@pytest.mark.parametrize(
    "name", ["random_photo.jpg", "ST02_Wheat_2026-05-12_001.jpg", "ST02_Wheat_20260512.jpg"]
)
def test_filename_not_matching_pattern_raises(name):
    with pytest.raises(watcher.MetadataError, match="doesn't match"):
        watcher.parse_filename(name)


def test_filename_with_impossible_date_raises():
    with pytest.raises(watcher.MetadataError, match="invalid"):
        watcher.parse_filename("ST04_Oat_20261399_001.jpg")


def test_sidecar_wins_over_filename(tmp_path):
    image = tmp_path / "ST02_Wheat_20260512_001.jpg"
    sidecar = tmp_path / "ST02_Wheat_20260512_001.json"
    sidecar.write_text(json.dumps({"crop_species": "Canola"}))
    assert watcher.find_metadata(image, sidecar) == {"crop_species": "Canola"}


def test_filename_used_when_no_sidecar(tmp_path):
    image = tmp_path / "ST02_Wheat_20260512_001.jpg"
    assert watcher.find_metadata(image, None)["station_id"] == "ST02"


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("a.jpg", "image"),
        ("a.JPEG", "image"),
        ("a.png", "image"),
        ("a.tif", "image"),
        ("a.tiff", "image"),
        ("a.json", "sidecar"),
        (".DS_Store", "ignore"),
        ("a.jpg.part", "ignore"),
        ("notes.txt", "other"),
        ("README", "other"),
    ],
)
def test_classify(tmp_path, name, kind):
    assert watcher.classify(tmp_path / name) == kind
