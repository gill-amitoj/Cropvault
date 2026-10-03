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

## 2026-10-02 — JWT in memory + localStorage, not an httpOnly cookie (Stage 2, required note)
- **Decision (already made in CLAUDE.md):** The API returns the JWT in the login response body; the
  frontend keeps it in memory and `localStorage` and sends `Authorization: Bearer <token>`.
- **Alternative:** Server sets the token in an `httpOnly; Secure; SameSite` cookie.
- **Trade-off:** localStorage is readable by any JavaScript on the page, so an XSS bug could steal
  the token; an httpOnly cookie can't be read by JS. But cookies are sent automatically, so they
  need CSRF protection (SameSite + CSRF token), and cross-port local dev (5173 → 8000) needs
  careful CORS/cookie settings. For a local demo with no third-party scripts, bearer tokens are
  simpler to build, test and explain. For production: httpOnly cookie + CSRF protection, or a
  short-lived access token in memory plus a refresh token in an httpOnly cookie.
- **Known consequence:** `<img src>` can't send a bearer header, so the frontend must fetch images
  with the header and display blob URLs (Stage 6).

## 2026-10-02 — Token lifetime 8 hours, no refresh tokens
- **Decision:** HS256 JWT with `sub` (user id), `iat`, `exp`; `JWT_EXPIRE_MINUTES=480` default.
- **Alternatives:** 1 hour (safer, but needs refresh tokens to be usable); 24 hours.
- **Reason:** A working day with no refresh logic. HS256 (one shared secret) fits because the same
  service both signs and verifies; RS256 key pairs help only when other services verify tokens.

## 2026-10-02 — Load the user from the DB on every request
- **Decision:** `get_current_user` decodes the token, then loads the user by id; inactive or
  missing → 401. The role is NOT stored in the token — the DB role is always used.
- **Alternatives:** Trust role/active claims inside the token (no DB query).
- **Reason:** Deactivation and role changes take effect on the very next request instead of when
  the token expires. Cost is one primary-key lookup per request — negligible at this scale.

## 2026-10-02 — Failed logins: one generic 401
- **Decision:** Unknown email, wrong password and deactivated account all return
  401 `{"detail":"Invalid email or password"}`. For an unknown email we still run argon2 against a
  dummy hash so response time doesn't reveal whether the email exists. Failures are logged
  (`logging`), not written to `audit_log`; successful logins are audited as LOGIN.
- **Alternatives:** 403 "account disabled" for deactivated users (friendlier, leaks existence).
- **Reason:** Don't help attackers enumerate accounts. Limitation: no rate limiting / lockout.

## 2026-10-02 — New audit action USER_CREATE (conflicts with CLAUDE.md action list)
- **Decision:** Added `USER_CREATE` to the `audit_log.action` CHECK list. Role changes use
  `ROLE_CHANGE` (details `{"from","to"}`); activate/deactivate uses `UPDATE` with
  `entity_type='user'` (details `{"is_active":{"from","to"}}`). Applied with `docker compose down -v`.
- **Alternatives:** Don't audit user creation (keeps CLAUDE.md unchanged, leaves a gap).
- **Reason:** "Every change is traceable." CLAUDE.md's action list needs updating by the owner.

## 2026-10-02 — Audit rows are written in the same transaction as the change
- **Decision:** `write_audit(conn, ...)` takes the caller's connection.
- **Alternatives:** Separate connection/transaction for audit writes.
- **Reason:** The change and its audit row commit together or not at all — no audited change that
  didn't happen, and no change without an audit row.

## 2026-10-02 — Experiments: any logged-in user lists, admin + researcher create
- **Decision:** `GET /api/experiments` for all roles; `POST` for admin and researcher (viewer 403).
  Lives in `routes_experiments.py` (not in the CLAUDE.md layout, which has no home for it).
  Experiment creation is not audited (no fitting action in the list).
- **Alternatives:** Admin-only creation.
- **Reason:** Researchers run the experiments; viewers are read-only everywhere.

## 2026-10-02 — Admins can't change their own role or deactivate themselves
- **Decision:** `PATCH /api/users/{own id}` → 400.
- **Alternatives:** Allow it.
- **Reason:** Prevents an admin from accidentally locking every admin out. Another admin can do it.

## 2026-10-02 — New-user passwords: admin sets them, minimum 8 characters
- **Decision:** `POST /api/users` requires `password` of length ≥ 8 (422 otherwise). No
  self-service password change/reset (out of scope). Emails are checked with a simple
  `something@something.tld` regex and lowercased, instead of adding `email-validator`.
- **Alternatives:** 12-character minimum; `pydantic[email]` for full email validation.
- **Reason:** Fast to build, one fewer dependency, good enough for an internal tool.

## 2026-10-02 — Dependencies declared with `Annotated[...]`
- **Decision:** Routes take `user: security.CurrentUser` or `admin: AdminUser`, where these are
  `Annotated[dict, Depends(...)]` aliases; `require_role(...)` returns a `Depends`.
- **Alternatives:** `user: dict = Depends(...)` defaults and disable ruff rule B008.
- **Reason:** FastAPI's recommended style; keeps ruff's B008 bug check on; the role rule is visible
  in each route's signature.
