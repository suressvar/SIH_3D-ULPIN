from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, roles
from app.db import get_db
from app.models import (
    AppUser,
    GeometryVersion,
    ProcessingJob,
    SourceDataset,
    ValidationIssue,
)
from app.repositories import audit, require
from app.schemas import IssueOut, JobCreate, JobOut

router = APIRouter(tags=["processing"])


@router.post("/processing", response_model=JobOut, status_code=202)
def enqueue(
    payload: JobCreate,
    db: Session = Depends(get_db),
    user: AppUser = Depends(roles("surveyor", "admin")),
):
    if payload.kind not in {"INGEST_GEOJSON", "VALIDATE_PRISM"}:
        raise HTTPException(
            422, "Use /pipeline/jobs with validated processing parameters"
        )
    if payload.input_dataset_id:
        dataset = require(db, SourceDataset, payload.input_dataset_id, lock=True)
        if dataset.inspection.get("intent") != "parcel" or dataset.status == "READY":
            raise HTTPException(409, "Only unprocessed parcel sources can be submitted")
        active = db.scalar(
            select(ProcessingJob)
            .where(
                ProcessingJob.input_dataset_id == dataset.id,
                ProcessingJob.status.in_(["QUEUED", "RUNNING"]),
            )
            .limit(1)
        )
        if active:
            return active
        dataset.status, dataset.error_message = "UPLOADED", None
    if payload.geometry_id:
        require(db, GeometryVersion, payload.geometry_id)
    job = ProcessingJob(**payload.model_dump(), created_by=user.id)
    db.add(job)
    audit(db, user.id, "JOB_QUEUED", job)
    return job


@router.get("/processing", response_model=list[JobOut])
def jobs(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    return list(
        db.scalars(
            select(ProcessingJob)
            .order_by(ProcessingJob.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )


@router.get("/processing/{job_id}", response_model=JobOut)
def job_detail(
    job_id: UUID, db: Session = Depends(get_db), user: AppUser = Depends(current_user)
):
    return require(db, ProcessingJob, job_id)


@router.post("/processing/{job_id}/cancel", response_model=JobOut)
def cancel(
    job_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser = Depends(roles("surveyor", "admin")),
):
    job = require(db, ProcessingJob, job_id, lock=True)
    if job.created_by != user.id and user.role != "admin":
        raise HTTPException(403, "Only the submitter or admin can cancel this job")
    if job.status != "QUEUED":
        raise HTTPException(
            409, "Only queued jobs can be cancelled safely in this phase"
        )
    job.status, job.completed_at = "CANCELLED", datetime.now(UTC)
    audit(db, user.id, "JOB_CANCELLED", job)
    return job


@router.get(
    "/validation/{job_id}/issues", response_model=list[IssueOut], tags=["validation"]
)
def issues(
    job_id: UUID,
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: AppUser = Depends(current_user),
):
    require(db, ProcessingJob, job_id)
    return list(
        db.scalars(
            select(ValidationIssue)
            .where(ValidationIssue.job_id == job_id)
            .order_by(ValidationIssue.id)
            .limit(limit)
            .offset(offset)
        )
    )
