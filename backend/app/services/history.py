import hashlib
import json
from uuid import UUID

from fastapi import HTTPException
from geoalchemy2.shape import to_shape
from shapely.ops import unary_union
from sqlalchemy import select, text

from app.models import (
    Evidence,
    Kind,
    ReviewCase,
    ReviewDecision,
    SpatialObject,
    SpatialRelationship,
)
from app.pipeline_models import ChangeMember, GeometryChange, IdentityVersion
from app.pipeline_schemas import ChangeInput
from app.repositories import audit, latest_geometry, require
from app.schemas import ObjectCreate
from app.services.objects import create_geometry, create_object
from app.spatial import project_footprint


def canonical_identity_code(parent_reference: str, object_id: UUID, geometry_hash: str):
    inputs = {
        "scheme": "ASTRA-P3D-CANONICAL-2",
        "parent_reference": parent_reference,
        "object_id": str(object_id),
        "geometry_hash": geometry_hash,
    }
    digest = hashlib.sha256(
        json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return "ASTRA-P3D-2-" + digest, inputs


def append_identity_version(db, identity, geometry, actor):
    existing = db.scalar(
        select(IdentityVersion).where(IdentityVersion.geometry_id == geometry.id)
    )
    if existing:
        return existing
    obj = require(db, SpatialObject, geometry.object_id)
    parcel = require(db, SpatialObject, obj.parcel_id)
    reference = parcel.existing_ulpin or f"PARCEL-UUID:{parcel.id}"
    code, inputs = canonical_identity_code(reference, obj.id, geometry.geometry_hash)
    version = IdentityVersion(
        identity_id=identity.id,
        geometry_id=geometry.id,
        canonical_code=code,
        geometry_hash=geometry.geometry_hash,
        identity_inputs=inputs,
        actor_id=actor,
    )
    db.add(version)
    audit(
        db,
        actor,
        "IDENTITY_GEOMETRY_VERSION_LINKED",
        version,
        {"label": "Proposed 3D ULPIN"},
    )
    return version


def change_property(db, request: ChangeInput, actor):
    db.execute(text("SELECT pg_advisory_xact_lock(26011002)"))
    objects = [require(db, SpatialObject, i) for i in request.object_ids]
    if any(o.kind != "UNIT" or o.lifecycle != "ACTIVE" for o in objects):
        raise HTTPException(422, "This phase supports changes to active property units")
    if len({o.parent_id for o in objects}) != 1:
        raise HTTPException(422, "Split/merge inputs must belong to the same floor")
    evidence = require(db, Evidence, request.evidence_id)
    if evidence.object_id not in request.object_ids:
        raise HTTPException(422, "Change evidence must be attached to an input unit")
    if request.review_decision_id:
        decision = require(db, ReviewDecision, request.review_decision_id)
        review = require(db, ReviewCase, decision.review_id)
        if review.object_id not in request.object_ids:
            raise HTTPException(422, "Review decision must concern an input unit")
        # A supplied decision is historical context, not automatic approval of new geometry.
    before = [latest_geometry(db, o.id) for o in objects]
    if [g.id if g else None for g in before] != request.expected_geometry_ids:
        raise HTTPException(409, "An input geometry changed; refresh before submitting")
    datum = before[0].elevation_reference
    low, high = before[0].z_min, before[0].z_max
    if low is None or any(
        g.z_min != low or g.z_max != high or g.elevation_reference != datum
        for g in before
    ):
        raise HTTPException(
            422, "Split/merge inputs require compatible explicit vertical bounds"
        )
    if request.operation in {"SPLIT", "MERGE"}:
        after_polygons = []
        for replacement in request.replacements:
            geometry = replacement.geometry
            if (
                geometry.z_min != low
                or geometry.z_max != high
                or geometry.elevation_reference != datum
            ):
                raise HTTPException(
                    422, "Split/merge must preserve the vertical reference and extent"
                )
            _, metric, _ = project_footprint(
                geometry.footprint, geometry.source_crs, before[0].metric_srid
            )
            after_polygons.append(metric)
        for i, a in enumerate(after_polygons):
            if any(a.intersection(b).area > 1e-4 for b in after_polygons[i + 1 :]):
                raise HTTPException(422, "Split outputs overlap")
        from pyproj import Transformer
        from shapely.ops import transform

        old_polygons = [
            transform(
                Transformer.from_crs(
                    4326, before[0].metric_srid, always_xy=True
                ).transform,
                to_shape(g.footprint),
            )
            for g in before
        ]
        if (
            unary_union(old_polygons)
            .symmetric_difference(unary_union(after_polygons))
            .area
            > 1e-4
        ):
            raise HTTPException(
                422, "Split/merge must conserve mapped area within 0.0001 square metres"
            )
    change = GeometryChange(
        operation=request.operation,
        reason=request.reason,
        evidence_id=evidence.id,
        review_decision_id=request.review_decision_id,
        actor_id=actor,
    )
    db.add(change)
    db.flush()
    for geometry in before:
        db.add(
            ChangeMember(
                change_id=change.id, geometry_id=geometry.id, direction="BEFORE"
            )
        )
    outputs = []
    for replacement in request.replacements:
        obj = (
            objects[0]
            if request.operation == "REPLACE"
            else create_object(
                db,
                ObjectCreate(
                    kind=Kind.UNIT,
                    label=replacement.label,
                    parent_id=objects[0].parent_id,
                    is_synthetic=objects[0].is_synthetic,
                ),
                actor,
            )
        )
        geometry = create_geometry(db, obj.id, replacement.geometry, actor)
        db.add(
            ChangeMember(
                change_id=change.id, geometry_id=geometry.id, direction="AFTER"
            )
        )
        if request.operation != "REPLACE":
            for old in objects:
                db.add(
                    SpatialRelationship(
                        source_id=obj.id, target_id=old.id, relation="PREDECESSOR"
                    )
                )
        outputs.append({"object_id": str(obj.id), "geometry_id": str(geometry.id)})
    if request.operation != "REPLACE":
        for obj in objects:
            obj.lifecycle = "SUPERSEDED"
    audit(
        db,
        actor,
        "PROPERTY_GEOMETRY_CHANGED",
        change,
        {"outputs": outputs, "rights_transferred": False, "status": "DRAFT"},
    )
    return {
        "change_id": str(change.id),
        "outputs": outputs,
        "status": "DRAFT",
        "rights_transferred": False,
    }
