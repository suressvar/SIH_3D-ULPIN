"""Regenerate an immutable asset bundle through the real job worker."""

import argparse
import json
from uuid import UUID

from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.models import AppUser, ProcessingJob, SpatialObject
from app.repositories import audit, require
from app.worker import run_job


def refresh(parcel_id):
    if get_settings().environment == "production":
        raise RuntimeError("Use authenticated API jobs in production")
    with get_session() as db, db.begin():
        parcel = require(db, SpatialObject, UUID(parcel_id))
        if not parcel.is_synthetic:
            raise ValueError("This development command is for synthetic fixtures only")
        actor = db.scalar(select(AppUser).where(AppUser.role == "surveyor"))
        if actor is None:
            raise ValueError("No surveyor actor available")
        job = ProcessingJob(
            kind="EXPORT_ASSETS",
            created_by=actor.id,
            parameters={
                "kind": "EXPORT_ASSETS",
                "object_id": parcel_id,
                "vertical_offset_to_ellipsoid": 0,
            },
        )
        db.add(job)
        db.flush()
        audit(db, actor.id, "JOB_QUEUED", job)
        job_id = job.id
    run_job(str(job_id))
    with get_session() as db:
        job = require(db, ProcessingJob, job_id)
        if job.status != "COMPLETED":
            raise RuntimeError(job.error_message)
        return {
            "job_id": str(job.id),
            "status": job.status,
            "asset_bundle_id": job.result["asset_bundle_id"],
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("parcel_id")
    print(json.dumps(refresh(parser.parse_args().parcel_id), indent=2))
