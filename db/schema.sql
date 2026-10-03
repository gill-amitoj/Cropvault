-- CropVault schema. Safe to run more than once (IF NOT EXISTS everywhere).
-- Changing an existing table needs a fresh volume: docker compose down -v

CREATE TABLE IF NOT EXISTS users (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE CHECK (email = lower(email)),
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'researcher', 'viewer')),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS experiments (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    description TEXT,
    created_by  BIGINT REFERENCES users (id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS images (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    experiment_id     BIGINT REFERENCES experiments (id),  -- optional
    crop_species      TEXT,
    capture_date      DATE,  -- DATE, not timestamp: EXIF dates have no timezone
    station_id        TEXT,
    original_filename TEXT NOT NULL,
    storage_key       TEXT NOT NULL UNIQUE,
    thumbnail_key     TEXT,
    content_type      TEXT NOT NULL,
    size_bytes        BIGINT NOT NULL CHECK (size_bytes > 0),
    width             INTEGER NOT NULL CHECK (width > 0),
    height            INTEGER NOT NULL CHECK (height > 0),
    sha256            CHAR(64) NOT NULL UNIQUE,  -- duplicate uploads are rejected here
    exif              JSONB,
    tags              TEXT[] NOT NULL DEFAULT '{}',
    uploaded_by       BIGINT NOT NULL REFERENCES users (id),
    -- RESTRICT: an original can't be deleted while crops/masks still point at it
    parent_image_id   BIGINT REFERENCES images (id) ON DELETE RESTRICT,
    derivation        TEXT CHECK (derivation IN ('crop', 'mask')),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- An original has no parent and no derivation; a derived image has both.
    CHECK ((parent_image_id IS NULL) = (derivation IS NULL))
);

CREATE TABLE IF NOT EXISTS annotations (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    image_id   BIGINT NOT NULL REFERENCES images (id) ON DELETE CASCADE,
    label      TEXT NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('bbox', 'polygon')),
    geometry   JSONB NOT NULL,  -- coordinates normalized 0-1 (validated in the API)
    created_by BIGINT NOT NULL REFERENCES users (id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     BIGINT REFERENCES users (id),
    action      TEXT NOT NULL CHECK (action IN (
                    'LOGIN', 'UPLOAD', 'UPDATE', 'DELETE',
                    'ANNOTATE', 'CROP', 'SEGMENT', 'ROLE_CHANGE', 'USER_CREATE')),
    entity_type TEXT NOT NULL,
    entity_id   BIGINT,
    details     JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Search indexes (see docs/decisions.md for which search each one speeds up)
CREATE INDEX IF NOT EXISTS idx_images_crop_species ON images (crop_species);
CREATE INDEX IF NOT EXISTS idx_images_experiment_id ON images (experiment_id);
CREATE INDEX IF NOT EXISTS idx_images_capture_date ON images (capture_date);
CREATE INDEX IF NOT EXISTS idx_images_station_id ON images (station_id);
CREATE INDEX IF NOT EXISTS idx_images_tags ON images USING GIN (tags);
