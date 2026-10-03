"""FastAPI app: routers and startup."""

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse

from app import db, storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Don't crash the API if MinIO is down at startup; /health will report it.
    try:
        storage.ensure_bucket()
    except Exception:
        logger.exception("Could not ensure storage bucket at startup")
    yield


app = FastAPI(title="CropVault API", lifespan=lifespan)
api = APIRouter(prefix="/api")


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


app.include_router(api)
