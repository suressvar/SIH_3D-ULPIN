from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, roles
from app.db import get_db
from app.models import (
    AppUser,
    AuditEvent,
    Evidence,
    PropertyRight,
    ReviewCase,
    ULPINIdentity,
)
from app.repositories import require
from app.schemas import (
    AuditOut,
    DecisionCreate,
    DecisionOut,
    EvidenceCreate,
    EvidenceOut,
    IdentityOut,
    ReviewCreate,
    ReviewOut,
    RightCreate,
    RightOut,
)
from app.services.records import (
    attach_evidence,
    decide_review,
    issue_identity,
    record_right,
    submit_review,
)

router = APIRouter()
writer = roles("surveyor", "admin")


@router.post(
    "/evidence", response_model=EvidenceOut, status_code=201, tags=["evidence"]
)
def add_evidence(
    payload: EvidenceCreate,
    db: Session = Depends(get_db),
    user: AppUser = Depends(writer),
):
    return attach_evidence(db, payload, user.id)


@router.get("/evidence", response_model=list[EvidenceOut], tags=["evidence"])
def evidence(
    object_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    return list(
        db.scalars(
            select(Evidence)
            .where(Evidence.object_id == object_id)
            .order_by(Evidence.created_at)
            .limit(limit)
            .offset(offset)
        )
    )


@router.post("/rights", response_model=RightOut, status_code=201, tags=["rights"])
def add_right(
    payload: RightCreate, db: Session = Depends(get_db), user: AppUser = Depends(writer)
):
    return record_right(db, payload, user.id)


@router.get("/rights", response_model=list[RightOut], tags=["rights"])
def rights(
    object_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    return list(
        db.scalars(
            select(PropertyRight)
            .where(PropertyRight.object_id == object_id)
            .order_by(PropertyRight.created_at)
            .limit(limit)
            .offset(offset)
        )
    )


@router.post("/ulpin/{object_id}", response_model=IdentityOut, tags=["ulpin"])
def identity(
    object_id: UUID, db: Session = Depends(get_db), user: AppUser = Depends(writer)
):
    return issue_identity(db, object_id, user.id)


@router.get("/ulpin", response_model=list[IdentityOut], tags=["ulpin"])
def find_identity(
    identifier: str = Query(min_length=1, max_length=100),
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    return list(
        db.scalars(select(ULPINIdentity).where(ULPINIdentity.identifier == identifier))
    )


@router.post("/reviews", response_model=ReviewOut, status_code=201, tags=["reviews"])
def review(
    payload: ReviewCreate,
    db: Session = Depends(get_db),
    user: AppUser = Depends(writer),
):
    return submit_review(db, payload, user.id)


@router.get("/reviews", response_model=list[ReviewOut], tags=["reviews"])
def reviews(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    return list(
        db.scalars(
            select(ReviewCase)
            .order_by(ReviewCase.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )


@router.get("/reviews/{review_id}", response_model=ReviewOut, tags=["reviews"])
def review_detail(
    review_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    return require(db, ReviewCase, review_id)


@router.post(
    "/reviews/{review_id}/decisions",
    response_model=DecisionOut,
    status_code=201,
    tags=["reviews"],
)
def decide(
    review_id: UUID,
    payload: DecisionCreate,
    db: Session = Depends(get_db),
    user: AppUser = Depends(roles("officer", "admin")),
):
    return decide_review(db, review_id, payload, user.id)


@router.get("/audit", response_model=list[AuditOut], tags=["audit"])
def history(
    entity_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: AppUser = Depends(roles("surveyor", "officer", "admin")),
):
    stmt = select(AuditEvent)
    if entity_id:
        stmt = stmt.where(AuditEvent.entity_id == entity_id)
    return list(
        db.scalars(
            stmt.order_by(AuditEvent.created_at.desc()).limit(limit).offset(offset)
        )
    )
