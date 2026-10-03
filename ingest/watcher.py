"""CropVault ingestion service.

Watches a drop folder, waits until each image is fully written, reads its metadata (sidecar JSON
first, filename pattern second), uploads it through the API, then moves it to processed/ or
failed/. It never touches the database or object storage directly.
"""

import datetime as dt
import json
import logging
import mimetypes
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from watchdog.events import FileSystemEventHandler
from watchdog.observers.polling import PollingObserver

logger = logging.getLogger("ingest")

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
TEMP_SUFFIXES = {".part", ".tmp", ".crdownload", ".swp"}
SIDECAR_FIELDS = ("experiment_code", "crop_species", "station_id", "capture_date", "tags")

STABLE_SECONDS = 2.0  # trap #1: size + mtime unchanged this long = finished writing
SIDECAR_GRACE_SECONDS = 5.0  # extra wait for a sidecar that arrives after its image
POLL_SECONDS = 1.0
MAX_ATTEMPTS = 5  # network errors and 5xx; waits 1, 2, 4, 8 s between attempts

# STATION_SPECIES_YYYYMMDD_anything  e.g. ST02_Wheat_20260512_001.jpg
FILENAME_PATTERN = re.compile(
    r"^(?P<station>[A-Za-z0-9-]+)_(?P<species>[A-Za-z-]+)_(?P<date>\d{8})_.+$"
)


# --- metadata (trap #11) ------------------------------------------------------------------


class MetadataError(Exception):
    """No usable metadata: the file goes to failed/ with this message as the reason."""


def sidecar_path(image: Path) -> Path:
    """leaf01.jpg -> leaf01.json"""
    return image.with_suffix(".json")


def read_sidecar(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise MetadataError(f"sidecar {path.name} is not valid JSON") from None
    if not isinstance(data, dict):
        raise MetadataError(f"sidecar {path.name} must be a JSON object")
    fields = {}
    for key in SIDECAR_FIELDS:
        value = data.get(key)
        if value is None:
            continue
        if key == "tags" and isinstance(value, list):
            value = ",".join(str(tag) for tag in value)
        fields[key] = str(value)
    return fields


def parse_filename(name: str) -> dict:
    match = FILENAME_PATTERN.match(Path(name).stem)
    if not match:
        raise MetadataError("no sidecar, and filename doesn't match STATION_SPECIES_YYYYMMDD_*")
    try:
        date = dt.datetime.strptime(match["date"], "%Y%m%d").date()
    except ValueError:
        raise MetadataError(f"no sidecar, and filename date {match['date']} is invalid") from None
    return {
        "station_id": match["station"],
        "crop_species": match["species"],
        "capture_date": date.isoformat(),
    }


def find_metadata(image: Path, sidecar: Path | None) -> dict:
    """Sidecar wins; the filename is only used when there is no sidecar."""
    if sidecar is not None:
        return read_sidecar(sidecar)
    return parse_filename(image.name)


# --- files --------------------------------------------------------------------------------


def classify(path: Path) -> str:
    """'image', 'sidecar', 'ignore' (hidden/temp) or 'other' (unsupported)."""
    name = path.name
    suffix = path.suffix.lower()
    if name.startswith(".") or suffix in TEMP_SUFFIXES:
        return "ignore"
    if suffix == ".json" or name.endswith(".reason.txt"):
        return "sidecar"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    return "other"


def move_to(folder: Path, image: Path, sidecar: Path | None, reason: str | None = None) -> Path:
    """Move the image (and its sidecar) into folder without overwriting anything there.
    On a name clash both get the same -1, -2... suffix so they stay paired.
    If a reason is given, write it to <image name>.reason.txt next to the moved file."""
    folder.mkdir(exist_ok=True)
    stem, n = image.stem, 0
    while any(
        (folder / name).exists()
        for name in (f"{stem}{image.suffix}", f"{stem}.json", f"{stem}{image.suffix}.reason.txt")
    ):
        n += 1
        stem = f"{image.stem}-{n}"
    target = folder / f"{stem}{image.suffix}"
    shutil.move(image, target)
    if sidecar is not None and sidecar.exists():
        shutil.move(sidecar, folder / f"{stem}.json")
    if reason:
        (folder / f"{target.name}.reason.txt").write_text(reason + "\n", encoding="utf-8")
    return target


class StabilityTracker:
    """Trap #1: a file counts as finished only after its size and mtime have stayed the same
    for STABLE_SECONDS. Call is_stable() on every poll."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.seen = {}  # path -> ((size, mtime_ns), time first seen with that signature)

    def is_stable(self, path: Path) -> bool:
        try:
            stat = path.stat()
        except FileNotFoundError:
            self.seen.pop(path, None)
            return False
        signature = (stat.st_size, stat.st_mtime_ns)
        now = self.clock()
        previous = self.seen.get(path)
        if previous is None or previous[0] != signature:
            self.seen[path] = (signature, now)
            return False
        return now - previous[1] >= STABLE_SECONDS

    def forget(self, path: Path) -> None:
        self.seen.pop(path, None)


# --- API client (retries, trap #2) --------------------------------------------------------


@dataclass
class UploadResult:
    outcome: str  # "created", "duplicate", "rejected", "unavailable"
    image_id: int | None = None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome in ("created", "duplicate")


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except ValueError:
        return response.text[:200]
    return detail if isinstance(detail, str) else json.dumps(detail)


class ApiClient:
    def __init__(self, base_url, email, password, http=None, sleep=time.sleep):
        self.http = http or httpx.Client(base_url=base_url, timeout=30)
        self.email = email
        self.password = password
        self.sleep = sleep
        self.token = None

    def login(self) -> None:
        response = self.http.post(
            "/auth/login", json={"email": self.email, "password": self.password}
        )
        response.raise_for_status()
        self.token = response.json()["access_token"]

    def upload(self, path: Path, fields: dict) -> UploadResult:
        """201 -> created; 409 -> duplicate (success: reprocessing is always safe).
        401 -> log in again once. Other 4xx -> rejected, no retry.
        Network errors and 5xx -> retry with exponential backoff, MAX_ATTEMPTS in total."""
        relogged = False
        reason = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                if self.token is None:
                    self.login()
                content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                with path.open("rb") as file:
                    response = self.http.post(
                        "/images",
                        files={"file": (path.name, file, content_type)},
                        data=fields,
                        headers={"Authorization": f"Bearer {self.token}"},
                    )
            except httpx.TransportError as exc:
                reason = f"network error: {exc.__class__.__name__}"
            except httpx.HTTPStatusError as exc:  # from login()
                if exc.response.status_code < 500:
                    return UploadResult("rejected", reason=f"login failed: {_detail(exc.response)}")
                reason = f"login HTTP {exc.response.status_code}"
            else:
                status = response.status_code
                if status == 201:
                    return UploadResult("created", image_id=response.json()["id"])
                if status == 409:
                    return UploadResult("duplicate", image_id=response.json()["detail"]["image_id"])
                if status == 401 and not relogged:
                    self.token, relogged = None, True  # token expired: log in again, no wait
                    continue
                if status < 500:
                    return UploadResult("rejected", reason=f"HTTP {status}: {_detail(response)}")
                reason = f"HTTP {status}"
            if attempt < MAX_ATTEMPTS:
                delay = 2 ** (attempt - 1)
                logger.warning(
                    "%s: attempt %d failed (%s); retrying in %ds", path.name, attempt, reason, delay
                )
                self.sleep(delay)
        return UploadResult(
            "unavailable", reason=f"API unavailable after {MAX_ATTEMPTS} attempts ({reason})"
        )


# --- the ingester -------------------------------------------------------------------------


class Ingester:
    """Holds the set of files to look at. The watchdog thread adds paths; the main loop calls
    process_pending() every POLL_SECONDS."""

    def __init__(self, watch_dir: Path, api, clock=time.monotonic):
        self.watch_dir = watch_dir
        self.processed_dir = watch_dir / "processed"
        self.failed_dir = watch_dir / "failed"
        self.api = api
        self.clock = clock
        self.tracker = StabilityTracker(clock)
        self.pending = set()
        self.lock = threading.Lock()
        self.stable_since = {}  # image -> when it became stable without a sidecar

    def add(self, path: Path) -> None:
        # Only files directly in the drop folder (not processed/ or failed/).
        if path.parent == self.watch_dir:
            with self.lock:
                self.pending.add(path)

    def add_existing(self) -> None:
        """Startup: files already waiting in the folder are processed too."""
        for path in self.watch_dir.iterdir():
            if path.is_file():
                self.add(path)

    def _done(self, *paths) -> None:
        with self.lock:
            for path in paths:
                self.pending.discard(path)
                self.tracker.forget(path)
        self.stable_since.pop(paths[0], None)

    def process_pending(self) -> None:
        with self.lock:
            snapshot = sorted(self.pending)
        for path in snapshot:
            kind = classify(path)
            if kind in ("ignore", "sidecar"):
                # Sidecars travel with their image (whose check tracks the sidecar's stability).
                with self.lock:
                    self.pending.discard(path)
                continue
            if not path.exists():
                self._done(path)
                continue
            # Check the image and its sidecar on every poll, so both 2 s timers run in parallel.
            sidecar = sidecar_path(path)
            image_stable = self.tracker.is_stable(path)
            sidecar_stable = self.tracker.is_stable(sidecar) if sidecar.exists() else False
            if not image_stable:
                continue
            if kind == "other":
                self._fail(path, None, f"unsupported file type {path.suffix or '(none)'}")
                continue

            if sidecar.exists():
                if not sidecar_stable:
                    continue  # sidecar still being written
            else:
                first = self.stable_since.setdefault(path, self.clock())
                if self.clock() - first < SIDECAR_GRACE_SECONDS:
                    continue  # give a late sidecar a chance
                sidecar = None
            self.handle_image(path, sidecar)

    def handle_image(self, image: Path, sidecar: Path | None) -> None:
        try:
            fields = find_metadata(image, sidecar)
        except MetadataError as exc:
            self._fail(image, sidecar, str(exc))
            return
        source = "sidecar" if sidecar else "filename"
        result = self.api.upload(image, fields)
        if not result.ok:
            self._fail(image, sidecar, result.reason)
            return
        move_to(self.processed_dir, image, sidecar)
        self._done(image, sidecar_path(image))
        if result.outcome == "created":
            logger.info(
                "processed %s -> image %s (metadata from %s)", image.name, result.image_id, source
            )
        else:
            logger.info("processed %s -> duplicate of image %s", image.name, result.image_id)

    def _fail(self, image: Path, sidecar: Path | None, reason: str) -> None:
        move_to(self.failed_dir, image, sidecar, reason)
        self._done(image, sidecar_path(image))
        logger.warning("failed %s: %s", image.name, reason)


class DropHandler(FileSystemEventHandler):
    def __init__(self, ingester: Ingester):
        self.ingester = ingester

    def on_created(self, event):
        if not event.is_directory:
            self.ingester.add(Path(event.src_path))

    def on_modified(self, event):
        if not event.is_directory:
            self.ingester.add(Path(event.src_path))

    def on_moved(self, event):
        if not event.is_directory:
            self.ingester.add(Path(event.dest_path))


def wait_for_login(api: ApiClient) -> None:
    """Keep trying until the API answers. Wrong credentials are a config error: stop."""
    while True:
        try:
            api.login()
            logger.info("Logged in to the API as %s", api.email)
            return
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:
                raise SystemExit(
                    f"Login rejected for {api.email}: {_detail(exc.response)}"
                ) from None
            logger.warning("API returned %s on login; retrying in 5s", exc.response.status_code)
        except httpx.TransportError:
            logger.warning("API not reachable yet; retrying in 5s")
        time.sleep(5)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per file, not per request
    watch_dir = Path(os.environ.get("WATCH_DIR", "/data/station_drop"))
    watch_dir.mkdir(parents=True, exist_ok=True)
    api = ApiClient(
        os.environ.get("API_URL", "http://api:8000/api"),
        os.environ["INGEST_EMAIL"],
        os.environ["INGEST_PASSWORD"],
    )
    wait_for_login(api)

    ingester = Ingester(watch_dir, api)
    ingester.add_existing()
    # Polling works on Docker Desktop bind mounts, where native file events often don't arrive.
    observer = PollingObserver(timeout=POLL_SECONDS)
    observer.schedule(DropHandler(ingester), str(watch_dir), recursive=False)
    observer.start()
    logger.info("Watching %s", watch_dir)
    try:
        while True:
            ingester.process_pending()
            time.sleep(POLL_SECONDS)
    finally:
        observer.stop()
        observer.join()


if __name__ == "__main__":
    main()
