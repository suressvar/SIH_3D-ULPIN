from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, roles
from app.db import get_db
from app.models import AppUser, GeometryVersion, Kind, SpatialObject
from app.repositories import latest_geometry, require
from app.schemas import GeometryCreate, GeometryOut, ObjectCreate, ObjectOut
from app.services.objects import (
    create_geometry,
    create_object,
    geometry_out,
    list_objects,
)

router = APIRouter()
writer = roles("surveyor", "admin")


def kind_router(path: str, kind: Kind):
    group = APIRouter(prefix=path, tags=[path.strip("/")])

    @group.get("", response_model=list[ObjectOut])
    def listing(
        parent_id: UUID | None = None,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db),
        user: AppUser = Depends(current_user),
    ):
        return list_objects(db, kind, parent_id, limit, offset)

    @group.post("", response_model=ObjectOut, status_code=201)
    def create(
        payload: ObjectCreate,
        db: Session = Depends(get_db),
        user: AppUser = Depends(writer),
    ):
        if payload.kind != kind:
            raise HTTPException(422, f"This endpoint creates {kind} objects")
        return create_object(db, payload, user.id)

    @group.get("/{object_id}", response_model=ObjectOut)
    def detail(
        object_id: UUID,
        db: Session = Depends(get_db),
        user: AppUser = Depends(current_user),
    ):
        obj = require(db, SpatialObject, object_id)
        if obj.kind != kind:
            raise HTTPException(404, "Object not found in this resource")
        return obj

    return group


for path, kind in [
    ("/parcels", Kind.PARCEL),
    ("/buildings", Kind.BUILDING),
    ("/floors", Kind.FLOOR),
    ("/units", Kind.UNIT),
    ("/underground", Kind.UNDERGROUND),
    ("/shared-spaces", Kind.SHARED),
    ("/easements", Kind.EASEMENT),
    ("/infrastructure", Kind.INFRASTRUCTURE),
]:
    router.include_router(kind_router(path, kind))


@router.post(
    "/spatial/{object_id}/geometry",
    tags=["geometry"],
    response_model=GeometryOut,
    status_code=201,
)
def add_geometry(
    object_id: UUID,
    payload: GeometryCreate,
    db: Session = Depends(get_db),
    user: AppUser = Depends(writer),
):
    return geometry_out(create_geometry(db, object_id, payload, user.id))


@router.get(
    "/spatial/{object_id}/geometry", tags=["geometry"], response_model=list[GeometryOut]
)
def geometry_history(
    object_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    require(db, SpatialObject, object_id)
    rows = db.scalars(
        select(GeometryVersion)
        .where(GeometryVersion.object_id == object_id)
        .order_by(GeometryVersion.version.desc())
        .limit(limit)
        .offset(offset)
    )
    return [geometry_out(g) for g in rows]


@router.get("/3d/{object_id}", tags=["3d"], response_model=GeometryOut)
def volume_contract(
    object_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    require(db, SpatialObject, object_id)
    geom = latest_geometry(db, object_id)
    if not geom:
        raise HTTPException(404, "No mapped geometry")
    return geometry_out(geom)
