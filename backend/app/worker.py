import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from celery import Celery
from sqlalchemy import select, update

from app.config import get_settings
from app.db import get_session
from app.models import ProcessingJob, SourceDataset
from app.repositories import audit
from app.services.exports import build_assets
from app.services.ingestion import ingest_geojson
from app.services.pipeline import process_assistance
from app.services.validation import validate_prism

logger = logging.getLogger(__name__)
celery_app = Celery("astra", broker=get_settings().redis_url)
celery_app.conf.update(
    task_ignore_result=True,
    task_serializer="json",
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "dispatch-persisted-jobs": {"task": "astra.dispatch", "schedule": 5.0}
    },
)


def run_job(job_id: str):
    identity = UUID(job_id)
    now = datetime.now(UTC)
    with get_session() as db, db.begin():
        claimed = db.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == identity, ProcessingJob.status == "QUEUED")
            .values(status="RUNNING", started_at=now, progress=10)
            .returning(ProcessingJob.id)
        ).scalar_one_or_none()
        if claimed is None:
            return
    try:
        with get_session() as db, db.begin():
            job = db.scalar(
                select(ProcessingJob)
                .where(ProcessingJob.id == identity)
                .with_for_update()
            )
            if job is None or job.status != "RUNNING":
                return
            handler = {
                "INGEST_GEOJSON": ingest_geojson,
                "VALIDATE_PRISM": validate_prism,
                "SUGGEST_BUILDINGS": process_assistance,
                "SUGGEST_UNITS": process_assistance,
                "ESTIMATE_HEIGHT": process_assistance,
                "SUGGEST_LEVELS": process_assistance,
                "EXPORT_ASSETS": build_assets,
            }[job.kind]
            job.result = handler(db, job)
            job.status, job.progress, job.completed_at = (
                "COMPLETED",
                100,
                datetime.now(UTC),
            )
            audit(db, job.created_by, "JOB_COMPLETED", job)
    except Exception as exc:
        logger.exception("Processing failed: %s", identity)
        # Input validation errors are safe to expose; infrastructure tracebacks stay in logs.
        message = (
            str(exc)[:2000]
            if isinstance(exc, ValueError)
            else "Processing failed; consult worker logs with the job ID"
        )
        with get_session() as db, db.begin():
            job = db.get(ProcessingJob, identity)
            if job is None:
                raise RuntimeError("Processing job disappeared") from exc
            job.status, job.completed_at, job.error_message = (
                "FAILED",
                datetime.now(UTC),
                message,
            )
            if job.input_dataset_id and job.kind == "INGEST_GEOJSON":
                dataset = db.get(SourceDataset, job.input_dataset_id)
                if dataset is None:
                    raise RuntimeError("Source dataset disappeared") from exc
                dataset.status, dataset.error_message = "REJECTED", message
            audit(db, job.created_by, "JOB_FAILED", job, {"message": message})


@celery_app.task(name="astra.process")
def process_job(job_id: str):
    run_job(job_id)


@celery_app.task(name="astra.dispatch")
def dispatch_jobs():
    with get_session() as db, db.begin():
        jobs = list(
            db.scalars(
                select(ProcessingJob)
                .where(
                    ProcessingJob.status == "QUEUED",
                    (ProcessingJob.dispatched_at.is_(None))
                    | (
                        ProcessingJob.dispatched_at
                        < datetime.now(UTC) - timedelta(seconds=60)
                    ),
                )
                .with_for_update(skip_locked=True)
                .limit(20)
            )
        )
        for job in jobs:
            process_job.apply_async(args=[str(job.id)], task_id=str(job.id))
            job.dispatched_at = datetime.now(UTC)
    # No false success on worker crash: mark old unlocked running work as failed.
    # Active handlers hold a row lock, so they are skipped even if slow.
    with get_session() as db, db.begin():
        abandoned = list(
            db.scalars(
                select(ProcessingJob)
                .where(
                    ProcessingJob.status == "RUNNING",
                    ProcessingJob.started_at
                    < datetime.now(UTC) - timedelta(minutes=10),
                )
                .with_for_update(skip_locked=True)
                .limit(20)
            )
        )
        for job in abandoned:
            job.status, job.completed_at = "FAILED", datetime.now(UTC)
            job.error_message = (
                "Worker interrupted before committing output; submit a new job"
            )
            audit(db, job.created_by, "JOB_INTERRUPTED", job)
