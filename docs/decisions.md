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

## 2026-10-02 — Uploads reference experiments by code (Stage 3)
- **Decision:** `POST /api/images` and `PATCH /api/images/{id}` take `experiment_code`
  (e.g. `EXP-2026-001`); an unknown code → 400 and nothing is stored.
- **Alternatives:** `experiment_id`.
- **Reason:** Sidecars written by imaging stations naturally carry the human-readable code; the
  ingest service won't need to look up ids.

## 2026-10-02 — Decompression bombs → 413; Pillow's warning treated as an error
- **Decision:** Pillow's `DecompressionBombWarning` (> ~89 MP) and `DecompressionBombError`
  (> ~179 MP) both → 413 "Image dimensions are too large". `MAX_IMAGE_PIXELS` left at default.
- **Alternatives:** 400; or only reject at Pillow's hard error threshold.
- **Reason:** Same family as the 20 MB limit ("too large to process"). By default Pillow only
  *warns* in the lower range and decodes anyway, which still costs gigabytes of RAM.

## 2026-10-02 — 20 MB limit enforced twice
- **Decision:** (1) HTTP middleware rejects `POST /api/images` with `Content-Length` > 20 MB + 1 MB
  multipart allowance → 413 before the body is received. (2) The route reads at most 20 MB + 1 byte
  and rejects anything larger → 413.
- **Alternatives:** Only the route check.
- **Reason:** FastAPI parses the whole multipart body (spooling to disk) before the route runs, so
  the route check alone still accepts a 2 GB upload first. Clients that don't send Content-Length
  (chunked) are still caught by check (2). Limitation: a production setup would also cap body size
  in a reverse proxy (nginx `client_max_body_size`).

## 2026-10-02 — EXIF: store a whitelist of readable tags
- **Decision:** Keep Make, Model, Software, DateTimeOriginal, Orientation, ExposureTime, FNumber,
  ISOSpeedRatings, FocalLength (from IFD0 + Exif sub-IFD), converted to JSON-safe values.
- **Alternatives:** Every tag stringified.
- **Reason:** Binary blobs (MakerNote, thumbnails) are large and not valid JSON; the whitelist is
  what researchers actually filter or read. `capture_date` = form value, else the DATE part of
  `DateTimeOriginal`, else NULL (EXIF has no timezone — trap #12).

## 2026-10-02 — Random storage keys (`originals/<uuid>.<ext>`, `thumbnails/<uuid>.jpg`)
- **Decision:** Object keys use a fresh UUID per upload; extension from the Pillow-detected format.
- **Alternatives:** Content-addressed keys (`originals/<sha256>`).
- **Reason:** Upload compensation ("insert failed → delete the objects I wrote") is only safe if
  the keys are mine alone. With sha-named keys, two racing uploads of the same file write the same
  key, and the loser's cleanup would delete the winner's original. The original filename is never
  used in a key (no path tricks), only stored as metadata.

## 2026-10-02 — Duplicate response shape
- **Decision:** `409 {"detail": {"message": "Duplicate image", "image_id": <existing id>}}`.
- **Alternatives:** `{"detail": "...", "image_id": N}` at the top level.
- **Reason:** Keeps the single-`detail` error convention; ingest reads `detail.image_id`.

## 2026-10-02 — Deleting an original with derived images → 409
- **Decision:** The DB's `ON DELETE RESTRICT` raises; the API returns 409 "This image has derived
  images (crops/masks). Delete those first." Nothing is removed from storage.
- **Alternatives:** 400.
- **Reason:** 409 = conflicts with the current state of the resource, which is exactly this.

## 2026-10-02 — Stored width/height are the DISPLAY orientation
- **Decision:** For EXIF orientations 5-8 (90°/270° rotation) the stored `width`/`height` are
  swapped to match how the image is displayed. Thumbnails apply `exif_transpose`. Original bytes are
  stored untouched.
- **Alternatives:** Store the raw pixel dimensions.
- **Reason:** The frontend shows the corrected image, so crop pixels (Stage 7) and normalized
  annotation coordinates (trap #9) must be measured against the displayed orientation.

## 2026-10-02 — Tags are normalized (lowercased, trimmed, de-duplicated)
- **Decision:** `"Drought, leaf ,drought,"` → `["drought", "leaf"]`, on upload and on PATCH.
- **Alternatives:** Store tags exactly as typed.
- **Reason:** Makes tag search in Stage 4 simple and predictable (`drought` = `Drought`) without
  case-insensitive array queries. Species and station are only trimmed, not lowercased.

## 2026-10-02 — Thumbnail details
- **Decision:** 320 px wide JPEG (quality 85), height keeps aspect ratio; images narrower than 320 px
  are not upscaled. Transparent PNGs are flattened on white. 16/32-bit TIFFs are contrast-stretched
  from their real min..max to 8-bit.
- **Reason:** Upscaling adds no information. Without stretching, a 16-bit scientific TIFF converts
  to an almost all-white thumbnail because every value above 255 clips.

## 2026-10-02 — Audit log endpoint shape
- **Decision:** `GET /api/audit` (admin): newest first, `page` (≥1) and `page_size` (1-100,
  default 24), returns `{items, total, page, page_size}`; each item includes `user_email`.
  Lives in `routes_audit.py` (not in the CLAUDE.md layout).
- **Reason:** Uses the pagination limits already decided in CLAUDE.md; the same response shape is
  proposed for `GET /images` in Stage 4.

## 2026-10-02 — Search filter behaviour (Stage 4)
- **Decision:** `GET /api/images` (every logged-in role), filters combined with AND:
  - `species`: case-insensitive EXACT match (`wheat` finds `Wheat`, `whe` finds nothing).
  - `experiment`: by code; an unknown code returns an empty page (200), not an error.
  - `station`: exact, case-sensitive (station ids are codes like `ST01`).
  - `tags=a,b`: image must have ALL listed tags (`tags @> ARRAY[...]`); input normalized like
    on upload (trimmed, lowercased).
  - `date_from` / `date_to`: both inclusive; `date_from > date_to` → 422; images with no
    `capture_date` are excluded whenever a date filter is used.
  - Derived images (crops/masks) are included; the frontend can label them via `derivation`.
- **Alternatives:** tags match ANY (`&&`); case-sensitive species; unknown experiment → 400;
  reversed range → empty; originals-only by default.
- **Reason:** ALL-tags narrows results like most search UIs. A filter that matches nothing is not
  an error. Everything stays parameterized: `search_where()` only joins fixed SQL fragments; every
  user value is a `%s` parameter (a test sends `wheat' OR '1'='1` and gets 0 results).

## 2026-10-02 — Search sort order and pagination
- **Decision:** `ORDER BY capture_date DESC NULLS LAST, id DESC`; `page` ≥ 1, `page_size` 1-100
  (default 24); response `{items, total, page, page_size}`; a page past the end returns empty items.
  `total` comes from a separate `count(*)` with the same WHERE.
- **Alternatives:** newest upload first (`created_at`); keyset/cursor pagination.
- **Reason:** Researchers think in capture dates. `id` breaks ties so the order is total and no
  image appears on two pages. OFFSET pagination is simple and fine at this size (it gets slower
  only with very deep pages on large tables — keyset would fix that).

## 2026-10-02 — Species index changed to `lower(crop_species)`
- **Decision:** Replaced `idx_images_crop_species` with an expression index
  `idx_images_crop_species_lower ON images (lower(crop_species))`. `schema.sql` drops the old index
  if present, so existing databases migrate on restart without `down -v`.
- **Reason:** The query filters on `lower(crop_species) = lower(%s)`. A plain index on
  `crop_species` can't serve a condition on `lower(crop_species)`; the index must be on the same
  expression. (Updates the "Search indexes" entry above: the species search now uses this index.)
- **Verified:** `test_filter_query_uses_its_index` runs `EXPLAIN` on the real search SQL for each
  filter with `enable_seqscan = off` and asserts the intended index appears in the plan. With only
  a handful of rows Postgres normally prefers a sequential scan, which is correct at that size.

## 2026-10-02 — Ingest service account is seeded by the API (Stage 5)
- **Decision:** On startup the API creates `INGEST_EMAIL` / `INGEST_PASSWORD` as a **researcher** if
  that email doesn't exist (`seed_user()`, same never-overwrite rule as the admin; `seed_admin` was
  generalized into `seed_user(email, password, role)`). Both variables are optional for the API.
- **Alternatives:** An admin creates the account by hand through the API.
- **Reason:** `docker compose up` works with no manual step. A researcher (not admin) account follows
  least privilege: it can upload and edit only its own images.

## 2026-10-02 — Sidecar naming: `leaf01.jpg` → `leaf01.json`
- **Decision:** The sidecar is the image path with its extension replaced by `.json`.
- **Alternatives:** `leaf01.jpg.json`; accept both.
- **Reason:** CLAUDE.md's `<image>.json` is ambiguous; one rule is simpler to test and document.
  Only known fields are read (`experiment_code`, `crop_species`, `station_id`, `capture_date`,
  `tags` as list or comma string); other keys are ignored. Validation of values (date format,
  experiment existence) is left to the API so there is one source of truth.

## 2026-10-02 — Missing sidecar: 5 s grace, then filename fallback
- **Decision:** When an image is stable (trap #1) but has no sidecar, wait a further 5 s for one;
  then use the filename pattern. A sidecar that exists must itself be stable (2 s) before use.
  Image and sidecar stability are checked on every poll, so their timers run in parallel.
- **Alternatives:** Fall back to the filename immediately.
- **Reason:** A station that writes the image before the sidecar would otherwise lose its metadata.
  Cost: files without sidecars are ingested ~7 s after the last write instead of ~2 s.

## 2026-10-02 — Retries exhausted → `failed/` with a reason file
- **Decision:** Network errors and 5xx: 5 attempts with 1, 2, 4, 8 s waits; then the file moves to
  `failed/` with reason "API unavailable after 5 attempts (...)". 401 → log in again once (tokens
  expire after 8 h); other 4xx → `failed/` immediately; 409 → `processed/` (duplicate = success).
  Every failed file gets `<name>.reason.txt`; to retry, copy it back into the drop folder.
- **Alternatives:** Leave the file in place and retry forever.
- **Reason:** Matches CLAUDE.md (files end in processed/ or failed/), never loops forever on a file the
  API keeps rejecting, and never deletes data.

## 2026-10-02 — Folder watching with watchdog's `PollingObserver`
- **Decision:** `PollingObserver(timeout=1s)` on the drop folder (non-recursive), plus a scan of
  existing files at startup. Events only add paths to a pending set; a 1 s main loop decides.
- **Alternatives:** Native observer (inotify on Linux).
- **Reason:** On Docker Desktop for Mac, file events from the host often don't reach containers
  through bind mounts, so a native observer can silently miss files. Polling one small folder every
  second is cheap and reliable.

## 2026-10-02 — Other ingest file rules
- **Decision:** Hidden files (`.DS_Store`) and temp suffixes (`.part`, `.tmp`, `.crdownload`, `.swp`)
  are ignored; any other non-image file → `failed/` "unsupported file type". On a name clash in
  `processed/` or `failed/`, the image and sidecar both get the same `-1`, `-2` suffix — nothing is
  overwritten. Wrong ingest credentials at startup stop the service (config error); an unreachable
  API is retried every 5 s. The API container got a healthcheck (`/api/health`) and the ingest
  service waits for it.
- **Reason:** Stations often write temp names and rename when done; those must not be ingested early.

## 2026-10-02 — Synthetic sample data for now
- **Decision:** `sample_data/make_samples.py` draws 20 synthetic files (+ sidecars) covering every
  ingestion path; they are committed (~0.5 MB) so the CLAUDE.md `cp` demo works.
- **Alternatives:** Wait for real CC0 photos.
- **Reason:** Unblocks Stage 5 now. Real photos (with sources/licences) replace them before README
  screenshots.
