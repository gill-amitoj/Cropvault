# Decisions

Judgment calls not already fixed in CLAUDE.md. Format: date, decision, alternatives, reason.

## 2026-10-02 — `/api/health` returns 503 when a dependency is down
- **Decision:** Return 200 `{"status":"ok","db":"ok","minio":"ok"}` when both checks pass,
  otherwise 503 with each check marked `ok` or `error`.
- **Alternatives:** Always return 200 and put the status only in the body.
- **Reason:** Docker, load balancers and monitoring tools look at the status code. The
  per-check body shows *which* dependency broke without reading logs. Error details are
  logged, not returned, so internal hostnames/messages aren't exposed.

## 2026-10-02 — CI runs plain Python, not Docker Compose
- **Decision:** GitHub Actions installs `backend/requirements.txt` on the runner and runs
  `ruff check`, `ruff format --check` and `pytest`.
- **Alternatives:** Run `docker compose up` in CI and test inside containers.
- **Reason:** Unit tests fake the DB and storage (monkeypatch), so no services are needed.
  This is faster and has fewer moving parts. Trade-off: CI does not prove the Docker
  images build; that is checked locally with `docker compose up --build`.

## 2026-10-02 — Python 3.12 in the API image
- **Decision:** `python:3.12-slim` base image; ruff targets py312; CI uses 3.12.
- **Alternatives:** `python:3.11-slim` (the minimum in CLAUDE.md).
- **Reason:** Current, stable, supported by every library we use. Slim keeps the image small.

## 2026-10-02 — Object storage: `pgsty/minio` community build
- **Decision:** Use `pgsty/minio:RELEASE.2026-08-04T00-00-00Z`, a community build of the
  MinIO AGPLv3 source. Pinned to an exact tag. Backend still uses the `minio` Python client.
- **Alternatives:** RustFS (Apache-2.0, MinIO-compatible, younger project); SeaweedFS
  (Apache-2.0, mature, heavier config, no MinIO-style console).
- **Reason:** Official MinIO images/binaries are no longer distributed (see
  problems_log.md). The fork is the same server, so the console, env vars and CLAUDE.md all
  stay accurate. Risk: depends on a small third-party maintainer; pinning the tag means an
  upstream change can't silently break us, and switching to RustFS later would need no code
  changes because both speak the S3 API.

## 2026-10-02 — Bucket is created by the API on startup
- **Decision:** On startup the API calls `ensure_bucket()` (create if missing). If MinIO is
  unreachable it logs the error and keeps running; `/health` then reports `minio: error`.
- **Alternatives:** A separate one-shot `mc mb` container in Compose.
- **Reason:** One fewer service, and the logic lives in Python where it can be tested.

## 2026-10-02 — Postgres published on host port 5433
- **Decision:** Compose maps `5433:5432` for the `db` service.
- **Alternatives:** No host port at all (most isolated, use `docker compose exec db psql`);
  keep 5432 and stop LedgerLens whenever CropVault runs.
- **Reason:** Lets both projects run at once and still allows psql/GUI access from the host at
  `localhost:5433`. The API is unaffected because it connects to `db:5432` inside Docker.
