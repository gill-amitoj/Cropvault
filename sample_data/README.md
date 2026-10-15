# Sample data

`station_drop/` holds **real crop photos from Wikimedia Commons** (wheat, canola, barley, oat,
including wheat leaf rust) plus sidecar JSON files, built by `prepare_samples.py`.
Every photo's author, licence and source link is in [CREDITS.md](CREDITS.md). The metadata in
the sidecars (stations, dates, experiments, tags) is fictional, made up for the demo.

The set exercises every ingestion path:

| Files | Expected result |
|---|---|
| `wheat_*`, `canola_*` with a `.json` sidecar (JPEG and one TIFF) | `processed/`, metadata from sidecar |
| `canola_phone_rotated.jpg` (stored sideways + EXIF Orientation 6, simulated phone photo) | `processed/`, shown upright, capture date read from EXIF |
| `ST02_Wheat_20260512_001.jpg`, `ST03_Barley_…` (incl. one PNG), `ST04_Oat_…` (incl. one TIFF), no sidecar | `processed/`, metadata from filename |
| `wheat_plot01_day01_resend.jpg` (same bytes as `wheat_plot01_day01.jpg`) | `processed/`, API 409 = duplicate |
| `random_photo.jpg` (no sidecar, no pattern) | `failed/` |
| `ST04_Oat_20261399_001.jpg` (impossible date) | `failed/` |
| `corrupt_scan.jpg` (text, not an image) | `failed/`, API 400 |
| `unknown_experiment.jpg` (sidecar names `EXP-9999`) | `failed/`, API 400 |
| `operator_notes.txt` | `failed/`, unsupported file type |

Run the demo: `cp sample_data/station_drop/* data/station_drop/`

Rebuild the set (downloads the originals from Wikimedia Commons, needs internet):
`docker compose run --rm -v ./sample_data:/sample_data api python /sample_data/prepare_samples.py`

Licences: the photos keep their original licences (CC BY-SA 2.0-4.0, CC BY 2.0, public domain).
Files derived from CC BY-SA photos (resized, converted, cropped) are shared under the same
licence. If you reuse these images, keep the credits.
