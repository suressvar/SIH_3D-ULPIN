"""Named, deterministic synthetic judge property; no model inference is fabricated."""

import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import cv2
import numpy as np
from pyproj import Transformer
from shapely.geometry import box, mapping, shape
from shapely.ops import transform
from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.models import (
    AppUser,
    Evidence,
    ProcessingJob,
    Source,
    SourceDataset,
    SpatialObject,
)
from app.pipeline_models import AssetBundle
from app.pipeline_schemas import ChangeInput, ProcessingRequest, ReplacementUnit
from app.repositories import audit, latest_geometry
from app.schemas import EvidenceCreate, GeometryCreate, ObjectCreate, RightCreate
from app.services.history import change_property
from app.services.objects import create_geometry, create_object, geometry_out
from app.services.records import attach_evidence, issue_identity, record_right
from app.storage import put_bytes
from app.worker import run_job


def uid(name):
    return uuid5(NAMESPACE_URL, "astra-judge-demo-v1/" + name)


def footprint(x1, y1, x2, y2):
    # Separate from earlier fixtures; these are explicitly synthetic UTM metres.
    return mapping(box(401000 + x1, 1441000 + y1, 401000 + x2, 1441000 + y2))


def seed_judge(output=Path("output/judge-demo")):
    if get_settings().environment == "production":
        raise RuntimeError("Synthetic seeding is disabled in production")
    output.mkdir(parents=True, exist_ok=True)
    parcel_id = uid("P001")
    conflict = transform(
        Transformer.from_crs(32644, 4326, always_xy=True).transform,
        shape(footprint(5, 5, 19, 23)),
    )
    (output / "conflict-A301.geojson").write_text(
        json.dumps(mapping(conflict), indent=2), encoding="utf-8"
    )
    with get_session() as db:
        existing = db.get(SpatialObject, parcel_id)
        if existing:
            bundle = db.scalar(
                select(AssetBundle)
                .where(AssetBundle.parcel_id == parcel_id)
                .order_by(AssetBundle.created_at.desc())
            )
            if not bundle:
                raise RuntimeError(
                    "Unfinished judge fixture exists; inspect jobs before resuming"
                )
            manifest_path = output / "manifest.json"
            if manifest_path.exists():
                info = json.loads(manifest_path.read_text(encoding="utf-8"))
                info["asset_bundle_id"] = str(bundle.id)
                manifest_path.write_text(json.dumps(info, indent=2), encoding="utf-8")
                return info | {"status": "already seeded; history retained"}
            return {
                "parcel_id": str(parcel_id),
                "status": "already seeded; history retained",
                "asset_bundle_id": str(bundle.id),
            }

    actor = uid("surveyor")
    units = []
    spaces = []
    with get_session() as db, db.begin():
        if not db.get(AppUser, actor):
            db.add(AppUser(id=actor, role="surveyor", active=False))
        db.flush()
        source_doc = {
            "label": "Demo / Synthetic Dataset",
            "source": "Synthetic survey-coordinate fixture, not a real survey",
            "crs": "EPSG:32644",
            "elevation_reference": "EPSG:4979",
            "parcel": footprint(0, 0, 32, 32),
            "building": footprint(4, 4, 28, 24),
            "floor_layout": {
                "unit_A": footprint(5, 5, 14, 23),
                "unit_B": footprint(18, 5, 27, 23),
                "corridor": footprint(14, 5, 18, 21),
                "staircase": footprint(14, 21, 18, 23),
            },
            "floor_to_floor_m": 3,
            "ground_elevation_m": 10,
            "note": "All coordinates, heights, parties and records in this fixture are synthetic.",
        }
        raw = json.dumps(source_doc, indent=2).encode()
        (output / "synthetic-survey.json").write_bytes(raw)
        key, digest = put_bytes(raw)
        source = SourceDataset(
            id=uid("survey-source"),
            filename="synthetic-survey.json",
            media_type="application/json",
            source_category=Source.SURVEY,
            object_key=key,
            sha256=digest,
            byte_size=len(raw),
            status="READY",
            is_synthetic=True,
            created_by=actor,
            inspection={
                "method": "curated synthetic coordinate fixture; each polygon validated by the geometry service",
                "declared_source_crs": "EPSG:32644",
                "real_survey": False,
            },
        )
        db.add(source)
        audit(
            db,
            actor,
            "DATASET_REGISTERED",
            source,
            {"is_synthetic": True, "method": "curated fixture"},
        )
        canvas = np.full((580, 880, 3), 255, dtype=np.uint8)
        cv2.putText(
            canvas,
            "DEMO / SYNTHETIC DATASET",
            (30, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (30, 50, 40),
            2,
        )
        cv2.putText(
            canvas,
            "Illustrative floor plan - no real ownership or survey",
            (30, 73),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (40, 40, 40),
            1,
        )
        for a, b in [
            ((40, 110), (350, 490)),
            ((350, 110), (480, 430)),
            ((350, 430), (480, 490)),
            ((480, 110), (790, 490)),
        ]:
            cv2.rectangle(canvas, a, b, (50, 60, 50), 3)
        for title, xy in [
            ("Unit A", (100, 270)),
            ("Corridor", (355, 270)),
            ("Stairs", (370, 465)),
            ("Unit B", (580, 270)),
        ]:
            cv2.putText(
                canvas, title, xy, cv2.FONT_HERSHEY_SIMPLEX, 0.6, (40, 70, 50), 1
            )
        cv2.putText(
            canvas,
            "Six occupied levels: GF, F1, F2, F3, F4, F5; roof; B1 parking",
            (30, 545),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (40, 40, 40),
            1,
        )
        ok, image = cv2.imencode(".png", canvas)
        if not ok:
            raise RuntimeError("Could not create synthetic plan")
        content = image.tobytes()
        (output / "synthetic-approved-plan.png").write_bytes(content)
        key, digest = put_bytes(content)
        plan = SourceDataset(
            id=uid("plan-source"),
            filename="synthetic-approved-plan.png",
            media_type="image/png",
            source_category="APPROVED_PLAN",
            object_key=key,
            sha256=digest,
            byte_size=len(content),
            status="EVIDENCE_ONLY",
            is_synthetic=True,
            created_by=actor,
            inspection={
                "note": "Illustrative approved-plan source classification; no actual government approval"
            },
        )
        db.add(plan)
        audit(db, actor, "DATASET_REGISTERED", plan, {"is_synthetic": True})

        def add(name, kind, parent, bounds, z=None, floor=None, semantic=None):
            obj = create_object(
                db,
                ObjectCreate(
                    kind=kind,
                    label=(
                        "Demo / Synthetic Dataset â€” P001"
                        if kind == "PARCEL"
                        else name
                    ),
                    parent_id=uid(parent) if parent else None,
                    floor_number=floor,
                    semantic_type=semantic,
                    is_synthetic=True,
                    existing_ulpin="DEMO26011P0001" if kind == "PARCEL" else None,
                ),
                actor,
                uid(name),
            )
            payload = GeometryCreate(
                footprint=footprint(*bounds),
                source_crs="EPSG:32644",
                metric_srid=32644,
                z_min=z[0] if z else None,
                z_max=z[1] if z else None,
                elevation_reference="EPSG:4979" if z else None,
                source_category=Source.SURVEY,
                source_dataset_id=source.id,
                method="Synthetic supplied coordinate and elevation fixture; not a real survey",
            )
            create_geometry(db, obj.id, payload, actor)
            attach_evidence(
                db,
                EvidenceCreate(
                    object_id=obj.id,
                    dataset_id=plan.id,
                    description="Demo / Synthetic Dataset â€” illustrative floor plan and source dimensions",
                ),
                actor,
            )
            return obj

        add("P001", "PARCEL", None, (0, 0, 32, 32))
        add("B01", "BUILDING", "P001", (4, 4, 28, 24), (10, 28.3))
        for n in range(6):
            label = "GF" if n == 0 else "F" + str(n)
            add(label, "FLOOR", "B01", (4, 4, 28, 24), (10 + 3 * n, 13 + 3 * n), n)
            for suffix, bounds in [("01", (5, 5, 14, 23)), ("02", (18, 5, 27, 23))]:
                name = "A-" + str(n) + suffix
                obj = add(name, "UNIT", label, bounds, (10 + 3 * n, 13 + 3 * n))
                units.append(obj.id)
                spaces.append(obj.id)
            spaces.append(
                add(
                    "Corridor " + label,
                    "SHARED",
                    label,
                    (14, 5, 18, 21),
                    (10 + 3 * n, 13 + 3 * n),
                    semantic="CORRIDOR",
                ).id
            )
            spaces.append(
                add(
                    "Staircase " + label,
                    "SHARED",
                    label,
                    (14, 21, 18, 23),
                    (10 + 3 * n, 13 + 3 * n),
                    semantic="STAIRCASE",
                ).id
            )
        add("Roof", "FLOOR", "B01", (4, 4, 28, 24), (28, 28.3), 6, "ROOF")
        spaces.append(
            add(
                "Shared roof",
                "SHARED",
                "Roof",
                (4, 4, 28, 24),
                (28, 28.3),
                semantic="ROOF_ACCESS",
            ).id
        )
        spaces.append(
            add(
                "B1 parking",
                "UNDERGROUND",
                "P001",
                (4, 4, 28, 24),
                (7, 10),
                semantic="PARKING",
            ).id
        )
        evidence = db.scalar(select(Evidence).where(Evidence.object_id == uid("A-301")))
        assert evidence is not None
        record_right(
            db,
            RightCreate(
                object_id=uid("A-301"),
                evidence_id=evidence.id,
                right_type="RECORDED_OWNERSHIP",
                party_reference="SYNTHETIC PARTY A301",
                description="Illustrative recorded information; no real owner or legal effect",
                is_synthetic=True,
            ),
            actor,
        )
        jobs = []
        for object_id in spaces:
            job = ProcessingJob(
                kind="VALIDATE_PRISM",
                geometry_id=latest_geometry(db, object_id).id,
                created_by=actor,
                parameters={},
            )
            db.add(job)
            db.flush()
            audit(db, actor, "JOB_QUEUED", job)
            jobs.append(job.id)
    for job_id in jobs:
        run_job(str(job_id))
    with get_session() as db, db.begin():
        for object_id in spaces:
            issue_identity(db, object_id, actor)
        original = latest_geometry(db, uid("A-301"))
        (output / "corrected-A301.geojson").write_text(
            json.dumps(geometry_out(original).footprint, indent=2), encoding="utf-8"
        )
        evidence = db.scalar(select(Evidence).where(Evidence.object_id == uid("A-301")))
        assert evidence is not None
        # A real historical manual revision preserves an inspected source boundary.
        corrected = GeometryCreate(
            footprint=geometry_out(original).footprint,
            source_crs="EPSG:4326",
            metric_srid=32644,
            z_min=19,
            z_max=22,
            elevation_reference="EPSG:4979",
            source_category=Source.MANUAL,
            source_dataset_id=uid("plan-source"),
            method="Synthetic manual plan reconciliation; boundary retained after inspection",
        )
        change_property(
            db,
            ChangeInput(
                operation="REPLACE",
                object_ids=[uid("A-301")],
                expected_geometry_ids=[original.id],
                replacements=[ReplacementUnit(label="A-301", geometry=corrected)],
                evidence_id=evidence.id,
                reason="Synthetic historical plan reconciliation",
            ),
            actor,
        )
        prior = latest_geometry(db, uid("A-301"))
        bad = GeometryCreate(
            footprint=footprint(5, 5, 19, 23),
            source_crs="EPSG:32644",
            metric_srid=32644,
            z_min=19,
            z_max=22,
            elevation_reference="EPSG:4979",
            source_category=Source.DERIVED,
            source_dataset_id=uid("survey-source"),
            method="Synthetic test error: east boundary extended by 5 m from supplied coordinates; no AI inference",
        )
        change_property(
            db,
            ChangeInput(
                operation="REPLACE",
                object_ids=[uid("A-301")],
                expected_geometry_ids=[prior.id],
                replacements=[ReplacementUnit(label="A-301", geometry=bad)],
                evidence_id=evidence.id,
                reason="Introduce a disclosed synthetic error for the judge correction workflow",
            ),
            actor,
        )
        check = ProcessingJob(
            kind="VALIDATE_PRISM",
            geometry_id=latest_geometry(db, uid("A-301")).id,
            created_by=actor,
            parameters={},
        )
        export = ProcessingJob(
            kind="EXPORT_ASSETS",
            created_by=actor,
            parameters=ProcessingRequest(
                kind="EXPORT_ASSETS",
                object_id=parcel_id,
                vertical_offset_to_ellipsoid=0,
            ).model_dump(mode="json"),
        )
        db.add_all([check, export])
        db.flush()
        audit(db, actor, "JOB_QUEUED", check)
        audit(db, actor, "JOB_QUEUED", export)
        check_id, export_id = check.id, export.id
    run_job(str(check_id))
    run_job(str(export_id))
    with get_session() as db:
        check_result = db.get(ProcessingJob, check_id)
        export_result = db.get(ProcessingJob, export_id)
        assert check_result is not None and export_result is not None
        if (
            check_result.status != "COMPLETED"
            or check_result.result.get("passed")
            or export_result.status != "COMPLETED"
        ):
            raise RuntimeError(
                "Judge fixture validation/export did not produce the required real outputs"
            )
        result = {
            "label": "Demo / Synthetic Dataset",
            "parcel_id": str(parcel_id),
            "search": "DEMO26011P0001",
            "building_id": str(uid("B01")),
            "floor_id": str(uid("F3")),
            "unit_id": str(uid("A-301")),
            "corrected_footprint_file": "corrected-A301.geojson",
            "asset_bundle_id": export_result.result["asset_bundle_id"],
            "ai_boundary": "Unavailable: no trained checkpoint supplied; DERIVED test error is explicitly not AI output",
            "legal_effect": "none",
        }
        (output / "manifest.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        return result


if __name__ == "__main__":
    print(json.dumps(seed_judge(), indent=2))
