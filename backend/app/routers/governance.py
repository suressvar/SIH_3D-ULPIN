"""Evidence-backed governance over existing spatial and review services."""

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session, defer

from app.auth import current_user, roles
from app.db import get_db
from app.governance_models import PropertyAnnotation, RightScope, WorkflowEvent
from app.models import (
    AppUser,
    AuditEvent,
    Evidence,
    GeometryVersion,
    ProcessingJob,
    PropertyRight,
    ReviewCase,
    ReviewDecision,
    SourceDataset,
    SpatialObject,
    ValidationIssue,
)
from app.pipeline_models import (
    ChangeMember,
    GeometryAttestation,
    GeometryChange,
    IdentityVersion,
)
from app.repositories import audit, require
from app.rules import rule_catalog
from app.schemas import (
    AuditOut,
    Contract,
    DatasetOut,
    DecisionOut,
    EvidenceOut,
    IssueOut,
    JobOut,
    ObjectOut,
    ReviewOut,
    RightOut,
)
from app.services.objects import geometry_out
from app.services.validation import require_validation

router = APIRouter(prefix="/governance", tags=["governance"])


class Payload(Contract):
    result: dict


def row_data(row):
    return jsonable_encoder({c.key: getattr(row, c.key) for c in row.__table__.columns})


@router.get("/rules", response_model=Payload)
def rules(user: AppUser = Depends(current_user)):
    return {"result": rule_catalog()}


@router.get("/objects/{object_id}", response_model=Payload)
def case(
    object_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    obj = require(db, SpatialObject, object_id)
    geometries = list(
        db.scalars(
            select(GeometryVersion)
            .options(
                defer(GeometryVersion.shell), defer(GeometryVersion.metric_footprint)
            )
            .where(GeometryVersion.object_id == object_id)
            .order_by(GeometryVersion.version.desc())
            .limit(21)
        )
    )
    geometry = geometries[0] if geometries else None
    events = list(
        db.scalars(
            select(WorkflowEvent)
            .where(WorkflowEvent.object_id == object_id)
            .order_by(WorkflowEvent.sequence.desc())
            .limit(51)
        )
    )
    evidence = list(
        db.scalars(
            select(Evidence)
            .where(Evidence.object_id == object_id)
            .order_by(Evidence.created_at.desc())
            .limit(51)
        )
    )
    rights = list(
        db.scalars(
            select(PropertyRight)
            .where(PropertyRight.object_id == object_id)
            .order_by(PropertyRight.created_at.desc())
            .limit(51)
        )
    )
    reviews = list(
        db.scalars(
            select(ReviewCase)
            .where(ReviewCase.object_id == object_id)
            .order_by(ReviewCase.created_at.desc())
            .limit(51)
        )
    )
    decisions = list(
        db.scalars(
            select(ReviewDecision)
            .where(ReviewDecision.review_id.in_([r.id for r in reviews]))
            .order_by(ReviewDecision.created_at.desc())
            .limit(51)
        )
    )
    job = (
        db.scalar(
            select(ProcessingJob)
            .where(
                ProcessingJob.geometry_id == geometry.id,
                ProcessingJob.kind == "VALIDATE_PRISM",
            )
            .order_by(ProcessingJob.created_at.desc())
            .limit(1)
        )
        if geometry
        else None
    )
    issues = (
        list(
            db.scalars(
                select(ValidationIssue)
                .where(ValidationIssue.job_id == job.id)
                .order_by(ValidationIssue.id)
                .limit(101)
            )
        )
        if job
        else []
    )
    fresh = False
    validation_reason = "No current geometry"
    if geometry:
        try:
            require_validation(db, geometry.id, job.id if job else None)
            fresh = True
            validation_reason = "Current geometry and semantic snapshot passed"
        except HTTPException as exc:
            validation_reason = str(exc.detail)
    current_events = [e for e in events if geometry and e.geometry_id == geometry.id]
    state = current_events[0].after_state if current_events else "UNTRACKED"
    source_ids = {e.dataset_id for e in evidence} | {
        g.source_dataset_id for g in geometries if g.source_dataset_id
    }
    sources = list(
        db.scalars(select(SourceDataset).where(SourceDataset.id.in_(source_ids)))
    )
    identities = list(
        db.scalars(
            select(IdentityVersion)
            .where(IdentityVersion.geometry_id.in_([g.id for g in geometries]))
            .order_by(IdentityVersion.created_at.desc())
            .limit(51)
        )
    )
    attestations = list(
        db.scalars(
            select(GeometryAttestation)
            .limit(51)
            .where(GeometryAttestation.geometry_id.in_([g.id for g in geometries]))
        )
    )
    changes = list(
        db.scalars(
            select(GeometryChange)
            .join(ChangeMember, ChangeMember.change_id == GeometryChange.id)
            .where(ChangeMember.geometry_id.in_([g.id for g in geometries]))
            .distinct()
            .order_by(GeometryChange.created_at.desc())
            .limit(51)
        )
    )
    ancestors: list[dict] = []
    parent_id = obj.parent_id
    while parent_id and len(ancestors) < 8:
        parent = require(db, SpatialObject, parent_id)
        ancestors.append(ObjectOut.model_validate(parent).model_dump(mode="json"))
        parent_id = parent.parent_id
    ids = [object_id]
    ids.extend(r.id for r in geometries)
    ids.extend(r.id for r in events)
    ids.extend(r.id for r in evidence)
    ids.extend(r.id for r in rights)
    ids.extend(r.id for r in reviews)
    ids.extend(r.id for r in decisions)
    ids.extend(r.id for r in changes)
    ids.extend(r.id for r in identities)
    ids.extend(r.id for r in attestations)
    scopes = list(
        db.scalars(
            select(RightScope)
            .limit(51)
            .where(RightScope.right_id.in_([r.id for r in rights]))
        )
    )
    annotations = list(
        db.scalars(
            select(PropertyAnnotation)
            .where(PropertyAnnotation.object_id == object_id)
            .order_by(PropertyAnnotation.sequence.desc())
            .limit(51)
        )
    )
    ids.extend(r.id for r in scopes)
    ids.extend(r.id for r in annotations)
    history = list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.entity_id.in_(ids))
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(101)
        )
    )
    members_by_change: dict[UUID, list] = {}
    for member in db.scalars(
        select(ChangeMember).where(ChangeMember.change_id.in_([c.id for c in changes]))
    ):
        members_by_change.setdefault(member.change_id, []).append(row_data(member))
    windows: dict[str, tuple[list[Any], int]] = {
        "geometry_versions": (geometries, 20),
        "workflow": (events, 50),
        "evidence": (evidence, 50),
        "rights": (rights, 50),
        "reviews": (reviews, 50),
        "decisions": (decisions, 50),
        "issues": (issues, 100),
        "identity_versions": (identities, 50),
        "attestations": (attestations, 50),
        "changes": (changes, 50),
        "scopes": (scopes, 50),
        "annotations": (annotations, 50),
        "audit": (history, 100),
    }
    pagination = {
        name: {"limit": limit, "has_more": len(rows) > limit}
        for name, (rows, limit) in windows.items()
    }
    for rows, limit in windows.values():
        del rows[limit:]
    events.reverse()
    annotations.reverse()
    history.reverse()
    return {
        "result": {
            "pagination": pagination,
            "object": ObjectOut.model_validate(obj).model_dump(mode="json"),
            "geometry": (
                geometry_out(geometry).model_dump(mode="json") if geometry else None
            ),
            "geometry_versions": [
                geometry_out(g).model_dump(mode="json") for g in geometries
            ],
            "state": state,
            "history_note": "Workflow events begin with phase 4; earlier records remain in audit history.",
            "validation_fresh": fresh,
            "validation_reason": validation_reason,
            "validation_job": (
                JobOut.model_validate(job).model_dump(mode="json") if job else None
            ),
            "issues": [
                IssueOut.model_validate(i).model_dump(mode="json") for i in issues
            ],
            "evidence": [
                EvidenceOut.model_validate(e).model_dump(mode="json") for e in evidence
            ],
            "rights": [
                RightOut.model_validate(r).model_dump(mode="json") for r in rights
            ],
            "reviews": [
                ReviewOut.model_validate(r).model_dump(mode="json") for r in reviews
            ],
            "decisions": [
                DecisionOut.model_validate(r).model_dump(mode="json") for r in decisions
            ],
            "workflow": [row_data(e) for e in events],
            "scopes": [row_data(e) for e in scopes],
            "annotations": [row_data(e) for e in annotations],
            "audit": (
                [AuditOut.model_validate(e).model_dump(mode="json") for e in history]
                if user.role != "viewer"
                else []
            ),
            "ancestors": ancestors,
            "sources": [
                DatasetOut.model_validate(r).model_dump(mode="json") for r in sources
            ],
            "identity_versions": [row_data(r) for r in identities],
            "attestations": [row_data(r) for r in attestations],
            "changes": [
                {
                    **row_data(r),
                    "members": members_by_change.get(r.id, []),
                }
                for r in changes
            ],
            "legal_effect": "Prototype review only; not proof of legal title",
        }
    }


class ScopeCreate(Contract):
    right_id: UUID
    related_object_id: UUID
    reason: str = Field(min_length=5, max_length=3000)


@router.post("/right-scopes", response_model=Payload, status_code=201)
def add_scope(
    payload: ScopeCreate,
    db: Session = Depends(get_db),
    user: AppUser = Depends(roles("surveyor", "admin")),
):
    db.execute(text("SELECT pg_advisory_xact_lock(26011002)"))
    right = require(db, PropertyRight, payload.right_id)
    source = require(db, SpatialObject, right.object_id)
    target = require(db, SpatialObject, payload.related_object_id)
    if source.id == target.id or source.is_synthetic != target.is_synthetic:
        raise HTTPException(
            422, "Choose a distinct space with matching data designation"
        )
    if right.right_type not in {"SHARED_USE", "ACCESS", "EASEMENT", "RESTRICTION"}:
        raise HTTPException(
            422, "Only shared, access, easement or restriction assertions can be scoped"
        )
    row = RightScope(**payload.model_dump(), actor_id=user.id)
    db.add(row)
    db.flush()
    audit(
        db,
        user.id,
        "RIGHT_SCOPE_RECORDED",
        row,
        {
            "object_id": str(source.id),
            "related_object_id": str(target.id),
            "evidence_id": str(right.evidence_id),
            "reason": payload.reason,
            "legal_effect": "none",
        },
    )
    return {"result": row_data(row)}


class AnnotationCreate(Contract):
    display_label: str = Field(min_length=1, max_length=160)
    address: str | None = Field(default=None, max_length=500)
    land_use: str | None = Field(default=None, max_length=100)
    evidence_id: UUID
    reason: str = Field(min_length=5, max_length=3000)
    expected_previous_id: UUID | None = None


@router.post(
    "/objects/{object_id}/annotations", response_model=Payload, status_code=201
)
def annotate(
    object_id: UUID,
    payload: AnnotationCreate,
    db: Session = Depends(get_db),
    user: AppUser = Depends(roles("surveyor", "admin")),
):
    require(db, SpatialObject, object_id, lock=True)
    evidence = require(db, Evidence, payload.evidence_id)
    if evidence.object_id != object_id:
        raise HTTPException(422, "Evidence must belong to this property")
    previous = db.scalar(
        select(PropertyAnnotation)
        .where(PropertyAnnotation.object_id == object_id)
        .order_by(PropertyAnnotation.sequence.desc())
        .limit(1)
    )
    if (previous.id if previous else None) != payload.expected_previous_id:
        raise HTTPException(409, "Property details changed; reload before saving")
    row = PropertyAnnotation(
        object_id=object_id,
        actor_id=user.id,
        **payload.model_dump(exclude={"expected_previous_id"}),
    )
    db.add(row)
    db.flush()
    audit(
        db,
        user.id,
        "PROPERTY_DETAILS_RECORDED",
        row,
        {
            "object_id": str(object_id),
            "before": row_data(previous) if previous else None,
            "after": row_data(row),
            "reason": payload.reason,
        },
    )
    return {"result": row_data(row)}


@router.get("/review-queue", response_model=Payload)
def review_queue(db: Session = Depends(get_db), user: AppUser = Depends(current_user)):
    rows = db.execute(
        select(ReviewCase, SpatialObject)
        .join(SpatialObject, SpatialObject.id == ReviewCase.object_id)
        .order_by(ReviewCase.created_at.desc())
        .limit(100)
    )
    return {
        "result": {
            "items": [
                {
                    **ReviewOut.model_validate(r).model_dump(mode="json"),
                    "object_label": o.label,
                    "parcel_id": str(o.parcel_id or o.id),
                }
                for r, o in rows
            ]
        }
    }


class MemberUpdate(Contract):
    role: Literal["admin", "surveyor", "officer", "viewer"]
    active: bool
    reason: str = Field(min_length=5, max_length=2000)


@router.get("/members", response_model=Payload)
def members(db: Session = Depends(get_db), user: AppUser = Depends(roles("admin"))):
    return {
        "result": {
            "items": [
                row_data(r)
                for r in db.scalars(
                    select(AppUser).order_by(AppUser.created_at).limit(200)
                )
            ]
        }
    }


@router.post("/members/{member_id}", response_model=Payload)
def update_member(
    member_id: UUID,
    payload: MemberUpdate,
    db: Session = Depends(get_db),
    user: AppUser = Depends(roles("admin")),
):
    db.execute(text("SELECT pg_advisory_xact_lock(26011003)"))
    member = require(db, AppUser, member_id, lock=True)
    if (
        member.role == "admin"
        and member.active
        and (payload.role != "admin" or not payload.active)
    ):
        if (
            len(
                list(
                    db.scalars(
                        select(AppUser.id).where(
                            AppUser.role == "admin", AppUser.active
                        )
                    )
                )
            )
            <= 1
        ):
            raise HTTPException(409, "Keep at least one active administrator")
    before = {"role": member.role, "active": member.active}
    member.role, member.active = payload.role, payload.active
    audit(
        db,
        user.id,
        "MEMBERSHIP_UPDATED",
        member,
        {
            "before": before,
            "after": {"role": payload.role, "active": payload.active},
            "reason": payload.reason,
        },
    )
    return {"result": row_data(member)}


@router.get("/objects/{object_id}/history", response_model=Payload)
def object_history(
    object_id: UUID,
    kind: Literal[
        "geometry_versions",
        "workflow",
        "evidence",
        "rights",
        "reviews",
        "annotations",
        "audit",
        "changes",
    ] = "workflow",
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100000),
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    require(db, SpatialObject, object_id)
    mapping: dict[str, Any] = {
        "geometry_versions": GeometryVersion,
        "workflow": WorkflowEvent,
        "evidence": Evidence,
        "rights": PropertyRight,
        "reviews": ReviewCase,
        "annotations": PropertyAnnotation,
        "audit": AuditEvent,
        "changes": GeometryChange,
    }
    model = mapping[kind]
    if kind == "audit":
        if user.role == "viewer":
            raise HTTPException(
                403, "Audit access requires a project editing or review role"
            )
        # Include linked entity records through indexed subqueries, not a client-provided table name.
        clauses = [AuditEvent.entity_id == object_id]
        related_models: list[Any] = [
            GeometryVersion,
            WorkflowEvent,
            Evidence,
            PropertyRight,
            ReviewCase,
            PropertyAnnotation,
        ]
        for related in related_models:
            clauses.append(
                AuditEvent.entity_id.in_(
                    select(related.id).where(related.object_id == object_id)
                )
            )
        geometry_ids = select(GeometryVersion.id).where(
            GeometryVersion.object_id == object_id
        )
        review_ids = select(ReviewCase.id).where(ReviewCase.object_id == object_id)
        right_ids = select(PropertyRight.id).where(PropertyRight.object_id == object_id)
        clauses.extend(
            [
                AuditEvent.entity_id.in_(
                    select(ReviewDecision.id).where(
                        ReviewDecision.review_id.in_(review_ids)
                    )
                ),
                AuditEvent.entity_id.in_(
                    select(IdentityVersion.id).where(
                        IdentityVersion.geometry_id.in_(geometry_ids)
                    )
                ),
                AuditEvent.entity_id.in_(
                    select(GeometryAttestation.id).where(
                        GeometryAttestation.geometry_id.in_(geometry_ids)
                    )
                ),
                AuditEvent.entity_id.in_(
                    select(RightScope.id).where(RightScope.right_id.in_(right_ids))
                ),
                AuditEvent.entity_id.in_(
                    select(ChangeMember.change_id).where(
                        ChangeMember.geometry_id.in_(geometry_ids)
                    )
                ),
            ]
        )
        clauses.append(AuditEvent.detail["object_id"].astext == str(object_id))
        from sqlalchemy import or_

        stmt = select(model).where(or_(*clauses))
    elif kind == "changes":
        stmt = (
            select(model)
            .join(ChangeMember, ChangeMember.change_id == GeometryChange.id)
            .join(GeometryVersion, GeometryVersion.id == ChangeMember.geometry_id)
            .where(GeometryVersion.object_id == object_id)
            .distinct()
        )
    else:
        stmt = select(model).where(model.object_id == object_id)
    if kind == "geometry_versions":
        stmt = stmt.options(
            defer(GeometryVersion.shell), defer(GeometryVersion.metric_footprint)
        )
    ordering = (
        (model.version.desc(),)
        if kind == "geometry_versions"
        else (
            (model.sequence.desc(),)
            if kind in ("workflow", "annotations")
            else (model.created_at.desc(), model.id.desc())
        )
    )
    rows = list(db.scalars(stmt.order_by(*ordering).limit(limit + 1).offset(offset)))
    members: dict[UUID, list[dict]] = {}
    if kind == "changes" and rows:
        for member in db.scalars(
            select(ChangeMember).where(
                ChangeMember.change_id.in_([r.id for r in rows[:limit]])
            )
        ):
            members.setdefault(member.change_id, []).append(row_data(member))
    return {
        "result": {
            "kind": kind,
            "items": [
                (
                    geometry_out(r).model_dump(mode="json")
                    if kind == "geometry_versions"
                    else row_data(r)
                    | ({"members": members.get(r.id, [])} if kind == "changes" else {})
                )
                for r in rows[:limit]
            ],
            "limit": limit,
            "offset": offset,
            "next_offset": offset + limit if len(rows) > limit else None,
        }
    }
