import logging
import time
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as DatabaseTimeoutError
from sqlalchemy.orm import Session

from app.auth import current_user, roles
from app.config import get_settings
from app.db import get_db
from app.models import AppUser
from app.routers import (
    datasets,
    governance,
    pipeline,
    processing,
    records,
    spatial,
    workspace,
)
from app.services.exports import export_available

logger = logging.getLogger(__name__)


@lru_cache
def redis_client():
    return Redis.from_url(
        get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2
    )


def rate_limit(request: Request):
    address = request.client.host if request.client else "unknown"
    key = f"astra:rate:{address}:{int(time.time()) // 60}"
    try:
        count = redis_client().eval(
            "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],70) end; return n",
            1,
            key,
        )
    except RedisError as exc:
        raise HTTPException(503, "Request limiter unavailable") from exc
    if count > get_settings().requests_per_minute:
        raise HTTPException(429, "Request rate exceeded", headers={"Retry-After": "60"})


class RequestSizeLimit:
    def __init__(self, app, max_bytes):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        size = 0

        async def bounded_receive():
            nonlocal size
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > self.max_bytes:
                    raise HTTPException(413, "Request exceeds upload limit")
            return message

        await self.app(scope, bounded_receive, send)


app = FastAPI(
    title="Astra VI 3D Cadastre API",
    version="0.4.0",
    description="SIH26011 spatial workspace and governance prototype. Proposed 3D ULPIN is a prototype extension, not a government standard.",
)
app.add_middleware(
    RequestSizeLimit, max_bytes=get_settings().max_upload_bytes + 1024 * 1024
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
for router in [
    spatial.router,
    datasets.router,
    processing.router,
    records.router,
    pipeline.router,
    workspace.router,
    governance.router,
]:
    app.include_router(router, prefix="/api/v1", dependencies=[Depends(rate_limit)])


@app.exception_handler(IntegrityError)
async def integrity_error(request, exc):
    logger.warning("Database constraint rejected a request")
    return JSONResponse(
        status_code=409,
        content={
            "detail": "Database constraint conflict; check hierarchy, duplicates and references"
        },
    )


@app.exception_handler(OperationalError)
@app.exception_handler(DatabaseTimeoutError)
async def database_error(request, exc):
    logger.error("Database unavailable")
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


@app.exception_handler(FileNotFoundError)
async def missing_source(request, exc):
    logger.warning("A stored source or generated asset is unavailable")
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Stored file unavailable. Its property record remains accessible."
        },
    )


class Health(BaseModel):
    status: str


class UserOut(BaseModel):
    id: str
    role: str


class Capability(BaseModel):
    capability: str
    available: bool
    reason: str


@app.get("/", tags=["health"])
def root():
    """Return a small human-readable service status instead of an opaque 404."""
    return {
        "service": "Astra VI 3D Cadastre API",
        "status": "running",
        "prototype": "Proposed 3D ULPIN",
        "docs": "/docs",
        "health": "/health/live",
        "api_base": "/api/v1",
    }


@app.get("/health/live", response_model=Health, tags=["health"])
def live():
    return {"status": "alive"}


@app.get("/health/ready", response_model=Health, tags=["health"])
def ready(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1 FROM cadastre.spatial_objects LIMIT 1"))
    try:
        redis_client().ping()
    except RedisError as exc:
        raise HTTPException(503, "Redis unavailable") from exc
    return {"status": "ready"}


@app.get(
    "/api/v1/auth/me",
    response_model=UserOut,
    tags=["auth"],
    dependencies=[Depends(rate_limit)],
)
def me(user: AppUser = Depends(current_user)):
    return {"id": str(user.id), "role": user.role}


@app.get("/api/v1/capabilities", response_model=list[Capability], tags=["capabilities"])
def capabilities():
    return [
        {"capability": name, "available": available, "reason": reason}
        for name, available, reason in [
            (
                "geojson_parcels",
                True,
                "Polygon Feature / FeatureCollection, maximum 100 features; requires database, storage and worker",
            ),
            (
                "evidence_upload",
                True,
                "PDF, PNG, JPEG retained privately; signature checks only, no OCR or malware scan",
            ),
            (
                "manual_prisms",
                True,
                "Explicit metric CRS, vertical bounds and named height reference",
            ),
            (
                "prism_validation",
                True,
                "Closed prisms, parent containment, semantic overlaps, floating units, registered penetration and explicit partition checks",
            ),
            (
                "ai_extraction",
                False,
                "Local SegFormer adapter is exposed; trained weights are not bundled; see /pipeline/capabilities",
            ),
            ("point_clouds", False, "PDAL / Open3D adapter deferred"),
            (
                "raster_dem_dsm",
                True,
                "Rasterio alignment and DSM minus DEM; explicit metres and matching vertical datum required",
            ),
            (
                "floor_plan_extraction",
                True,
                "OpenCV enclosed-region suggestions; explicit alignment and human adoption required",
            ),
            (
                "glb_3d_tiles",
                export_available(),
                "Real Blender / glTF Transform exporter requires optional tools; see /pipeline/capabilities. Cesium workspace loads the generated assets",
            ),
        ]
    ]


@app.get("/metrics", include_in_schema=False)
def metrics(user: AppUser = Depends(roles("admin"))):
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
