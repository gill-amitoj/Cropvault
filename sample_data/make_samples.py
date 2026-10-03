"""Generate SYNTHETIC sample images + sidecars for the ingestion demo.

These are drawn shapes, not real plant photos. Replace them with real CC0/public-domain photos
(and note each source + licence in sample_data/README.md) before taking README screenshots.

Run (Pillow is installed in the api image):
    docker compose run --rm -v ./sample_data:/sample_data api python /sample_data/make_samples.py

Every ingestion path is covered: sidecar metadata, filename-pattern metadata, PNG/TIFF, a rotated
(EXIF orientation 6) photo, a duplicate resend, and five files that must end up in failed/.
"""

import io
import json
import random
from pathlib import Path

from PIL import ExifTags, Image, ImageDraw

OUT = Path(__file__).parent / "station_drop"


def leaf_image(seed: int, size=(1024, 768)) -> Image.Image:
    """Soil-coloured background with a few leaf-like green ellipses (deterministic per seed)."""
    rng = random.Random(seed)
    img = Image.new("RGB", size, (110 + rng.randint(-15, 15), 80, 50))
    draw = ImageDraw.Draw(img)
    for _ in range(rng.randint(3, 7)):
        x, y = rng.randint(0, size[0] - 300), rng.randint(0, size[1] - 200)
        w, h = rng.randint(150, 300), rng.randint(60, 160)
        green = (rng.randint(30, 90), rng.randint(120, 200), rng.randint(30, 80))
        draw.ellipse((x, y, x + w, y + h), fill=green, outline=(20, 60, 20), width=3)
        if rng.random() < 0.4:  # a "lesion"
            cx, cy = x + w // 2, y + h // 2
            draw.ellipse((cx - 12, cy - 9, cx + 12, cy + 9), fill=(140, 100, 40))
    return img


def save(img: Image.Image, name: str, fmt: str, exif=None) -> bytes:
    buffer = io.BytesIO()
    kwargs = {"exif": exif} if exif is not None else {}
    if fmt == "JPEG":
        kwargs["quality"] = 85
    if fmt == "TIFF":
        kwargs["compression"] = "tiff_lzw"
    img.save(buffer, fmt, **kwargs)
    data = buffer.getvalue()
    (OUT / name).write_bytes(data)
    return data


def sidecar(name: str, **fields) -> None:
    (OUT / name).with_suffix(".json").write_text(json.dumps(fields, indent=2) + "\n")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.iterdir():
        old.unlink()

    # 1. Sidecar metadata (preferred path) -------------------------------------------------
    wheat = [
        ("wheat_plot01_day01.jpg", "2026-05-01", ["drought", "leaf"]),
        ("wheat_plot01_day08.jpg", "2026-05-08", ["drought", "leaf"]),
        ("wheat_plot02_day01.jpg", "2026-05-01", ["control", "leaf"]),
        ("wheat_plot02_day08.jpg", "2026-05-08", ["control", "leaf"]),
    ]
    for n, (name, date, tags) in enumerate(wheat):
        save(leaf_image(100 + n), name, "JPEG")
        sidecar(name, experiment_code="EXP-2026-001", crop_species="Wheat",
                station_id="ST01", capture_date=date, tags=tags)  # fmt: skip

    canola = [
        ("canola_field_a_001.jpg", "2026-06-02", ["rust", "leaf"]),
        ("canola_field_a_002.jpg", "2026-06-02", ["healthy", "leaf"]),
    ]
    for n, (name, date, tags) in enumerate(canola):
        save(leaf_image(200 + n), name, "JPEG")
        sidecar(name, experiment_code="EXP-2026-002", crop_species="Canola",
                station_id="ST05", capture_date=date, tags=tags)  # fmt: skip

    save(leaf_image(300), "canola_field_b_scan.png", "PNG")
    sidecar("canola_field_b_scan.png", experiment_code="EXP-2026-002", crop_species="Canola",
            station_id="ST05", capture_date="2026-06-03", tags=["rust", "scan"])  # fmt: skip

    save(leaf_image(310, size=(800, 600)), "wheat_microscope_01.tif", "TIFF")
    sidecar("wheat_microscope_01.tif", experiment_code="EXP-2026-001", crop_species="Wheat",
            station_id="MICRO1", capture_date="2026-05-15", tags=["microscope"])  # fmt: skip

    # Phone photo stored sideways with EXIF orientation 6; capture date from EXIF only.
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = 6
    exif[ExifTags.Base.Make] = "SyntheticCam"
    exif.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.DateTimeOriginal] = "2026:05:20 09:15:00"
    save(leaf_image(320), "wheat_phone_rotated.jpg", "JPEG", exif=exif)
    sidecar("wheat_phone_rotated.jpg", experiment_code="EXP-2026-001", crop_species="Wheat",
            station_id="PHONE", tags=["phone"])  # fmt: skip

    # 2. No sidecar: metadata from STATION_SPECIES_YYYYMMDD_*.ext -------------------------
    for n, name in enumerate(
        [
            "ST02_Wheat_20260512_001.jpg",
            "ST02_Wheat_20260512_002.jpg",
            "ST03_Barley_20260514_001.jpg",
            "ST03_Barley_20260514_002.png",
            "ST04_Oat_20260516_001.tif",
        ]
    ):
        fmt = {"jpg": "JPEG", "png": "PNG", "tif": "TIFF"}[name.rsplit(".", 1)[1]]
        save(leaf_image(400 + n), name, fmt)

    # 3. Duplicate: same bytes as wheat_plot01_day01.jpg, resent under a new name -> 409 -----
    original = (OUT / "wheat_plot01_day01.jpg").read_bytes()
    (OUT / "wheat_plot01_day01_resend.jpg").write_bytes(original)
    sidecar("wheat_plot01_day01_resend.jpg", experiment_code="EXP-2026-001",
            crop_species="Wheat", station_id="ST01", capture_date="2026-05-01")  # fmt: skip

    # 4. Must end up in failed/ ------------------------------------------------------------
    save(leaf_image(500), "random_photo.jpg", "JPEG")  # no sidecar, no pattern
    save(leaf_image(501), "ST04_Oat_20261399_001.jpg", "JPEG")  # impossible date
    (OUT / "corrupt_scan.jpg").write_bytes(b"this is not an image, just text named .jpg\n")
    sidecar("corrupt_scan.jpg", crop_species="Wheat", station_id="ST01")  # API -> 400
    save(leaf_image(502), "unknown_experiment.jpg", "JPEG")
    sidecar("unknown_experiment.jpg", experiment_code="EXP-9999", crop_species="Wheat")  # 400
    (OUT / "operator_notes.txt").write_text("Shift notes: nothing unusual.\n")  # unsupported

    images = [p for p in OUT.iterdir() if p.suffix != ".json"]
    print(f"Wrote {len(images)} files (+ sidecars) to {OUT}")


if __name__ == "__main__":
    main()
