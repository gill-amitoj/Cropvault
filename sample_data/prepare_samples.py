"""Build the sample ingestion set from real, openly licensed Wikimedia Commons photos.

Downloads each photo, prepares it (EXIF orientation applied, resized, metadata stripped),
writes the sidecar .json files, adds the deliberate failure cases, and writes CREDITS.md from
the same list, so the credits always match the files.

Run (Pillow is installed in the api image; needs internet):
    docker compose run --rm -v ./sample_data:/sample_data api python /sample_data/prepare_samples.py
"""

import io
import json
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import ExifTags, Image, ImageOps

HERE = Path(__file__).parent
OUT = HERE / "station_drop"
CACHE = HERE / ".cache"  # downloaded originals (gitignored), so re-runs don't re-download
USER_AGENT = "cropvault-sample-builder/1.0 (https://github.com/gill-amitoj/Cropvault)"
COMMONS = "https://upload.wikimedia.org/wikipedia/commons/"

# Source photos: verified on each Wikimedia Commons file page (licence + author).
PHOTOS = {
    "wheat_field": (
        "Wheat P1210892.jpg",
        "9/96/Wheat_P1210892.jpg",
        "David Monniaux",
        "CC BY-SA 3.0",
        "https://creativecommons.org/licenses/by-sa/3.0/",
    ),
    "wheat_closeup": (
        "Wheat close-up.JPG",
        "b/b4/Wheat_close-up.JPG",
        "Bluemoose",
        "CC BY-SA 3.0",
        "https://creativecommons.org/licenses/by-sa/3.0/",
    ),
    "spelt_leaf": (
        "Triticum spelta sl11.jpg",
        "b/b9/Triticum_spelta_sl11.jpg",
        "Stefan.lefnaer",
        "CC BY-SA 4.0",
        "https://creativecommons.org/licenses/by-sa/4.0/",
    ),
    "wheat_ear_sky": (
        "Triticum aestivum.jpg",
        "6/64/Triticum_aestivum.jpg",
        "Andreas Trepte",
        "CC BY-SA 2.5",
        "https://creativecommons.org/licenses/by-sa/2.5/",
    ),
    "wheat_rust_1": (
        "Puccinia recondita f.sp. tritici on Triticum aestivum, Bruine roest op gewone tarwe.jpg",
        "e/ee/Puccinia_recondita_f.sp._tritici_on_Triticum_aestivum%2C_Bruine_roest_op_gewone_tarwe.jpg",
        "Rasbak",
        "CC BY-SA 3.0",
        "https://creativecommons.org/licenses/by-sa/3.0/",
    ),
    "wheat_rust_2": (
        "Puccinia triticina (03).jpg",
        "0/08/Puccinia_triticina_%2803%29.jpg",
        "bjoerns",
        "CC BY-SA 4.0",
        "https://creativecommons.org/licenses/by-sa/4.0/",
    ),
    "canola_flowering": (
        "Rapsfeld Rapeseed Brassica napus.jpg",
        "9/90/Rapsfeld_Rapeseed_Brassica_napus.jpg",
        "Richard Bartz",
        "CC BY-SA 2.5",
        "https://creativecommons.org/licenses/by-sa/2.5/",
    ),
    "canola_green": (
        "Brassica napus habit1 (14678237071).jpg",
        "7/73/Brassica_napus_habit1_%2814678237071%29.jpg",
        "Harry Rose",
        "CC BY 2.0",
        "https://creativecommons.org/licenses/by/2.0/",
    ),
    "canola_leaf_studio": (
        "Brassica napus 04 ies.jpg",
        "b/b5/Brassica_napus_04_ies.jpg",
        "Frank Vincentz",
        "CC BY-SA 3.0",
        "https://creativecommons.org/licenses/by-sa/3.0/",
    ),
    "canola_leaf_field": (
        "Brassica napus lower stem leave, koolzaad onderste stengelblad (1)bewerkt.jpg",
        "9/93/Brassica_napus_lower_stem_leave%2C_koolzaad_onderste_stengelblad_%281%29bewerkt.jpg",
        "Rasbak",
        "CC BY-SA 3.0",
        "https://creativecommons.org/licenses/by-sa/3.0/",
    ),
    "wheat_ripe": (
        "Triticum aestivum ripe, Tarwe oogstrijp.jpg",
        "5/51/Triticum_aestivum_ripe%2C_Tarwe_oogstrijp.jpg",
        "Rasbak",
        "CC BY-SA 3.0",
        "https://creativecommons.org/licenses/by-sa/3.0/",
    ),
    "barley_green": (
        "Escourgeon-Hordeum vulgare subsp. vulgare.jpg",
        "5/52/Escourgeon-Hordeum_vulgare_subsp._vulgare.jpg",
        "raul.dupagne",
        "Public domain",
        None,
    ),
    "barley_field": (
        "A large barley field - geograph.org.uk - 5461065.jpg",
        "8/8f/A_large_barley_field_-_geograph.org.uk_-_5461065.jpg",
        "Philip Halling",
        "CC BY-SA 2.0",
        "https://creativecommons.org/licenses/by-sa/2.0/",
    ),
    "barley_heads": (
        "Wintergerste Aehre vor Bluete.jpg",
        "3/39/Wintergerste_Aehre_vor_Bluete.jpg",
        "Florian Gerlach (Nawaro)",
        "CC BY-SA 3.0",
        "https://creativecommons.org/licenses/by-sa/3.0/",
    ),
    "barley_ripe": (
        "HordeumVulgare001.JPG",
        "9/97/HordeumVulgare001.JPG",
        "Hugo.arg",
        "CC BY-SA 3.0",
        "https://creativecommons.org/licenses/by-sa/3.0/",
    ),
    "oat_closeup": (
        "LPCC-507-Espiguetes de civada.jpg",
        "b/be/LPCC-507-Espiguetes_de_civada.jpg",
        "Miquel Pujol",
        "CC BY-SA 3.0",
        "https://creativecommons.org/licenses/by-sa/3.0/",
    ),
    "oat_panicle": (
        "Avena sativa II.jpg",
        "3/3c/Avena_sativa_II.jpg",
        "Andreas Trepte",
        "CC BY-SA 2.5",
        "https://creativecommons.org/licenses/by-sa/2.5/",
    ),
    "barley_ladybird": (
        "A lady beetle perches on barley.JPG",
        "6/6e/A_lady_beetle_perches_on_barley.JPG",
        "T.Voekler",
        "CC BY-SA 3.0",
        "https://creativecommons.org/licenses/by-sa/3.0/",
    ),
}

WHEAT = {"experiment_code": "EXP-2026-001", "crop_species": "Wheat", "station_id": "ST01"}
CANOLA = {"experiment_code": "EXP-2026-002", "crop_species": "Canola", "station_id": "ST05"}

# (output file, source photo, how to prepare it, sidecar fields or None)
SAMPLES = [
    # 1. Sidecar metadata (preferred path)
    (
        "wheat_plot01_day01.jpg",
        "wheat_field",
        "jpg",
        {**WHEAT, "capture_date": "2026-05-01", "tags": ["drought", "field"]},
    ),
    (
        "wheat_plot01_day08.jpg",
        "wheat_closeup",
        "jpg",
        {**WHEAT, "capture_date": "2026-05-08", "tags": ["drought", "ear"]},
    ),
    (
        "wheat_plot02_day01.jpg",
        "spelt_leaf",
        "jpg",
        {**WHEAT, "capture_date": "2026-05-01", "tags": ["control", "leaf"]},
    ),
    (
        "wheat_plot02_day08.jpg",
        "wheat_ear_sky",
        "jpg",
        {**WHEAT, "capture_date": "2026-05-08", "tags": ["control", "ear"]},
    ),
    (
        "wheat_leafrust_01.jpg",
        "wheat_rust_1",
        "jpg",
        {**WHEAT, "capture_date": "2026-05-15", "tags": ["rust", "leaf", "disease"]},
    ),
    (
        "wheat_leafrust_02.jpg",
        "wheat_rust_2",
        "jpg",
        {**WHEAT, "capture_date": "2026-05-22", "tags": ["rust", "leaf", "disease"]},
    ),
    (
        "canola_field_a_001.jpg",
        "canola_flowering",
        "jpg",
        {**CANOLA, "capture_date": "2026-06-02", "tags": ["flowering", "field"]},
    ),
    (
        "canola_field_a_002.jpg",
        "canola_green",
        "jpg",
        {**CANOLA, "capture_date": "2026-06-02", "tags": ["healthy", "field"]},
    ),
    (
        "canola_leaf_scan_01.tif",
        "canola_leaf_studio",
        "tif",
        {**CANOLA, "station_id": "LAB1", "capture_date": "2026-06-03", "tags": ["leaf", "scan"]},
    ),
    # Simulated phone photo: stored sideways + EXIF orientation 6; date comes from EXIF only
    (
        "canola_phone_rotated.jpg",
        "canola_leaf_field",
        "phone",
        {**CANOLA, "station_id": "PHONE", "tags": ["phone", "leaf"]},
    ),
    # 2. No sidecar: metadata from STATION_SPECIES_YYYYMMDD_*.ext
    ("ST02_Wheat_20260512_001.jpg", "wheat_ripe", "jpg", None),
    ("ST03_Barley_20260514_001.jpg", "barley_green", "jpg", None),
    ("ST03_Barley_20260514_002.png", "barley_field", "png", None),
    ("ST03_Barley_20260514_003.jpg", "barley_heads", "jpg", None),
    ("ST03_Barley_20260514_004.jpg", "barley_ripe", "jpg", None),
    ("ST04_Oat_20260516_001.tif", "oat_closeup", "tif", None),
    ("ST04_Oat_20260516_002.jpg", "oat_panicle", "jpg", None),
    # 4. Must end up in failed/ (real photos where an image is needed)
    ("random_photo.jpg", "barley_ladybird", "jpg", None),  # no sidecar, no pattern
    ("ST04_Oat_20261399_001.jpg", "oat_panicle", "crop", None),  # impossible date
    # Different bytes from its source on purpose: an exact copy would hit the duplicate
    # check (409) before the experiment check (400) that this sample demonstrates.
    (
        "unknown_experiment.jpg",
        "barley_heads",
        "crop",
        {"experiment_code": "EXP-9999", "crop_species": "Barley"},
    ),
]

# Long side in pixels per output type: keeps the repo small while still sharp on screen.
MAX_SIDE = {"jpg": 1280, "phone": 1280, "crop": 1000, "png": 768, "tif": 768}
CHANGES = {
    "jpg": "resized to max 1280 px, metadata removed",
    "png": "resized to max 768 px, metadata removed, converted to PNG",
    "tif": "resized to max 768 px, metadata removed, converted to TIFF",
    "crop": "centre-cropped to 70%, resized to max 1000 px, metadata removed",
    "phone": "resized to max 1280 px, stored rotated with EXIF Orientation=6 and a "
    "synthetic EXIF date to simulate a phone photo",
}


def download(path: str) -> Image.Image:
    """Fetch an original from Commons (or the local cache). Polite: pauses between requests
    and backs off when Wikimedia answers 429 Too Many Requests."""
    cached = CACHE / path.replace("/", "_")
    if not cached.exists():
        request = urllib.request.Request(COMMONS + path, headers={"User-Agent": USER_AGENT})
        for attempt in range(1, 6):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    data = response.read()
                break
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or attempt == 5:
                    raise
                wait = int(exc.headers.get("Retry-After") or 10 * attempt)
                print(f"  rate limited; waiting {wait}s")
                time.sleep(wait)
        CACHE.mkdir(exist_ok=True)
        cached.write_bytes(data)
        time.sleep(2)
    return Image.open(io.BytesIO(cached.read_bytes()))


def prepare(img: Image.Image, how: str) -> Image.Image:
    """Upright, RGB, resized copy with no metadata carried over."""
    img = ImageOps.exif_transpose(img).convert("RGB")
    if how == "crop":
        w, h = img.size
        img = img.crop((int(w * 0.15), int(h * 0.15), int(w * 0.85), int(h * 0.85)))
    img.thumbnail((MAX_SIDE[how], MAX_SIDE[how]), Image.Resampling.LANCZOS)
    return img


def save(img: Image.Image, name: str, how: str) -> None:
    path = OUT / name
    if how == "png":
        img.save(path, "PNG", optimize=True)
    elif how == "tif":
        img.save(path, "TIFF", compression="tiff_lzw")
    elif how == "phone":
        # A phone stores pixels sideways and adds "rotate 90 deg clockwise to display".
        exif = Image.Exif()
        exif[ExifTags.Base.Orientation] = 6
        exif[ExifTags.Base.Make] = "SimulatedPhone"
        exif.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.DateTimeOriginal] = "2026:05:20 09:15:00"
        img.rotate(90, expand=True).save(path, "JPEG", quality=85, exif=exif)
    else:
        img.save(path, "JPEG", quality=85)


def write_sidecar(name: str, fields: dict) -> None:
    (OUT / name).with_suffix(".json").write_text(json.dumps(fields, indent=2) + "\n")


def write_credits(used: dict) -> None:
    lines = [
        "# Sample photo credits",
        "",
        "All sample images are derived from photos on Wikimedia Commons. Each keeps its original",
        "licence; files derived from CC BY-SA photos are shared under the same licence.",
        "Generated by `prepare_samples.py` - do not edit by hand.",
        "",
        "| Sample file | Source photo | Author | Licence | Changes |",
        "|---|---|---|---|---|",
    ]
    for name, (key, how) in used.items():
        title, path, author, licence, licence_url = PHOTOS[key]
        page = "https://commons.wikimedia.org/wiki/File:" + path.split("/", 2)[2]
        licence_md = f"[{licence}]({licence_url})" if licence_url else licence
        lines.append(f"| `{name}` | [{title}]({page}) | {author} | {licence_md} | {CHANGES[how]} |")
    lines += [
        "",
        "`wheat_plot01_day01_resend.jpg` is a byte-for-byte copy of `wheat_plot01_day01.jpg`",
        "(same credit). `corrupt_scan.jpg` and `operator_notes.txt` are plain text written for the",
        "demo. The sidecar `.json` metadata (stations, dates, experiments, tags) is fictional.",
        "",
    ]
    (HERE / "CREDITS.md").write_text("\n".join(lines))


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    cache, used = {}, {}
    for name, key, how, sidecar in SAMPLES:
        if key not in cache:
            print(f"downloading {PHOTOS[key][0]}")
            cache[key] = download(PHOTOS[key][1])
        save(prepare(cache[key], how), name, how)
        if sidecar is not None:
            write_sidecar(name, sidecar)
        used[name] = (key, how)

    # 3. Duplicate: same bytes as wheat_plot01_day01.jpg under a new name -> 409
    shutil.copyfile(OUT / "wheat_plot01_day01.jpg", OUT / "wheat_plot01_day01_resend.jpg")
    write_sidecar("wheat_plot01_day01_resend.jpg", {**WHEAT, "capture_date": "2026-05-01"})

    # 4. More failure cases that need no photo
    (OUT / "corrupt_scan.jpg").write_bytes(b"this is not an image, just text named .jpg\n")
    write_sidecar("corrupt_scan.jpg", {"crop_species": "Wheat", "station_id": "ST01"})  # API -> 400
    (OUT / "operator_notes.txt").write_text("Shift notes: nothing unusual.\n")  # unsupported

    write_credits(used)
    files = [p for p in OUT.iterdir() if p.suffix != ".json"]
    size_mb = sum(p.stat().st_size for p in OUT.iterdir()) / 1024 / 1024
    print(f"Wrote {len(files)} files (+ sidecars), {size_mb:.1f} MB, and CREDITS.md")


if __name__ == "__main__":
    main()
