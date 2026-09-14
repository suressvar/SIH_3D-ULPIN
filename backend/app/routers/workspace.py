"""Bounded read models for the GIS UI; all values come from persistent records."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2.shape import to_shape
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.auth import current_user
from app.db import get_db
from app.governance_models import PropertyAnnotation
from app.models import (
    AppUser,
    AuditEvent,
    GeometryVersion,
    ProcessingJob,
    ReviewCase,
    SpatialObject,
    ULPINIdentity,
    ValidationIssue,
)
from app.pipeline_models import AssetBundle, IdentityVersion, SpatialSuggestion
from app.repositories import current_geometries, require
from app.schemas import AuditOut, Contract, IssueOut, JobOut, ObjectOut
from app.services.objects import geometry_out

router = APIRouter(prefix="/workspace", tags=["workspace"])


class Payload(Contract):
    result: dict


@router.get("/overview", response_model=Payload)
def overview(db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    counts: dict[str, int] = {
        kind: count
        for kind, count in db.execute(
            select(SpatialObject.kind, func.count()).group_by(SpatialObject.kind)
        ).all()
    }
    return {
        "result": {
            "counts": counts,
            "pending_reviews": db.scalar(
                select(func.count())
                .select_from(ReviewCase)
                .where(ReviewCase.status == "SUBMITTED")
            ),
            "validation_issues": db.scalar(
                select(func.count())
                .select_from(ValidationIssue)
                .where(ValidationIssue.status == "OPEN")
            ),
            "suggestions": db.scalar(
                select(func.count()).select_from(SpatialSuggestion)
            ),
            "jobs": [
                JobOut.model_validate(j).model_dump(mode="json")
                for j in db.scalars(
                    select(ProcessingJob)
                    .order_by(ProcessingJob.created_at.desc())
                    .limit(15)
                )
            ],
            "recent_changes": [
                AuditOut.model_validate(a).model_dump(mode="json")
                for a in db.scalars(
                    select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(15)
                )
            ],
        }
    }


@router.get("/search", response_model=Payload)
def search(
    q: str = Query("", max_length=160),
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    ids = select(ULPINIdentity.object_id).where(
        ULPINIdentity.identifier.ilike(pattern, escape="\\")
    )
    revisions = (
        select(GeometryVersion.object_id)
        .join(IdentityVersion, IdentityVersion.geometry_id == GeometryVersion.id)
        .where(IdentityVersion.canonical_code.ilike(pattern, escape="\\"))
    )
    current_annotations = (
        select(PropertyAnnotation)
        .distinct(PropertyAnnotation.object_id)
        .order_by(PropertyAnnotation.object_id, PropertyAnnotation.sequence.desc())
        .subquery()
    )
    profile_ids = select(current_annotations.c.object_id).where(
        or_(
            current_annotations.c.display_label.ilike(pattern, escape="\\"),
            current_annotations.c.address.ilike(pattern, escape="\\"),
        )
    )
    stmt = select(SpatialObject).where(
        or_(
            SpatialObject.label.ilike(pattern, escape="\\"),
            SpatialObject.existing_ulpin.ilike(pattern, escape="\\"),
            SpatialObject.id.in_(ids),
            SpatialObject.id.in_(revisions),
            SpatialObject.id.in_(profile_ids),
        )
    )
    # Coordinates search is explicit. No invented addresses or geocoding provider.
    try:
        lon, lat = [float(x.strip()) for x in q.split(",")]
        if -180 <= lon <= 180 and -90 <= lat <= 90:
            newer = aliased(GeometryVersion)
            geoids = (
                select(GeometryVersion.object_id)
                .join(SpatialObject, SpatialObject.id == GeometryVersion.object_id)
                .where(
                    SpatialObject.lifecycle == "ACTIVE",
                    ~select(newer.id)
                    .where(
                        newer.object_id == GeometryVersion.object_id,
                        newer.version > GeometryVersion.version,
                    )
                    .exists(),
                    func.ST_Intersects(
                        GeometryVersion.footprint,
                        func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326),
                    ),
                )
            )
            stmt = select(SpatialObject).where(SpatialObject.id.in_(geoids))
    except ValueError:
        pass
    rows = list(
        db.scalars(stmt.order_by(SpatialObject.kind, SpatialObject.label).limit(50))
    )
    return {
        "result": {
            "items": [
                ObjectOut.model_validate(o).model_dump(mode="json") for o in rows
            ],
            "limit": 50,
            "location_search": "longitude, latitude or a provided address; no external geocoding",
        }
    }


@router.get("/scene/{parcel_id}", response_model=Payload)
def scene(
    parcel_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    parcel = require(db, SpatialObject, parcel_id)
    if parcel.kind != "PARCEL":
        raise HTTPException(422, "Select a root parcel")
    objects = list(
        db.scalars(
            select(SpatialObject)
            .where(
                or_(SpatialObject.id == parcel_id, SpatialObject.parcel_id == parcel_id)
            )
            .order_by(SpatialObject.created_at)
            .limit(501)
        )
    )
    if len(objects) > 500:
        raise HTTPException(
            413, "Parcel exceeds interactive object limit; subdivide the workspace"
        )
    geometries = current_geometries(db, parcel_id)
    bundle = db.scalar(
        select(AssetBundle)
        .where(AssetBundle.parcel_id == parcel_id)
        .order_by(AssetBundle.created_at.desc())
    )
    asset = None
    if bundle:
        asset = {
            "id": str(bundle.id),
            "placement": bundle.placement,
            "snapshot": bundle.snapshot,
            "files": {
                n: f"/api/v1/exports/{bundle.id}/files/{n}" for n in bundle.manifest
            },
        }
    identities = list(
        db.scalars(
            select(IdentityVersion).where(
                IdentityVersion.geometry_id.in_([g.id for g in geometries])
            )
        )
    )
    return {
        "result": {
            "objects": [
                ObjectOut.model_validate(o).model_dump(mode="json") for o in objects
            ],
            "geometries": [
                {
                    **geometry_out(g).model_dump(mode="json"),
                    "area_m2": to_shape(g.metric_footprint).area,
                    "volume_m3": (
                        to_shape(g.metric_footprint).area * (g.z_max - g.z_min)
                        if g.z_min is not None
                        else None
                    ),
                }
                for g in geometries
            ],
            "identities": {str(v.geometry_id): v.canonical_code for v in identities},
            "asset": asset,
        }
    }


@router.get("/issues", response_model=Payload)
def issues(db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    rows = db.execute(
        select(
            ValidationIssue,
            GeometryVersion.object_id,
            SpatialObject.label,
            SpatialObject.parcel_id,
        )
        .join(GeometryVersion, ValidationIssue.geometry_id == GeometryVersion.id)
        .join(SpatialObject, GeometryVersion.object_id == SpatialObject.id)
        .order_by(ValidationIssue.created_at.desc())
        .limit(100)
    ).all()
    return {
        "result": {
            "items": [
                {
                    **IssueOut.model_validate(i).model_dump(mode="json"),
                    "object_id": str(o),
                    "object_label": label,
                    "parcel_id": str(p),
                }
                for i, o, label, p in rows
            ]
        }
    }
