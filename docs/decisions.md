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

## 2026-10-02 — Schema applied by the API on startup (Stage 1)
- **Decision:** On startup the API runs `db/schema.sql` then `db/seed.sql` (mounted read-only at
  `/db`). Both use `IF NOT EXISTS` / `ON CONFLICT DO NOTHING`, so every restart is safe.
- **Alternatives:** Postgres `docker-entrypoint-initdb.d` (runs only on an empty volume, and tests
  can't reuse it).
- **Reason:** The same `apply_schema()` works in Docker, tests and CI. Limitation: no migrations
  tool, so changing an existing table needs `docker compose down -v` (wipes data).

## 2026-10-02 — A database failure at startup stops the API
- **Decision:** If `apply_schema()` or `seed_admin()` fails, startup fails and the API exits.
  (MinIO failures at startup are only logged — see the bucket decision above.)
- **Alternatives:** Log and keep running, like the bucket check.
- **Reason:** Without tables the API can't serve any request, so failing loudly is clearer than
  running half-broken. Compose already waits for Postgres to be healthy before starting the API.

## 2026-10-02 — DB tests run against a real Postgres test database
- **Decision:** Tests use a separate `cropvault_test` database (created if missing, schema applied
  once per run, all tables truncated before each test). `clean_db` refuses to run unless the DB
  name ends in `_test`. CI adds a `postgres:16` service container. MinIO is still always faked.
- **Alternatives:** Fake the DB with monkeypatch everywhere.
- **Reason:** Constraints, RBAC queries and search filters only mean something against real SQL.
  This revises the Stage 0 "CI needs no services" decision, for the database only.

## 2026-10-02 — Crops block deletion of their original (`ON DELETE RESTRICT`)
- **Decision:** `images.parent_image_id` uses `ON DELETE RESTRICT`.
- **Alternatives:** `SET NULL` (crop survives but loses its source); `CASCADE` (silently deletes
  crops and leaves their MinIO objects orphaned).
- **Reason:** Traceability (trap #6): a derived image must always point at its source. To delete an
  original, delete its derived images first.

## 2026-10-02 — `experiment_id` is optional
- **Decision:** `images.experiment_id` is nullable.
- **Alternatives:** Required (every upload/sidecar must name an existing experiment).
- **Reason:** Ad-hoc uploads and ingested files without an experiment code still work.

## 2026-10-02 — Schema conventions
- **Decision:** `BIGINT GENERATED ALWAYS AS IDENTITY` ids; `TIMESTAMPTZ` for `created_at`;
  `CHECK` constraints (not Postgres ENUM types) for role, derivation, kind and action; emails must be
  lowercase (`CHECK (email = lower(email))`, the app lowercases before insert); `storage_key` UNIQUE;
  `CHECK ((parent_image_id IS NULL) = (derivation IS NULL))`.
- **Alternatives:** `SERIAL` ids; ENUM types; case-insensitive email via `citext`.
- **Reason:** Identity columns are the modern standard. CHECK lists are easy to read and to change
  (an ENUM value can't easily be removed). The lowercase rule stops `Bob@x.com` and `bob@x.com`
  becoming two accounts without needing an extension.

## 2026-10-02 — Existing admin is never overwritten by `.env`
- **Decision:** `seed_admin()` creates the admin only if the email doesn't exist; it never resets the
  password or role.
- **Alternatives:** Re-sync the password from `.env` on every startup.
- **Reason:** A password changed in the app must not be silently reverted by a restart.

## 2026-10-02 — Search indexes and what each one speeds up
- `idx_images_crop_species` (B-tree): `GET /images?species=wheat` → `WHERE crop_species = %s`.
- `idx_images_experiment_id` (B-tree): `?experiment=` → `WHERE experiment_id = %s`; also speeds up
  joins to `experiments`.
- `idx_images_capture_date` (B-tree): `?date_from=&date_to=` → range `WHERE capture_date BETWEEN`;
  B-trees are sorted, so ranges (and `ORDER BY capture_date`) are fast.
- `idx_images_station_id` (B-tree): `?station=` → `WHERE station_id = %s`.
- `idx_images_tags` (GIN): `?tags=` → `WHERE tags @> %s` / `tags && %s`. A B-tree can't look inside an
  array; GIN indexes each element, so "images tagged drought" doesn't scan every row.
- Not added: `sha256`, `email`, `code` and `storage_key` already get an index from their UNIQUE
  constraint. With ~20 sample images Postgres may still choose a sequential scan; the indexes matter
  as the table grows.
