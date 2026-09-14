from uuid import UUID

from fastapi import HTTPException
from geoalchemy2.shape import from_shape, to_shape
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import (
    GeometryVersion,
    Kind,
    ProcessingJob,
    SpatialObject,
    ValidationIssue,
)
from app.repositories import audit, current_geometries, latest_geometry, require
from app.rules import RULESET_VERSION, rule_catalog
from app.services.topology import extra_rules, semantic_snapshot
from app.services.workflow import transition
from app.spatial import overlap_volume


def snapshot(db: Session, parcel_id: UUID) -> dict:
    return {
        **{str(g.object_id): str(g.id) for g in current_geometries(db, parcel_id)},
        "_semantics": semantic_snapshot(db, parcel_id),
    }


def validate_prism(db: Session, job: ProcessingJob) -> dict:
    db.execute(text("SELECT pg_advisory_xact_lock(26011002)"))
    if job.geometry_id is None:
        raise ValueError("Validation job is missing geometry")
    geom = require(db, GeometryVersion, job.geometry_id)
    obj = require(db, SpatialObject, geom.object_id)
    root = obj.parcel_id or obj.id
    require(db, SpatialObject, root, lock=True)
    if latest_geometry(db, obj.id).id != geom.id:
        raise ValueError("Validation requested for a superseded geometry version")
    transition(
        db,
        geom,
        "VALIDATION",
        job.created_by,
        "Prism validation started",
        job_id=job.id,
    )
    issues = []

    def issue(code, severity, message, related=None, details=None):
        data = dict(details or {})
        affected = data.pop("_affected", None)
        data["rule_definition"] = rule_catalog().get(code)
        data.update(
            {"rule": code, "affected_object": str(obj.id), "explanation": message}
        )
        entry = ValidationIssue(
            job_id=job.id,
            geometry_id=geom.id,
            related_geometry_id=related.id if related else None,
            code=code,
            severity=severity,
            message=message,
            details=data,
            affected_geometry=(
                from_shape(shape(affected), srid=4326) if affected else None
            ),
        )
        db.add(entry)
        issues.append(entry)

    if geom.z_min is None and obj.kind != Kind.PARCEL:
        issue(
            "HEIGHT_REQUIRED",
            "ERROR",
            "No vertical extent; volumetric validation cannot run",
        )
    if geom.height_estimated:
        issue(
            "ESTIMATED_HEIGHT",
            "WARNING",
            "Height is estimated and requires evidence review",
        )
    parent_geom = latest_geometry(db, obj.parent_id) if obj.parent_id else None
    if obj.parent_id and not parent_geom:
        issue(
            "PARENT_GEOMETRY_MISSING", "ERROR", "Parent geometry must be mapped first"
        )
    if parent_geom:
        if not to_shape(parent_geom.footprint).covers(to_shape(geom.footprint)):
            issue(
                "OUTSIDE_PARENT",
                (
                    "WARNING"
                    if obj.kind in {Kind.EASEMENT, Kind.INFRASTRUCTURE}
                    else "ERROR"
                ),
                "Footprint extends outside its parent; assess supporting rights",
                parent_geom,
            )
        if geom.z_min is not None and parent_geom.z_min is not None:
            if geom.elevation_reference != parent_geom.elevation_reference:
                issue(
                    "VERTICAL_REFERENCE_MISMATCH",
                    "ERROR",
                    "Parent and child heights use different references",
                    parent_geom,
                )
            elif geom.z_min < parent_geom.z_min or geom.z_max > parent_geom.z_max:
                issue(
                    "OUTSIDE_PARENT_HEIGHT",
                    "ERROR",
                    "Volume exceeds parent vertical extent",
                    parent_geom,
                )

    candidates = current_geometries(db, root)
    # Structural containers intentionally enclose their descendants. Only exclusive
    # units are compared as mutually exclusive; other rights need their own rules.
    if obj.kind == Kind.UNIT and geom.z_min is not None:
        metric = to_shape(geom.metric_footprint)
        for other in candidates:
            if other.id == geom.id:
                continue
            other_obj = require(db, SpatialObject, other.object_id)
            if other_obj.kind != Kind.UNIT:
                continue
            if not to_shape(geom.footprint).intersects(to_shape(other.footprint)):
                continue
            if (
                other.z_min is None
                or other.elevation_reference != geom.elevation_reference
            ):
                issue(
                    "INCOMPARABLE_NEIGHBOUR",
                    "ERROR",
                    "Overlapping footprint has missing or incompatible vertical reference",
                    other,
                )
                continue
            projection = Transformer.from_crs(4326, geom.metric_srid, always_xy=True)
            other_metric = transform(projection.transform, to_shape(other.footprint))
            volume = overlap_volume(
                metric, geom.z_min, geom.z_max, other_metric, other.z_min, other.z_max
            )
            if volume > 1e-6:
                issue(
                    "EXCLUSIVE_VOLUME_OVERLAP",
                    "ERROR",
                    f"{obj.label} overlaps {other_obj.label}; two exclusive unit volumes intersect. Review their boundaries and recorded rights",
                    other,
                    {
                        "_affected": mapping(
                            transform(
                                Transformer.from_crs(
                                    geom.metric_srid, 4326, always_xy=True
                                ).transform,
                                metric.intersection(other_metric),
                            )
                        ),
                        "z_min": max(geom.z_min, other.z_min),
                        "z_max": min(geom.z_max, other.z_max),
                        "intersection_volume_m3": volume,
                        "method": "footprint intersection area multiplied by shared Z extent",
                        "numerical_tolerance_m3": 1e-6,
                    },
                )
    extra_rules(db, job, obj, geom, issue)
    db.flush()
    result = {
        "geometry_id": str(geom.id),
        "method": "VERTICAL_PRISM_V2",
        "ruleset_version": RULESET_VERSION,
        "scope": "2D validity, immediate-parent containment, explicit heights and exclusive unit prisms within one parcel",
        "not_checked": [
            "arbitrary solids",
            "legal title",
            "unregistered cross-parcel conflicts",
            "structural safety",
            "gaps unless complete partition explicitly requested",
        ],
        "passed": not any(i.severity in {"ERROR", "CRITICAL"} for i in issues),
        "issue_count": len(issues),
        "snapshot": snapshot(db, root),
    }
    audit(
        db,
        job.created_by,
        "GEOMETRY_VALIDATED",
        geom,
        {"job_id": str(job.id), "passed": result["passed"]},
    )
    transition(
        db,
        geom,
        "VALIDATED" if result["passed"] else "CORRECTION_REQUIRED",
        job.created_by,
        (
            "Prism validation passed"
            if result["passed"]
            else "Blocking validation findings require correction"
        ),
        job_id=job.id,
    )
    return result


def require_validation(
    db: Session, geometry_id: UUID, job_id: UUID | None = None
) -> ProcessingJob:
    geom = require(db, GeometryVersion, geometry_id)
    obj = require(db, SpatialObject, geom.object_id)
    if latest_geometry(db, obj.id).id != geom.id:
        raise HTTPException(
            409, "Geometry has been superseded; validate its latest version"
        )
    stmt = (
        select(ProcessingJob)
        .where(
            ProcessingJob.geometry_id == geom.id, ProcessingJob.status == "COMPLETED"
        )
        .order_by(ProcessingJob.completed_at.desc())
    )
    if job_id:
        stmt = stmt.where(ProcessingJob.id == job_id)
    job = db.scalar(stmt.limit(1))
    if not job or not job.result.get("passed"):
        raise HTTPException(409, "A completed passing validation is required")
    if job.result.get("snapshot") != snapshot(db, obj.parcel_id or obj.id):
        raise HTTPException(
            409, "Parcel geometry changed after validation; run validation again"
        )
    return job
