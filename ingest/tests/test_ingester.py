import json

import pytest

import watcher
from tests.test_files import FakeClock


class FakeApi:
    """Records uploads and answers with a fixed result per filename."""

    def __init__(self, results=None):
        self.results = results or {}
        self.uploads = []

    def upload(self, path, fields):
        self.uploads.append((path.name, fields))
        return self.results.get(path.name, watcher.UploadResult("created", image_id=1))


@pytest.fixture
def setup(tmp_path):
    clock = FakeClock()
    api = FakeApi()
    ingester = watcher.Ingester(tmp_path, api, clock)
    return tmp_path, clock, api, ingester


def drop(folder, name, data=b"image bytes", sidecar=None):
    (folder / name).write_bytes(data)
    if sidecar is not None:
        (folder / name).with_suffix(".json").write_text(json.dumps(sidecar))


def run(ingester, clock, seconds, step=1.0):
    """Poll like the main loop does, advancing the fake clock."""
    elapsed = 0.0
    while elapsed <= seconds:
        ingester.process_pending()
        clock.advance(step)
        elapsed += step


def test_image_with_sidecar_is_uploaded_and_moved_to_processed(setup):
    folder, clock, api, ingester = setup
    drop(folder, "leaf.jpg", sidecar={"crop_species": "Wheat"})
    ingester.add_existing()

    run(ingester, clock, 3)

    assert api.uploads == [("leaf.jpg", {"crop_species": "Wheat"})]
    assert (folder / "processed" / "leaf.jpg").exists()
    assert (folder / "processed" / "leaf.json").exists()
    assert not (folder / "leaf.jpg").exists()


def test_nothing_happens_before_the_file_is_stable(setup):
    folder, clock, api, ingester = setup
    drop(folder, "leaf.jpg", sidecar={})
    ingester.add_existing()

    run(ingester, clock, 1)

    assert api.uploads == []
    assert (folder / "leaf.jpg").exists()


def test_file_still_being_written_is_not_uploaded_until_it_stops_growing(setup):
    folder, clock, api, ingester = setup
    drop(folder, "leaf.jpg", b"part", sidecar={})
    ingester.add_existing()
    for size in range(1, 5):  # keeps growing every second
        ingester.process_pending()
        (folder / "leaf.jpg").write_bytes(b"part" * (size + 1))
        clock.advance(1)
    assert api.uploads == []

    run(ingester, clock, 3)
    assert len(api.uploads) == 1


def test_no_sidecar_waits_grace_period_then_uses_filename(setup):
    folder, clock, api, ingester = setup
    drop(folder, "ST02_Wheat_20260512_001.jpg")
    ingester.add_existing()

    run(ingester, clock, 4)  # stable after 2 s, but still inside the 5 s sidecar grace
    assert api.uploads == []

    run(ingester, clock, 4)
    assert api.uploads == [
        (
            "ST02_Wheat_20260512_001.jpg",
            {"station_id": "ST02", "crop_species": "Wheat", "capture_date": "2026-05-12"},
        )
    ]


def test_late_sidecar_is_still_used(setup):
    folder, clock, api, ingester = setup
    drop(folder, "ST02_Wheat_20260512_001.jpg")
    ingester.add_existing()
    run(ingester, clock, 3)

    sidecar = folder / "ST02_Wheat_20260512_001.json"
    sidecar.write_text(json.dumps({"crop_species": "Canola"}))
    ingester.add(sidecar)
    run(ingester, clock, 4)

    assert api.uploads[0][1] == {"crop_species": "Canola"}


def test_no_sidecar_and_bad_filename_goes_to_failed_with_reason(setup):
    folder, clock, api, ingester = setup
    drop(folder, "random_photo.jpg")
    ingester.add_existing()

    run(ingester, clock, 9)

    assert api.uploads == []
    reason = (folder / "failed" / "random_photo.jpg.reason.txt").read_text()
    assert "doesn't match" in reason


def test_api_rejection_goes_to_failed_with_sidecar(setup):
    folder, clock, api, ingester = setup
    api.results["fake.jpg"] = watcher.UploadResult("rejected", reason="HTTP 400: not an image")
    drop(folder, "fake.jpg", b"text", sidecar={"crop_species": "Wheat"})
    ingester.add_existing()

    run(ingester, clock, 3)

    assert (folder / "failed" / "fake.jpg").exists()
    assert (folder / "failed" / "fake.json").exists()
    assert "HTTP 400" in (folder / "failed" / "fake.jpg.reason.txt").read_text()


def test_duplicate_goes_to_processed(setup):
    folder, clock, api, ingester = setup
    api.results["again.jpg"] = watcher.UploadResult("duplicate", image_id=3)
    drop(folder, "again.jpg", sidecar={})
    ingester.add_existing()

    run(ingester, clock, 3)

    assert (folder / "processed" / "again.jpg").exists()


def test_unsupported_file_goes_to_failed_and_hidden_files_are_ignored(setup):
    folder, clock, api, ingester = setup
    drop(folder, "notes.txt")
    drop(folder, ".DS_Store")
    drop(folder, "big.jpg.part")
    ingester.add_existing()

    run(ingester, clock, 3)

    assert "unsupported file type .txt" in (folder / "failed" / "notes.txt.reason.txt").read_text()
    assert (folder / ".DS_Store").exists() and (folder / "big.jpg.part").exists()
    assert api.uploads == []


def test_files_in_processed_or_failed_are_never_picked_up(setup):
    folder, clock, api, ingester = setup
    (folder / "processed").mkdir()
    ingester.add(folder / "processed" / "old.jpg")
    assert ingester.pending == set()


def test_each_file_is_uploaded_only_once(setup):
    folder, clock, api, ingester = setup
    drop(folder, "leaf.jpg", sidecar={})
    ingester.add_existing()
    run(ingester, clock, 3)
    ingester.add(folder / "leaf.jpg")  # stale event after the move
    run(ingester, clock, 3)
    assert len(api.uploads) == 1


def test_one_log_line_per_file(setup, caplog):
    folder, clock, api, ingester = setup
    drop(folder, "leaf.jpg", sidecar={})
    drop(folder, "random_photo.jpg")
    ingester.add_existing()
    with caplog.at_level("INFO", logger="ingest"):
        run(ingester, clock, 9)
    lines = [r.getMessage() for r in caplog.records]
    assert len(lines) == 2
    assert lines[0] == "processed leaf.jpg -> image 1 (metadata from sidecar)"
    assert lines[1].startswith("failed random_photo.jpg: no sidecar, and filename doesn't match")
