"""Small, idempotent synthetic fixture. Run only against a development database."""

import json
from uuid import NAMESPACE_URL, uuid5

from shapely.geometry import box, mapping
from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.models import AppUser, ProcessingJob, Source, SourceDataset, SpatialObject
from app.repositories import audit
from app.schemas import EvidenceCreate, GeometryCreate, ObjectCreate, RightCreate
from app.services.objects import create_geometry, create_object
from app.services.records import attach_evidence, issue_identity, record_right
from app.storage import put_bytes
from app.worker import run_job

LABEL = "Demo / Synthetic Dataset"


def uid(name: str):
    return uuid5(NAMESPACE_URL, "astra-sih26011-demo-v1/" + name)


def footprint(x1=0, y1=0, x2=30, y2=30):
    return mapping(box(400000 + x1, 1440000 + y1, 400000 + x2, 1440000 + y2))


def seed():
    if get_settings().environment == "production":
        raise RuntimeError("Synthetic seeding is disabled in production")
    job_ids = []
    with get_session() as db, db.begin():
        if db.get(SpatialObject, uid("parcel")):
            completed_jobs = list(
                db.scalars(
                    select(ProcessingJob).where(
                        ProcessingJob.id.in_(
                            [
                                uid(f"validation-unit-{f}0{u}")
                                for f in range(1, 4)
                                for u in [1, 2]
                            ]
                        )
                    )
                )
            )
            if len(completed_jobs) != 6 or any(
                job.status != "COMPLETED" for job in completed_jobs
            ):
                raise RuntimeError(
                    "An incomplete seed exists; inspect its processing jobs before retrying"
                )
            return {
                "dataset": LABEL,
                "parcel_id": str(uid("parcel")),
                "status": "already seeded",
            }
        for name, role in [("surveyor", "surveyor"), ("officer", "officer")]:
            if not db.get(AppUser, uid(name)):
                db.add(AppUser(id=uid(name), role=role, active=False))
        db.flush()
        actor = uid("surveyor")
        original = json.dumps(
            {
                "type": "FeatureCollection",
                "name": LABEL,
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"label": LABEL, "is_synthetic": True},
                        "geometry": footprint(),
                    }
                ],
                "source_note": "Entirely synthetic metric coordinates EPSG:32644; not surveyed, not government data",
            },
            sort_keys=True,
        ).encode()
        key, digest = put_bytes(original)
        source = SourceDataset(
            id=uid("source"),
            filename="synthetic-plan.json",
            media_type="application/json",
            source_category=Source.MANUAL,
            object_key=key,
            sha256=digest,
            byte_size=len(original),
            status="READY",
            inspection={
                "format": "Synthetic fixture",
                "source_crs": "EPSG:32644",
                "note": LABEL,
            },
            is_synthetic=True,
            created_by=actor,
        )
        db.add(source)
        db.flush()

        def obj(
            name,
            kind,
            parent=None,
            bounds=(0, 0, 30, 30),
            low=None,
            high=None,
            floor_number=None,
        ):
            item = create_object(
                db,
                ObjectCreate(
                    kind=kind,
                    label=f"{LABEL} — {name}",
                    parent_id=uid(parent) if parent else None,
                    floor_number=floor_number,
                    is_synthetic=True,
                ),
                actor,
                uid(name),
            )
            geom = create_geometry(
                db,
                item.id,
                GeometryCreate(
                    footprint=footprint(*bounds),
                    source_crs="EPSG:32644",
                    metric_srid=32644,
                    z_min=low,
                    z_max=high,
                    elevation_reference=(
                        "SYNTHETIC_LOCAL_DATUM" if low is not None else None
                    ),
                    source_category=Source.MANUAL,
                    source_dataset_id=source.id,
                    method="Deterministic synthetic vertical prism; heights are designed fixture values, not observations",
                ),
                actor,
            )
            return item, geom

        obj("parcel", "PARCEL")
        obj("building", "BUILDING", "parcel", (2, 2, 22, 22), 0, 9)
        for floor in range(1, 4):
            floor_name = f"floor-{floor}"
            obj(
                floor_name,
                "FLOOR",
                "building",
                (2, 2, 22, 22),
                (floor - 1) * 3,
                floor * 3,
                floor,
            )
            for unit in range(1, 3):
                name = f"unit-{floor}0{unit}"
                # First-floor second unit overlaps its neighbour by 1m; other floors do not.
                left = 9 if floor == 1 and unit == 2 else 12
                bounds = (3, 3, 10, 20) if unit == 1 else (left, 3, 21, 20)
                item, geom = obj(
                    name, "UNIT", floor_name, bounds, (floor - 1) * 3, floor * 3
                )
                evidence = attach_evidence(
                    db,
                    EvidenceCreate(
                        object_id=item.id,
                        dataset_id=source.id,
                        description="Synthetic design fixture; not an approved plan or proof of title",
                    ),
                    actor,
                )
                record_right(
                    db,
                    RightCreate(
                        object_id=item.id,
                        evidence_id=evidence.id,
                        right_type="RECORDED_OWNERSHIP",
                        party_reference=f"SYNTHETIC-PARTY-{floor}0{unit}",
                        description="Fictional demonstration assertion with no legal effect",
                        is_synthetic=True,
                    ),
                    actor,
                )
                job = ProcessingJob(
                    id=uid(f"validation-{name}"),
                    kind="VALIDATE_PRISM",
                    geometry_id=geom.id,
                    created_by=actor,
                )
                db.add(job)
                job_ids.append(str(job.id))
        obj("shared-corridor", "SHARED", "building", (10, 2, 12, 22), 0, 9)
        obj("basement", "UNDERGROUND", "parcel", (2, 2, 22, 22), -3, 0)
        audit(db, actor, "SYNTHETIC_DATASET_SEEDED", source, {"label": LABEL})
    # Same real handlers as the worker, deliberately run synchronously by this CLI.
    for job_id in job_ids:
        run_job(job_id)
    with get_session() as db, db.begin():
        for floor in [2, 3]:
            for unit in [1, 2]:
                issue_identity(db, uid(f"unit-{floor}0{unit}"), uid("surveyor"))
        jobs = list(
            db.scalars(
                select(ProcessingJob).where(
                    ProcessingJob.id.in_(
                        [
                            uid(f"validation-unit-{f}0{u}")
                            for f in range(1, 4)
                            for u in [1, 2]
                        ]
                    )
                )
            )
        )
        if any(j.status != "COMPLETED" for j in jobs):
            raise RuntimeError("Seed validation failed; inspect processing jobs")
    return {"dataset": LABEL, "parcel_id": str(uid("parcel")), "status": "seeded"}


if __name__ == "__main__":
    print(json.dumps(seed(), indent=2))
