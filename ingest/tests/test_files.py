import watcher


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_file_is_stable_only_after_two_unchanged_seconds(tmp_path):
    clock = FakeClock()
    tracker = watcher.StabilityTracker(clock)
    path = tmp_path / "a.jpg"
    path.write_bytes(b"x" * 10)

    assert not tracker.is_stable(path)  # first sighting
    clock.advance(1.9)
    assert not tracker.is_stable(path)
    clock.advance(0.2)
    assert tracker.is_stable(path)


def test_growing_file_resets_the_timer(tmp_path):
    clock = FakeClock()
    tracker = watcher.StabilityTracker(clock)
    path = tmp_path / "a.jpg"
    path.write_bytes(b"x" * 10)
    tracker.is_stable(path)

    clock.advance(1.5)
    path.write_bytes(b"x" * 20)  # station still writing
    assert not tracker.is_stable(path)
    clock.advance(1.5)
    assert not tracker.is_stable(path)  # only 1.5 s since it last changed
    clock.advance(0.6)
    assert tracker.is_stable(path)


def test_missing_file_is_not_stable(tmp_path):
    assert not watcher.StabilityTracker(FakeClock()).is_stable(tmp_path / "gone.jpg")


def test_move_to_keeps_image_and_sidecar_paired_and_never_overwrites(tmp_path):
    processed = tmp_path / "processed"
    processed.mkdir()
    (processed / "leaf.jpg").write_bytes(b"older")

    image = tmp_path / "leaf.jpg"
    sidecar = tmp_path / "leaf.json"
    image.write_bytes(b"new")
    sidecar.write_text("{}")

    target = watcher.move_to(processed, image, sidecar)

    assert target == processed / "leaf-1.jpg"
    assert (processed / "leaf.jpg").read_bytes() == b"older"
    assert (processed / "leaf-1.jpg").read_bytes() == b"new"
    assert (processed / "leaf-1.json").exists()
    assert not image.exists() and not sidecar.exists()


def test_move_to_writes_reason_file(tmp_path):
    image = tmp_path / "bad.jpg"
    image.write_bytes(b"x")
    watcher.move_to(tmp_path / "failed", image, None, "HTTP 400: nope")
    assert (tmp_path / "failed" / "bad.jpg.reason.txt").read_text() == "HTTP 400: nope\n"
