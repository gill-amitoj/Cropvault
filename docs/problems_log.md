# Problems log

Real problems hit while building CropVault. Format: date, problem, cause, fix.

## 2026-10-02 — Official MinIO Docker image cannot be pulled
- **Problem:** `docker pull minio/minio` fails with "pull access denied"; `quay.io/minio/minio`
  returns 401; the binary downloads at `dl.min.io` return HTTP 410 Gone.
- **Cause:** MinIO Inc. stopped distributing free community-edition images and binaries in
  2025. The source code is still AGPLv3, but there is no official prebuilt image any more.
- **Fix:** Use the `pgsty/minio` community build of the same AGPLv3 source, pinned to an
  exact tag (see docs/decisions.md, 2026-10-02).

## 2026-10-02 — Postgres container fails to start: port 5432 already allocated
- **Problem:** `docker compose up` failed with "Bind for 0.0.0.0:5432 failed: port is already
  allocated".
- **Cause:** The LedgerLens project's `ledgerlens-postgres` container already publishes host
  port 5432. Two containers can't bind the same host port.
- **Fix:** Publish CropVault's Postgres on host port 5433 (`5433:5432`). Inside Docker the API
  still uses `db:5432`, so no code or `.env` change was needed.

## 2026-10-02 — Images with sidecars waited ~4 s instead of 2 s
- **Problem:** Ingester tests expected an image with a sidecar to be uploaded after ~2 s; it took ~4 s.
- **Cause:** The sidecar's stability timer only started once the image itself was stable, so the two
  2-second waits ran one after the other instead of side by side.
- **Fix:** `process_pending()` now checks image and sidecar stability on every poll before deciding,
  so both timers run in parallel. (An earlier draft also called `tracker.forget()` on the sidecar's
  own pending entry, which would have reset its timer forever — caught in review before running.)
