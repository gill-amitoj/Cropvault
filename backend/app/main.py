"""FastAPI app: routers and startup."""

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from app import (
    config,
    db,
    images,
    routes_audit,
    routes_auth,
    routes_experiments,
    routes_images,
    routes_users,
    storage,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Without the schema the API is useless, so a DB failure here stops startup.
    db.apply_schema()
    db.seed_user(config.ADMIN_EMAIL, config.ADMIN_PASSWORD, "admin")
    if config.INGEST_EMAIL and config.INGEST_PASSWORD:
        db.seed_user(config.INGEST_EMAIL, config.INGEST_PASSWORD, "researcher")
    # Don't crash the API if MinIO is down at startup; /health will report it.
    try:
        storage.ensure_bucket()
    except Exception:
        logger.exception("Could not ensure storage bucket at startup")
    yield


app = FastAPI(title="CropVault API", lifespan=lifespan)
api = APIRouter(prefix="/api")

# Allowance for multipart boundaries and form fields on top of the file itself.
MULTIPART_OVERHEAD_BYTES = 1024 * 1024


@app.middleware("http")
async def reject_oversized_uploads(request: Request, call_next):
    """Reject a too-big upload from its Content-Length header BEFORE the body is received.
    (Routes only run after FastAPI has read the whole body.) The upload route re-checks the
    real file size, which also covers clients that don't send Content-Length."""
    if request.method == "POST" and request.url.path == "/api/images":
        length = request.headers.get("content-length")
        limit = images.MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES
        if length and length.isdigit() and int(length) > limit:
            return JSONResponse({"detail": "File is larger than 20 MB"}, status_code=413)
    return await call_next(request)


@api.get("/health")
def health():
    """Check DB and MinIO. 200 if both are ok, 503 if either fails."""
    checks = {}
    for name, check in (("db", db.check_db), ("minio", storage.check_storage)):
        try:
            check()
            checks[name] = "ok"
        except Exception as exc:
            logger.warning("Health check %s failed: %s", name, exc)
            checks[name] = "error"

    healthy = all(status == "ok" for status in checks.values())
    body = {"status": "ok" if healthy else "error", **checks}
    return JSONResponse(body, status_code=200 if healthy else 503)


api.include_router(routes_auth.router)
api.include_router(routes_users.router)
api.include_router(routes_experiments.router)
api.include_router(routes_images.router)
api.include_router(routes_audit.router)
app.include_router(api)
