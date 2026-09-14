from uuid import UUID

from fastapi import HTTPException
from geoalchemy2.elements import WKTElement
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import mapping
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import GeometryVersion, Kind, SourceDataset, SpatialObject
from app.repositories import audit, latest_geometry, require
from app.schemas import GeometryCreate, GeometryOut, ObjectCreate
from app.services.workflow import transition
from app.spatial import geometry_digest, prism_shell_wkt, project_footprint

PARENTS = {
    Kind.BUILDING: {Kind.PARCEL},
    Kind.FLOOR: {Kind.BUILDING},
    Kind.UNIT: {Kind.FLOOR},
    Kind.UNDERGROUND: {Kind.PARCEL, Kind.BUILDING},
    Kind.SHARED: {Kind.PARCEL, Kind.BUILDING, Kind.FLOOR},
    Kind.EASEMENT: {Kind.PARCEL},
    Kind.INFRASTRUCTURE: {Kind.PARCEL, Kind.EASEMENT},
}


def create_object(
    db: Session, payload: ObjectCreate, actor: UUID, object_id: UUID | None = None
):
    db.execute(text("SELECT pg_advisory_xact_lock(26011002)"))
    parent = (
        require(db, SpatialObject, payload.parent_id) if payload.parent_id else None
    )
    if parent and parent.kind not in PARENTS[payload.kind]:
        raise HTTPException(422, "Parent type does not match the spatial hierarchy")
    if parent and parent.is_synthetic != payload.is_synthetic:
        raise HTTPException(
            422, "Children must retain the parent synthetic-data designation"
        )
    data = payload.model_dump()
    data["parcel_id"] = (
        (parent.id if parent.kind == Kind.PARCEL else parent.parcel_id)
        if parent
        else None
    )
    if object_id:
        data["id"] = object_id
    obj = SpatialObject(**data, created_by=actor)
    db.add(obj)
    audit(db, actor, "OBJECT_CREATED", obj, {"is_synthetic": obj.is_synthetic})
    return obj


def create_geometry(db: Session, object_id: UUID, payload: GeometryCreate, actor: UUID):
    db.execute(text("SELECT pg_advisory_xact_lock(26011002)"))
    obj = require(db, SpatialObject, object_id)
    if obj.lifecycle != "ACTIVE":
        raise HTTPException(409, "Superseded objects cannot receive new geometry")
    # Serialize all geometry edits within a parcel, including validation snapshots.
    require(db, SpatialObject, obj.parcel_id or obj.id, lock=True)
    if obj.kind == Kind.PARCEL and payload.z_min is not None:
        raise HTTPException(
            422, "Surface parcels use 2D footprints; create a child for a volume"
        )
    if payload.source_dataset_id:
        dataset = require(db, SourceDataset, payload.source_dataset_id)
        if dataset.status not in {"READY", "EVIDENCE_ONLY"}:
            raise HTTPException(422, "Source dataset is not usable")
        if dataset.is_synthetic != obj.is_synthetic:
            raise HTTPException(422, "Synthetic and real sources cannot be mixed")
    elif payload.source_category != "MANUAL":
        raise HTTPException(422, "This source category requires a source dataset")
    try:
        geographic, metric, transformation = project_footprint(
            payload.footprint, payload.source_crs, payload.metric_srid
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    latest = latest_geometry(db, object_id)
    geom = GeometryVersion(
        object_id=object_id,
        version=latest.version + 1 if latest else 1,
        footprint=from_shape(geographic, srid=4326),
        metric_footprint=from_shape(metric, srid=payload.metric_srid),
        shell=(
            WKTElement(
                prism_shell_wkt(metric, payload.z_min, payload.z_max),
                srid=payload.metric_srid,
            )
            if payload.z_min is not None and payload.z_max is not None
            else None
        ),
        metric_srid=payload.metric_srid,
        source_crs=payload.source_crs,
        transformation=transformation,
        z_min=payload.z_min,
        z_max=payload.z_max,
        elevation_reference=payload.elevation_reference,
        height_estimated=payload.height_estimated,
        source_category=payload.source_category,
        source_dataset_id=payload.source_dataset_id,
        confidence=payload.confidence,
        method=payload.method,
        geometry_hash=geometry_digest(geographic, payload),
        validity=(
            "PRISM_CONSTRUCTED" if payload.z_min is not None else "FOOTPRINT_VALID"
        ),
        created_by=actor,
    )
    db.add(geom)
    audit(
        db,
        actor,
        "GEOMETRY_VERSION_CREATED",
        geom,
        {
            "object_id": str(object_id),
            "version": geom.version,
            "height_estimated": geom.height_estimated,
        },
    )
    transition(db, geom, "DRAFT", actor, payload.method)
    return geom


def geometry_out(geom: GeometryVersion) -> GeometryOut:
    data = {
        name: getattr(geom, name)
        for name in GeometryOut.model_fields
        if name != "footprint"
    }
    data["footprint"] = mapping(to_shape(geom.footprint))
    return GeometryOut(**data)


def list_objects(
    db: Session, kind: Kind, parent_id: UUID | None, limit: int, offset: int
):
    stmt = select(SpatialObject).where(SpatialObject.kind == kind)
    if parent_id:
        stmt = stmt.where(SpatialObject.parent_id == parent_id)
    return list(
        db.scalars(
            stmt.order_by(SpatialObject.created_at, SpatialObject.id)
            .limit(limit)
            .offset(offset)
        )
    )
