# CropVault — Project Instructions for Claude Code

## What this project is
CropVault is a small open-source image management system for plant-science research.
Imaging stations drop crop images into a folder; a pipeline uploads them to central
storage; researchers search, view, annotate, and crop them through a web app with
role-based access control (RBAC). Every change is traceable through an audit log.

It is modelled on a real NRC Canada co-op role (crop image management system), so it
should look like something a research software team would actually use: simple,
tested, documented, and runnable with one command.

Core question: How do you reliably move research images from instruments into a
searchable, access-controlled system without losing, duplicating, or corrupting data?

## How to work with me (read this first)
I am learning. I must be able to explain every part of this project in an interview.
- Work on ONE stage at a time (see Roadmap). Do not build ahead.
- Before writing code for a stage, give me a short plan (5-10 lines) and wait for "go".
- Whenever you make a judgment call that is NOT already decided in "Decisions already
  made" below (a limit, a library choice, a permission rule, an error behaviour),
  STOP and show me 2-3 options with trade-offs. I decide. Record it in
  `docs/decisions.md` (date, decision, alternatives, reason).
- After finishing a stage, explain what you built in plain language, list the files you
  changed, tell me how to run and check it myself, and give me 2 interview questions
  about that stage with short answers.
- Run the tests and linter yourself before saying a stage is done. Never claim
  something works without running it.
- Keep code simple and readable. No clever abstractions. Prefer plain functions.
- Small changes only. Don't rewrite working files to change one thing.
- When something breaks, explain the root cause in 1-2 sentences before fixing it.
  Log real problems in `docs/problems_log.md` (date, problem, cause, fix).
- Never add a dependency without telling me what it's for.
- Never invent test results, performance numbers, or screenshots. If something is
  unknown, say so.

## Hard constraints
- 100% free and open source. No paid APIs, no paid cloud, no third-party API keys.
- Everything runs locally with `docker compose up --build`.
- No secrets in git. Everything sensitive comes from `.env` (commit only `.env.example`).
- Deadline: Stages 0-6 working and pushed by Sunday Oct 4, 2026, 6:00 PM MT.
  If we fall behind, cut Stage 8 first, then Stage 7. Never cut tests or the README.

## Tech stack
- Python 3.11+, FastAPI, Uvicorn
- PostgreSQL 16 with `psycopg[binary]` (plain SQL, no ORM), schema in `db/schema.sql`
- MinIO (free, S3-compatible object storage) via the `minio` Python client
- Auth: PyJWT for tokens, argon2 (`argon2-cffi`) for password hashing
- Pillow for image checks, thumbnails, EXIF, and crops; OpenCV only in Stage 8
- `watchdog` + `httpx` for the ingestion service
- React + Vite + TypeScript, React Router, plain CSS (no UI framework)
- `pytest`, `ruff` (lint + format), GitHub Actions CI
- Python `logging` module, never bare `print()` for status

## Known traps (the core of this project)
1. **Half-written files.** A station may still be writing an image when the watcher
   sees it. Only process a file after its size is unchanged for 2 seconds.
2. **The same image arrives twice.** Stations resend and the watcher restarts. Compute
   SHA-256 of every upload; if it already exists, return 409 with the existing id.
   The ingestion service treats 409 as success, so reprocessing is always safe.
3. **Never trust the file extension or Content-Type.** Open the file with Pillow to
   confirm it is a real JPEG/PNG/TIFF. Reject anything else with 400.
4. **Huge images.** Max 20 MB per upload (413 if larger). Keep Pillow's
   decompression-bomb protection on.
5. **EXIF orientation.** Phone and camera images can display rotated. Apply
   `ImageOps.exif_transpose` when making thumbnails and crops. Never modify the
   original file.
6. **Originals are immutable.** Crops and masks create NEW derived images linked to
   their parent (`parent_image_id`, `derivation`). This is what makes the data
   traceable.
7. **Storage and database can get out of sync.** Upload order: put object in MinIO,
   then insert the DB row; if the insert fails, delete the object. Delete order: delete
   the DB row, then the object; if the object delete fails, log it as an orphan.
8. **RBAC in the frontend is not security.** Hiding a button does nothing. Every rule
   is enforced in the backend, and every forbidden case has a test that expects 403.
9. **Annotation coordinates.** The browser shows images scaled down. Store coordinates
   normalized 0-1 against the image's real width/height, so annotations still line up
   at any display size.
10. **Docker hostnames.** Inside Compose the API reaches MinIO at `minio:9000`, but the
    browser can't. So images are streamed through the API after the permission check,
    never served from public MinIO URLs.
11. **Fragile filenames.** Prefer metadata from a sidecar `<image>.json`. Fall back to
    the filename pattern `STATION_SPECIES_YYYYMMDD_*.jpg` only if there is no sidecar.
    If neither works, move the file to `failed/` with a logged reason.
12. **EXIF dates have no timezone.** Store `capture_date` as a DATE, not a timestamp.

## Decisions already made (don't ask, but explain them when relevant)
- Plain SQL with psycopg, no ORM (same approach as my LedgerLens project).
- Sync FastAPI endpoints (simpler to reason about than async for this scale).
- JWT kept in memory + `localStorage` for this local demo. Record the trade-off against
  httpOnly cookies in `docs/decisions.md` in Stage 2.
- Thumbnails: 320 px wide JPEG.
- Pagination: default 24 per page, max 100.
- Researchers can edit or delete only their OWN images and annotations; admins can
  edit or delete anything.
- First admin is created from `.env` (`ADMIN_EMAIL`, `ADMIN_PASSWORD`) on startup.

## Initial scope (do NOT expand without my approval)
Roles (3): admin, researcher, viewer
Image formats: JPEG, PNG, TIFF
Annotation types: bounding box, polygon
Image operations: thumbnail, crop (segmentation only in Stage 8)
Sample data: 15-20 free plant images I add to `sample_data/station_drop/` with sidecars

## RBAC rules
| Action                                   | admin | researcher | viewer |
|------------------------------------------|-------|------------|--------|
| Log in, view, search images              | yes   | yes        | yes    |
| Upload images, edit metadata             | yes   | own only   | no     |
| Create / edit / delete annotations       | yes   | own only   | no     |
| Crop or segment (creates derived image)  | yes   | yes        | no     |
| Delete images                            | yes   | own only   | no     |
| Manage users and roles, view audit log   | yes   | no         | no     |

## Repository layout (create files only when a stage needs them)
```
cropvault/
  CLAUDE.md  README.md  .env.example  .gitignore  docker-compose.yml
  .github/workflows/ci.yml
  db/schema.sql  db/seed.sql
  docs/decisions.md  docs/problems_log.md
  backend/
    Dockerfile  requirements.txt
    app/
      main.py          # FastAPI app, routers, startup
      config.py        # read settings from env in ONE place
      db.py            # connection + small query helpers
      security.py      # hashing, JWT, require_role()
      storage.py       # put/get/delete object in MinIO (plain functions)
      images.py        # validation, checksum, thumbnail, EXIF, crop
      audit.py         # write_audit()
      routes_auth.py  routes_users.py  routes_images.py  routes_annotations.py
    tests/  (fake storage via monkeypatch; never call real MinIO in unit tests)
  ingest/
    Dockerfile  watcher.py
    tests/
  frontend/
    Dockerfile  src/ (api.ts, pages/, components/)
  sample_data/station_drop/
  data/station_drop/  (gitignored, mounted into the ingest container)
```

## Database tables (db/schema.sql)
- users(id, email UNIQUE, password_hash, role, is_active, created_at)
- experiments(id, code UNIQUE, title, description, created_by, created_at)
- images(id, experiment_id, crop_species, capture_date, station_id, original_filename,
  storage_key, thumbnail_key, content_type, size_bytes, width, height,
  sha256 UNIQUE, exif JSONB, tags TEXT[], uploaded_by, parent_image_id, derivation,
  created_at)
  derivation ∈ {NULL, crop, mask}
- annotations(id, image_id ON DELETE CASCADE, label, kind, geometry JSONB,
  created_by, created_at, updated_at)
  kind ∈ {bbox, polygon}; geometry coordinates normalized 0-1
- audit_log(id, user_id, action, entity_type, entity_id, details JSONB, created_at)
  action ∈ {LOGIN, UPLOAD, UPDATE, DELETE, ANNOTATE, CROP, SEGMENT, ROLE_CHANGE}

Indexes: crop_species, experiment_id, capture_date, station_id, GIN on tags.
Explain each index in `docs/decisions.md` (which search it speeds up).

## API (prefix /api)
- POST /auth/login, GET /auth/me
- GET/POST /users, PATCH /users/{id}  (admin)
- GET/POST /experiments
- POST /images (multipart), GET /images (filters: species, experiment, station, tags,
  date_from, date_to, page, page_size), GET/PATCH/DELETE /images/{id}
- GET /images/{id}/file, GET /images/{id}/thumbnail  (streamed after auth check)
- GET/POST /images/{id}/annotations, PATCH/DELETE /annotations/{id}
- POST /images/{id}/crop  (body: x, y, width, height in pixels)
- POST /images/{id}/segment  (Stage 8 only)
- GET /audit  (admin), GET /health (checks DB + MinIO)

Errors are JSON `{"detail": ...}` with correct codes: 400, 401, 403, 404, 409, 413, 422.

## Ingestion service rules (ingest/watcher.py)
- Watches `/data/station_drop`; on startup also processes files already there.
- Logs in as a researcher service account from env, uploads through the API only.
  It never writes to the database directly.
- Retries with exponential backoff (max 5 attempts) on network errors and 5xx.
  Does NOT retry 4xx (except treating 409 as success).
- Moves files to `processed/` or `failed/` and logs one line per file.

## Roadmap (one stage at a time)
0. Setup (repo, .gitignore, .env.example, Docker Compose with Postgres + MinIO + API,
   GET /health green, ruff + pytest + CI workflow passing)
1. Database schema + seed admin
2. Auth + RBAC (login, JWT, /auth/me, user management, 403 tests for every role rule)
3. Image upload + storage (validation, checksum dedupe, thumbnails, EXIF, streaming,
   delete, audit log)
4. Search (filters, pagination, indexes, a test for each filter)
5. Ingestion service end to end with sample_data
6. React frontend: login, gallery + filters, image detail, upload, admin page
7. Annotation canvas (bbox + polygon) + crop to derived image
8. Optional: OpenCV segmentation (Otsu threshold) saved as a derived mask image
9. README: what it does, Mermaid architecture diagram, 3-command setup, RBAC table,
   real screenshots, known limitations
Later (only if 0-9 are done): MinIO lifecycle rules, export to CSV, dashboard.

## Commands
```
cp .env.example .env
docker compose up --build
docker compose exec api pytest -q
docker compose exec api ruff check . && docker compose exec api ruff format --check .
cp sample_data/station_drop/* data/station_drop/     # trigger the ingestion demo
```
Frontend http://localhost:5173 · API docs http://localhost:8000/docs · MinIO console http://localhost:9001

Current stage: 0
