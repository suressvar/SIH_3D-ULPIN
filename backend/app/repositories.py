from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, defer

from app.models import AuditEvent, GeometryVersion, SpatialObject


def require(db: Session, model, record_id: UUID, lock: bool = False):
    statement = select(model).where(model.id == record_id)
    if lock:
        statement = statement.with_for_update()
    record = db.scalar(statement)
    if record is None:
        raise HTTPException(404, f"{model.__name__} not found")
    return record


def latest_geometry(db: Session, object_id: UUID):
    return db.scalar(
        select(GeometryVersion)
        .where(GeometryVersion.object_id == object_id)
        .order_by(GeometryVersion.version.desc())
        .limit(1)
    )


def current_geometries(db: Session, parcel_id: UUID):
    latest_ids = (
        select(GeometryVersion.id)
        .join(SpatialObject, SpatialObject.id == GeometryVersion.object_id)
        .where(
            SpatialObject.lifecycle == "ACTIVE",
            (SpatialObject.parcel_id == parcel_id) | (SpatialObject.id == parcel_id),
        )
        .distinct(GeometryVersion.object_id)
        .order_by(GeometryVersion.object_id, GeometryVersion.version.desc())
    )
    return list(
        db.scalars(
            select(GeometryVersion)
            .options(defer(GeometryVersion.shell))
            .join(SpatialObject, GeometryVersion.object_id == SpatialObject.id)
            .where(
                GeometryVersion.id.in_(latest_ids),
                SpatialObject.lifecycle == "ACTIVE",
                (SpatialObject.parcel_id == parcel_id)
                | (SpatialObject.id == parcel_id),
            )
            .order_by(GeometryVersion.object_id)
        )
    )


def audit(db: Session, actor: UUID, action: str, entity, detail: dict | None = None):
    db.flush()
    db.add(
        AuditEvent(
            actor_id=actor,
            action=action,
            entity_type=entity.__tablename__,
            entity_id=entity.id,
            detail=detail or {},
        )
    )
