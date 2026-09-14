from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import (
    Evidence,
    GeometryVersion,
    PropertyRight,
    ReviewCase,
    ReviewDecision,
    SourceDataset,
    SpatialObject,
    ULPINIdentity,
)
from app.pipeline_models import IdentityVersion
from app.repositories import audit, latest_geometry, require
from app.schemas import DecisionCreate, EvidenceCreate, ReviewCreate, RightCreate
from app.services.history import append_identity_version, canonical_identity_code
from app.services.validation import require_validation
from app.services.workflow import transition


def attach_evidence(db: Session, payload: EvidenceCreate, actor: UUID):
    obj = require(db, SpatialObject, payload.object_id)
    source = require(db, SourceDataset, payload.dataset_id)
    if source.status not in {"READY", "EVIDENCE_ONLY"}:
        raise HTTPException(
            422, "Rejected or unprocessed data cannot serve as evidence"
        )
    if obj.is_synthetic != source.is_synthetic:
        raise HTTPException(
            422, "Synthetic evidence designation must match the property"
        )
    record = Evidence(**payload.model_dump(), created_by=actor)
    db.add(record)
    audit(db, actor, "EVIDENCE_ATTACHED", record)
    return record


def record_right(db: Session, payload: RightCreate, actor: UUID):
    db.execute(text("SELECT pg_advisory_xact_lock(26011002)"))
    obj = require(db, SpatialObject, payload.object_id)
    evidence = require(db, Evidence, payload.evidence_id)
    if evidence.object_id != obj.id or payload.is_synthetic != obj.is_synthetic:
        raise HTTPException(
            422, "Right, evidence and synthetic designation must match the property"
        )
    right = PropertyRight(**payload.model_dump(), created_by=actor)
    db.add(right)
    audit(
        db, actor, "RIGHT_RECORDED", right, {"legal_status": "recorded assertion only"}
    )
    return right


def issue_identity(db: Session, object_id: UUID, actor: UUID):
    db.execute(text("SELECT pg_advisory_xact_lock(26011002)"))
    obj = require(db, SpatialObject, object_id)
    require(db, SpatialObject, obj.parcel_id or obj.id, lock=True)
    if obj.kind not in {
        "BUILDING",
        "UNIT",
        "UNDERGROUND",
        "SHARED",
        "EASEMENT",
        "INFRASTRUCTURE",
    }:
        raise HTTPException(422, "Proposed identity applies to a property space")
    existing = db.scalar(
        select(ULPINIdentity).where(ULPINIdentity.object_id == object_id)
    )
    geom = latest_geometry(db, object_id)
    if not geom:
        raise HTTPException(409, "Property has no geometry")
    require_validation(db, geom.id)
    if geom.z_min is None:
        raise HTTPException(409, "Proposed 3D identity requires explicit height bounds")
    if existing:
        append_identity_version(db, existing, geom, actor)
        return existing
    parcel = require(db, SpatialObject, obj.parcel_id)
    code, _ = canonical_identity_code(
        parcel.existing_ulpin or f"PARCEL-UUID:{parcel.id}", obj.id, geom.geometry_hash
    )
    # Preserve prior identity records; new identities include canonical geometry inputs.
    identity = ULPINIdentity(
        object_id=obj.id,
        issued_geometry_id=geom.id,
        identifier=code,
        scheme_version="ASTRA-PROTOTYPE-2",
        created_by=actor,
    )
    db.add(identity)
    audit(
        db,
        actor,
        "PROPOSED_IDENTITY_ISSUED",
        identity,
        {"parent_parcel_id": str(obj.parcel_id), "official_standard": False},
    )
    append_identity_version(db, identity, geom, actor)
    return identity


def submit_review(db: Session, payload: ReviewCreate, actor: UUID):
    db.execute(text("SELECT pg_advisory_xact_lock(26011002)"))
    geom = require(db, GeometryVersion, payload.geometry_id)
    obj = require(db, SpatialObject, geom.object_id)
    require(db, SpatialObject, obj.parcel_id or obj.id, lock=True)
    require_validation(db, geom.id, payload.validation_job_id)
    if not db.scalar(select(Evidence).where(Evidence.object_id == obj.id).limit(1)):
        raise HTTPException(409, "Supporting evidence is required before review")
    if not db.scalar(select(ULPINIdentity).where(ULPINIdentity.object_id == obj.id)):
        raise HTTPException(409, "Issue the proposed identity before submitting review")
    if not db.scalar(
        select(IdentityVersion).where(IdentityVersion.geometry_id == geom.id)
    ):
        raise HTTPException(
            409, "Record the Proposed 3D ULPIN for this geometry version before review"
        )
    review = ReviewCase(
        object_id=obj.id,
        geometry_id=geom.id,
        validation_job_id=payload.validation_job_id,
        submitted_by=actor,
    )
    db.add(review)
    audit(db, actor, "REVIEW_SUBMITTED", review)
    transition(
        db,
        geom,
        "REVIEW",
        actor,
        "Submitted for prototype review",
        job_id=payload.validation_job_id,
    )
    return review


def decide_review(db: Session, review_id: UUID, payload: DecisionCreate, actor: UUID):
    db.execute(text("SELECT pg_advisory_xact_lock(26011002)"))
    review = require(db, ReviewCase, review_id, lock=True)
    obj = require(db, SpatialObject, review.object_id)
    require(db, SpatialObject, obj.parcel_id or obj.id, lock=True)
    if review.status != "SUBMITTED":
        raise HTTPException(409, "Review has already been decided")
    if review.submitted_by == actor:
        raise HTTPException(403, "Reviewer must be different from submitter")
    if payload.decision == "ACCEPTED_PROTOTYPE":
        require_validation(db, review.geometry_id, review.validation_job_id)
    decision = ReviewDecision(
        review_id=review.id, reviewer_id=actor, **payload.model_dump()
    )
    review.status = payload.decision
    db.add(decision)
    audit(
        db,
        actor,
        "REVIEW_DECIDED",
        decision,
        {
            "review_id": str(review.id),
            "decision": payload.decision,
            "legal_effect": "none; prototype review",
        },
    )
    transition(
        db,
        require(db, GeometryVersion, review.geometry_id),
        (
            "ACCEPTED"
            if payload.decision == "ACCEPTED_PROTOTYPE"
            else "CORRECTION_REQUIRED"
        ),
        actor,
        payload.reason,
        decision_id=decision.id,
    )
    return decision
