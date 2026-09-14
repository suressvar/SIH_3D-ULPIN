from typing import Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.assistance import model_status
from app.auth import current_user, roles
from app.config import get_settings
from app.db import get_db
from app.models import (
    AppUser,
    Evidence,
    GeometryVersion,
    ProcessingJob,
    ReviewCase,
    Source,
    SpatialObject,
    SpatialRelationship,
    ValidationIssue,
)
from app.pipeline_models import (
    AssetBundle,
    ChangeMember,
    GeometryAttestation,
    GeometryChange,
    HeightObservation,
    IdentityVersion,
    SpatialSuggestion,
    SuggestionDecision,
)
from app.pipeline_schemas import (
    AttestationInput,
    ChangeInput,
    FloorLevelsInput,
    HeightInput,
    IssueAcknowledge,
    ProcessingRequest,
    RelationshipInput,
    SuggestionAdopt,
)
from app.repositories import audit, latest_geometry, require
from app.schemas import Contract, DatasetOut, JobOut
from app.services.exports import export_available
from app.services.history import change_property
from app.services.pipeline import (
    adopt_suggestion,
    create_floor_levels,
    queue_processing,
    record_height,
    register_processing_source,
)
from app.storage import read_bytes

router = APIRouter(tags=["spatial-pipeline"])
writer = roles("surveyor", "admin")


class Result(Contract):
    result: dict


class Results(Contract):
    items: list[dict]


@router.get("/pipeline/capabilities", response_model=Result)
def capabilities(user: AppUser = Depends(current_user)):
    return {
        "result": {
            "models": model_status(),
            "height_estimation": True,
            "plan_regions": True,
            "geometric_point_planes": True,
            "asset_export": export_available(),
            "point_formats": ["NPY"],
            "note": "Capabilities do not constitute inference accuracy or acceptance",
        }
    }


@router.post("/pipeline/datasets", response_model=DatasetOut, status_code=201)
async def upload_processing(
    file: UploadFile = File(),
    intent: Literal["raster", "plan", "points"] = Form(),
    source_category: Source = Form(),
    is_synthetic: bool = Form(False),
    db: Session = Depends(get_db),
    user: AppUser = Depends(writer),
):
    content = await file.read(get_settings().max_upload_bytes + 1)
    await file.close()
    if not content or len(content) > get_settings().max_upload_bytes:
        raise HTTPException(413, "Empty or oversized source")
    return register_processing_source(
        db,
        content,
        (file.filename or "upload").replace("\\", "/").split("/")[-1],
        source_category,
        is_synthetic,
        user.id,
        intent,
    )


@router.post("/pipeline/jobs", response_model=JobOut, status_code=202)
def process(
    request: ProcessingRequest,
    db: Session = Depends(get_db),
    user: AppUser = Depends(writer),
):
    return queue_processing(db, request, user.id)


@router.get("/pipeline/suggestions", response_model=Results)
def suggestions(
    parent_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    rows = list(
        db.scalars(
            select(SpatialSuggestion)
            .where(SpatialSuggestion.parent_id == parent_id)
            .order_by(SpatialSuggestion.created_at)
            .limit(limit)
            .offset(offset)
        )
    )
    decisions = {
        d.suggestion_id: d
        for d in db.scalars(
            select(SuggestionDecision).where(
                SuggestionDecision.suggestion_id.in_([s.id for s in rows])
            )
        )
    }
    items = []
    for s in rows:
        decision = decisions.get(s.id)
        items.append(
            {
                "id": str(s.id),
                "parent_id": str(s.parent_id),
                "dataset_id": str(s.dataset_id),
                "kind": s.kind,
                "label": s.label,
                "footprint": mapping(to_shape(s.footprint)),
                "source": s.source_category,
                "confidence": s.confidence,
                "method": s.method,
                "is_synthetic": s.is_synthetic,
                "status": decision.decision if decision else "SUGGESTED",
                "geometry_id": (
                    str(decision.geometry_id)
                    if decision and decision.geometry_id
                    else None
                ),
            }
        )
    return {"items": items}


@router.post("/pipeline/suggestions/{suggestion_id}/decision", response_model=Result)
def adopt(
    suggestion_id: UUID,
    request: SuggestionAdopt,
    db: Session = Depends(get_db),
    user: AppUser = Depends(writer),
):
    result = adopt_suggestion(db, suggestion_id, request, user.id)
    return {
        "result": {
            "decision_id": str(result.id),
            "status": result.decision,
            "geometry_id": str(result.geometry_id) if result.geometry_id else None,
        }
    }


@router.post("/pipeline/heights", response_model=Result, status_code=201)
def height(
    request: HeightInput, db: Session = Depends(get_db), user: AppUser = Depends(writer)
):
    value = record_height(db, request, user.id)
    return {
        "result": {
            "id": str(value.id),
            "height_value": value.height_value,
            "height_source": value.height_source,
            "estimated": value.estimated,
        }
    }


@router.get("/pipeline/heights/{object_id}", response_model=Results)
def heights(
    object_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    rows = db.scalars(
        select(HeightObservation)
        .where(HeightObservation.object_id == object_id)
        .order_by(HeightObservation.created_at)
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [
            {
                "id": str(x.id),
                "height_value": x.height_value,
                "base_elevation": x.base_elevation,
                "height_source": x.height_source,
                "confidence": x.confidence,
                "vertical_reference": x.vertical_reference,
                "estimated": x.estimated,
                "details": x.details,
            }
            for x in rows
        ]
    }


@router.post("/pipeline/floors", response_model=Results, status_code=201)
def floors(
    request: FloorLevelsInput,
    db: Session = Depends(get_db),
    user: AppUser = Depends(writer),
):
    return {"items": create_floor_levels(db, request, user.id)}


@router.post("/pipeline/validate/{object_id}", response_model=JobOut, status_code=202)
def validate(
    object_id: UUID,
    require_complete_partition: bool = False,
    db: Session = Depends(get_db),
    user: AppUser = Depends(writer),
):
    obj = require(db, SpatialObject, object_id)
    geometry = latest_geometry(db, obj.id)
    if geometry is None:
        raise HTTPException(409, "Geometry is missing")
    job = ProcessingJob(
        kind="VALIDATE_PRISM",
        geometry_id=geometry.id,
        parameters={"require_complete_partition": require_complete_partition},
        created_by=user.id,
    )
    db.add(job)
    audit(db, user.id, "JOB_QUEUED", job)
    return job


@router.get("/pipeline/issues/{issue_id}", response_model=Result)
def issue(
    issue_id: UUID, db: Session = Depends(get_db), user: AppUser = Depends(current_user)
):
    row = require(db, ValidationIssue, issue_id)
    return {
        "result": {
            "issue_id": str(row.id),
            "severity": row.severity,
            "type": row.code,
            "status": row.status,
            "affected_object": row.details.get("affected_object"),
            "affected_geometry": (
                mapping(to_shape(row.affected_geometry))
                if row.affected_geometry is not None
                else None
            ),
            "rule": row.code,
            "explanation": row.message,
            "details": row.details,
        }
    }


@router.post("/pipeline/issues/{issue_id}/acknowledge", response_model=Result)
def acknowledge(
    issue_id: UUID,
    request: IssueAcknowledge,
    db: Session = Depends(get_db),
    user: AppUser = Depends(roles("officer", "admin")),
):
    row = require(db, ValidationIssue, issue_id)
    row.status = "ACKNOWLEDGED"
    audit(
        db,
        user.id,
        "VALIDATION_ISSUE_ACKNOWLEDGED",
        row,
        {"reason": request.reason, "validation_overridden": False},
    )
    return {
        "result": {
            "issue_id": str(row.id),
            "status": row.status,
            "validation_overridden": False,
        }
    }


@router.post("/pipeline/relationships", response_model=Result, status_code=201)
def relationship(
    request: RelationshipInput,
    db: Session = Depends(get_db),
    user: AppUser = Depends(roles("officer", "admin")),
):
    db.execute(text("SELECT pg_advisory_xact_lock(26011002)"))
    source = require(db, SpatialObject, request.source_id)
    target = require(db, SpatialObject, request.target_id)
    evidence = require(db, Evidence, request.evidence_id)
    if source.is_synthetic != target.is_synthetic or evidence.object_id not in {
        source.id,
        target.id,
    }:
        raise HTTPException(
            422, "Relationship requires matching evidence and data designation"
        )
    if request.relation == "SHARED_BY" and {source.kind, target.kind} != {
        "SHARED",
        "UNIT",
    }:
        raise HTTPException(422, "SHARED_BY requires a shared space and a unit")
    row = SpatialRelationship(
        source_id=source.id, target_id=target.id, relation=request.relation
    )
    db.add(row)
    audit(
        db,
        user.id,
        "SPATIAL_RELATIONSHIP_RECORDED",
        row,
        {"evidence_id": str(evidence.id), "reason": request.reason},
    )
    return {"result": {"id": str(row.id)}}


@router.post("/pipeline/changes", response_model=Result, status_code=201)
def change(
    request: ChangeInput, db: Session = Depends(get_db), user: AppUser = Depends(writer)
):
    return {"result": change_property(db, request, user.id)}


@router.get("/pipeline/history/{object_id}", response_model=Results)
def history(
    object_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    ids = select(GeometryVersion.id).where(GeometryVersion.object_id == object_id)
    changes = db.scalars(
        select(GeometryChange)
        .join(ChangeMember, ChangeMember.change_id == GeometryChange.id)
        .where(ChangeMember.geometry_id.in_(ids))
        .distinct()
        .order_by(GeometryChange.created_at)
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [
            {
                "id": str(c.id),
                "operation": c.operation,
                "reason": c.reason,
                "actor": str(c.actor_id),
                "timestamp": c.created_at.isoformat(),
                "evidence_id": str(c.evidence_id),
                "review_decision_id": (
                    str(c.review_decision_id) if c.review_decision_id else None
                ),
                "versions": [
                    {"geometry_id": str(m.geometry_id), "direction": m.direction}
                    for m in db.scalars(
                        select(ChangeMember).where(ChangeMember.change_id == c.id)
                    )
                ],
            }
            for c in changes
        ]
    }


@router.get("/pipeline/identity-versions/{object_id}", response_model=Results)
def identity_versions(
    object_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    rows = db.scalars(
        select(IdentityVersion)
        .join(GeometryVersion, IdentityVersion.geometry_id == GeometryVersion.id)
        .where(GeometryVersion.object_id == object_id)
        .order_by(IdentityVersion.created_at)
        .limit(100)
    )
    return {
        "items": [
            {
                "id": str(r.id),
                "canonical_code": r.canonical_code,
                "geometry_id": str(r.geometry_id),
                "geometry_hash": r.geometry_hash,
                "label": "Proposed 3D ULPIN",
                "identity_inputs": r.identity_inputs,
            }
            for r in rows
        ]
    }


@router.get("/pipeline/geometry/{geometry_id}/status", response_model=Result)
def geometry_status(
    geometry_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    geom = require(db, GeometryVersion, geometry_id)
    attestations = list(
        db.scalars(
            select(GeometryAttestation).where(
                GeometryAttestation.geometry_id == geom.id
            )
        )
    )
    job = db.scalar(
        select(ProcessingJob)
        .where(
            ProcessingJob.geometry_id == geom.id,
            ProcessingJob.status == "COMPLETED",
            ProcessingJob.kind == "VALIDATE_PRISM",
        )
        .order_by(ProcessingJob.completed_at.desc())
        .limit(1)
    )
    review = db.scalar(
        select(ReviewCase)
        .where(
            ReviewCase.geometry_id == geom.id, ReviewCase.status == "ACCEPTED_PROTOTYPE"
        )
        .limit(1)
    )
    from app.services.validation import snapshot

    obj = require(db, SpatialObject, geom.object_id)
    current = latest_geometry(db, obj.id).id == geom.id and obj.lifecycle == "ACTIVE"
    fresh = bool(
        job and job.result.get("snapshot") == snapshot(db, obj.parcel_id or obj.id)
    )
    return {
        "result": {
            "geometry_id": str(geom.id),
            "source_labels": {
                "AI_ESTIMATE": "AI estimated",
                "APPROVED_PLAN": "Plan derived",
                "MANUAL": "Manual correction",
                "DERIVED": "Derived suggestion",
            }.get(geom.source_category, geom.source_category),
            "attestations": [a.status for a in attestations],
            "validated": bool(job and job.result.get("passed") and fresh),
            "accepted": bool(review and current),
            "current": current,
            "legal_effect": "none; prototype review",
        }
    }


@router.post("/pipeline/geometry/{geometry_id}/attest", response_model=Result)
def attest(
    geometry_id: UUID,
    request: AttestationInput,
    db: Session = Depends(get_db),
    user: AppUser = Depends(roles("officer", "admin")),
):
    geom = require(db, GeometryVersion, geometry_id)
    obj = require(db, SpatialObject, geom.object_id)
    evidence = require(db, Evidence, request.evidence_id)
    if obj.is_synthetic or evidence.object_id != obj.id:
        raise HTTPException(
            422,
            "Synthetic data cannot receive survey/plan verification; evidence must match the object",
        )
    row = GeometryAttestation(
        geometry_id=geom.id,
        evidence_id=evidence.id,
        status=request.status,
        reason=request.reason,
        actor_id=user.id,
    )
    db.add(row)
    audit(db, user.id, "GEOMETRY_ATTESTED", row)
    return {"result": {"id": str(row.id), "status": row.status}}


@router.get("/exports/{bundle_id}", response_model=Result)
def export_manifest(
    bundle_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    bundle = require(db, AssetBundle, bundle_id)
    return {
        "result": {
            "id": str(bundle.id),
            "files": {
                name: {
                    "url": f"/api/v1/exports/{bundle.id}/files/{name}",
                    "sha256": item["sha256"],
                    "bytes": item["bytes"],
                }
                for name, item in bundle.manifest.items()
            },
            "placement": bundle.placement,
            "validation": bundle.validation,
        }
    }


@router.get("/exports/{bundle_id}/files/{filename}")
def export_file(
    bundle_id: UUID,
    filename: str,
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    bundle = require(db, AssetBundle, bundle_id)
    if filename not in bundle.manifest:
        raise HTTPException(404, "Asset not in this bundle")
    info = bundle.manifest[filename]
    import hashlib

    content = read_bytes(info["key"])
    if hashlib.sha256(content).hexdigest() != info["sha256"]:
        raise HTTPException(503, "Stored asset checksum mismatch")
    media = (
        "image/png"
        if filename.endswith(".png")
        else (
            "model/gltf-binary"
            if filename.endswith(".glb")
            else (
                "application/geo+json"
                if filename.endswith(".geojson")
                else "application/json"
            )
        )
    )
    return Response(
        content,
        media_type=media,
        headers={
            "ETag": '"' + info["sha256"] + '"',
            "Cache-Control": "private, max-age=31536000, immutable",
        },
    )
