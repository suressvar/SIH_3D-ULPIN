"""Deterministic source-data pipeline; never calls a model in synthetic mode."""

import io
import json
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import cv2
import numpy as np
from geoalchemy2.shape import to_shape
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from shapely.geometry import box, mapping
from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.models import (
    AppUser,
    GeometryVersion,
    Kind,
    ProcessingJob,
    Source,
    SpatialObject,
)
from app.pipeline_models import AssetBundle, HeightObservation, SpatialSuggestion
from app.pipeline_schemas import (
    FloorLevelsInput,
    Level,
    ProcessingRequest,
    SuggestionAdopt,
)
from app.repositories import latest_geometry, require
from app.schemas import EvidenceCreate, GeometryCreate, ObjectCreate
from app.services.objects import create_geometry, create_object
from app.services.pipeline import (
    adopt_suggestion,
    create_floor_levels,
    queue_processing,
    register_processing_source,
)
from app.services.records import attach_evidence, issue_identity
from app.storage import read_bytes
from app.worker import run_job

NAMESPACE = "astra-sih26011-spatial-demo-v2/"
LABEL = "Demo / Synthetic Dataset"


def uid(name):
    return uuid5(NAMESPACE_URL, NAMESPACE + name)


def geotiff(array, transform, units=None):
    with MemoryFile() as mem:
        with mem.open(
            driver="GTiff",
            height=array.shape[0],
            width=array.shape[1],
            count=1,
            dtype=str(array.dtype),
            crs="EPSG:32644",
            transform=transform,
            nodata=-9999 if units else None,
        ) as dst:
            dst.write(array, 1)
            if units:
                dst.set_band_unit(1, units)
                dst.update_tags(VERTICAL_REFERENCE="EPSG:4979")
        return mem.read()


def fixture_inputs():
    affine = from_origin(400000, 1440032, 1, 1)
    mask = np.zeros((32, 32), dtype="uint8")
    mask[8:28, 4:24] = 1
    ground = np.full((32, 32), 10, dtype="float32")
    surface = ground + mask * 15
    plan = np.full((20, 20), 255, dtype="uint8")
    plan[[0, -1], :] = 0
    plan[:, [0, -1, 9, 11]] = 0
    ok, png = cv2.imencode(".png", plan)
    if not ok:
        raise RuntimeError("Synthetic plan encoding failed")
    rng = np.random.default_rng(26011)
    points = np.vstack(
        [
            np.column_stack(
                [
                    400004 + rng.uniform(0, 20, 80),
                    1440004 + rng.uniform(0, 20, 80),
                    np.full(80, 10 + 3 * i) + rng.normal(0, 0.005, 80),
                ]
            )
            for i in range(6)
        ]
    )
    buffer = io.BytesIO()
    np.save(buffer, points, allow_pickle=False)
    return {
        "mask.tif": geotiff(mask, affine),
        "dem.tif": geotiff(ground, affine, "m"),
        "dsm.tif": geotiff(surface, affine, "m"),
        "floor-plan.png": png.tobytes(),
        "planes.npy": buffer.getvalue(),
    }


def finish_job(job_id):
    run_job(str(job_id))
    with get_session() as db:
        job = require(db, ProcessingJob, job_id)
        if job.status != "COMPLETED":
            raise RuntimeError(
                f"Pipeline job {job_id}: {job.status}: {job.error_message}"
            )
        return job.result


def demo(output_directory: Path):
    if get_settings().environment == "production":
        raise RuntimeError("Synthetic processing is disabled in production")
    with get_session() as db:
        existing = db.scalar(
            select(AssetBundle).where(AssetBundle.parcel_id == uid("parcel"))
        )
        if existing:
            return materialize(existing, output_directory)
        if db.get(SpatialObject, uid("parcel")):
            raise RuntimeError(
                "An unfinished demo exists; inspect its jobs instead of silently reseeding"
            )
    inputs = fixture_inputs()
    output_directory.mkdir(parents=True, exist_ok=True)
    for name, content in inputs.items():
        (output_directory / name).write_bytes(content)
    with get_session() as db, db.begin():
        actor = uid("surveyor")
        db.add(AppUser(id=actor, role="surveyor", active=False))
        db.add(AppUser(id=uid("officer"), role="officer", active=False))
        db.flush()
        parcel = create_object(
            db,
            ObjectCreate(
                kind=Kind.PARCEL,
                label=LABEL + " — source pipeline parcel",
                is_synthetic=True,
            ),
            actor,
            uid("parcel"),
        )
        create_geometry(
            db,
            parcel.id,
            GeometryCreate(
                footprint=mapping(box(400000, 1440000, 400032, 1440032)),
                source_crs="EPSG:32644",
                metric_srid=32644,
                source_category=Source.MANUAL,
                method="Synthetic parcel coordinates; no real land record",
            ),
            actor,
        )
        sources = {}
        for name, content in inputs.items():
            intent = (
                "raster"
                if name.endswith(".tif")
                else "points" if name.endswith(".npy") else "plan"
            )
            source = register_processing_source(
                db, content, LABEL + " " + name, Source.MANUAL, True, actor, intent
            )
            if source.status != "READY":
                raise RuntimeError(source.error_message)
            sources[name] = source.id
        extraction = queue_processing(
            db,
            ProcessingRequest(
                kind="SUGGEST_BUILDINGS",
                object_id=parcel.id,
                dataset_id=sources["mask.tif"],
                mode="BINARY_MASK",
            ),
            actor,
        )
        extraction_id = extraction.id
    extracted = finish_job(extraction_id)
    if extracted["count"] != 1:
        raise RuntimeError("Synthetic mask should yield exactly one building")
    with get_session() as db, db.begin():
        suggestion = require(
            db, SpatialSuggestion, UUID(extracted["suggestion_ids"][0])
        )
        adoption = adopt_suggestion(
            db,
            suggestion.id,
            SuggestionAdopt(
                decision="ADOPTED_AS_DRAFT",
                reason="Synthetic operator confirms sample footprint; not a survey",
                geometry=GeometryCreate(
                    footprint=mapping(to_shape(suggestion.footprint)),
                    source_crs="EPSG:4326",
                    metric_srid=32644,
                    source_category=Source.DERIVED,
                    source_dataset_id=suggestion.dataset_id,
                    method="Synthetic binary-mask suggestion reviewed as draft",
                ),
            ),
            actor,
        )
        building_id = require(db, GeometryVersion, adoption.geometry_id).object_id
        height_job = queue_processing(
            db,
            ProcessingRequest(
                kind="ESTIMATE_HEIGHT",
                object_id=building_id,
                dataset_id=sources["dsm.tif"],
                secondary_dataset_id=sources["dem.tif"],
                vertical_reference="EPSG:4979",
            ),
            actor,
        )
        height_job_id = height_job.id
    height = finish_job(height_job_id)
    with get_session() as db, db.begin():
        observation = require(
            db, HeightObservation, UUID(height["height_observation_id"])
        )
        base = latest_geometry(db, building_id)
        create_geometry(
            db,
            building_id,
            GeometryCreate(
                footprint=mapping(to_shape(base.footprint)),
                source_crs="EPSG:4326",
                metric_srid=32644,
                z_min=observation.base_elevation,
                z_max=observation.base_elevation + observation.height_value,
                elevation_reference="EPSG:4979",
                height_estimated=True,
                source_category=Source.DEM_DSM,
                source_dataset_id=sources["dsm.tif"],
                method="Synthetic operator adopts measured DSM-DEM estimate; uncertainty remains marked",
            ),
            actor,
        )
        floors = create_floor_levels(
            db,
            FloorLevelsInput(
                building_id=building_id,
                dataset_id=sources["floor-plan.png"],
                levels=[
                    Level(
                        label="GF" if i == 0 else f"F{i}",
                        number=i,
                        elevation=10 + 3 * i,
                        upper_elevation=13 + 3 * i,
                        semantic_type="GROUND" if i == 0 else "UPPER",
                    )
                    for i in range(5)
                ],
                vertical_reference="EPSG:4979",
                source_category=Source.DERIVED,
                reason="Explicit synthetic plan levels; not inferred by dividing a building height",
            ),
            actor,
        )
        plan_jobs = []
        for floor in floors:
            job = queue_processing(
                db,
                ProcessingRequest(
                    kind="SUGGEST_UNITS",
                    object_id=UUID(floor["object_id"]),
                    dataset_id=sources["floor-plan.png"],
                    mode="ENCLOSED_ROOMS",
                    source_crs="EPSG:32644",
                    pixel_to_source=[1, 0, 400004, 0, -1, 1440024],
                    min_area_m2=0.5,
                ),
                actor,
            )
            plan_jobs.append(job.id)
        point_job = queue_processing(
            db,
            ProcessingRequest(
                kind="SUGGEST_LEVELS",
                object_id=building_id,
                dataset_id=sources["planes.npy"],
                mode="POINT_PLANES",
                source_crs="EPSG:32644",
                vertical_reference="EPSG:4979",
            ),
            actor,
        )
        point_job_id = point_job.id
    planes = finish_job(point_job_id)
    spaces = []
    for floor, job_id in zip(floors, plan_jobs, strict=True):
        result = finish_job(job_id)
        with get_session() as db, db.begin():
            level_geom = latest_geometry(db, UUID(floor["object_id"]))
            suggestions = [
                require(db, SpatialSuggestion, UUID(x))
                for x in result["suggestion_ids"]
            ]
            if len(suggestions) != 3:
                raise RuntimeError("Expected two unit regions and one corridor region")
            for index, suggestion in enumerate(suggestions):
                shared = index == 1
                adoption = adopt_suggestion(
                    db,
                    suggestion.id,
                    SuggestionAdopt(
                        decision="ADOPTED_AS_DRAFT",
                        target_kind="SHARED" if shared else "UNIT",
                        semantic_type="CORRIDOR" if shared else None,
                        reason="Synthetic operator classifies enclosed region; no ownership inferred",
                        geometry=GeometryCreate(
                            footprint=mapping(to_shape(suggestion.footprint)),
                            source_crs="EPSG:4326",
                            metric_srid=32644,
                            z_min=level_geom.z_min,
                            z_max=level_geom.z_max,
                            elevation_reference="EPSG:4979",
                            source_category=Source.DERIVED,
                            source_dataset_id=suggestion.dataset_id,
                            method="Synthetic aligned floor plan with explicit operator-confirmed vertical bounds",
                        ),
                    ),
                    actor,
                )
                geometry = require(db, GeometryVersion, adoption.geometry_id)
                spaces.append(geometry.object_id)
                attach_evidence(
                    db,
                    EvidenceCreate(
                        object_id=geometry.object_id,
                        dataset_id=suggestion.dataset_id,
                        description="Synthetic plan fixture, not an approved plan or title evidence",
                    ),
                    actor,
                )
    with get_session() as db, db.begin():
        # Independent basement footprint; deliberately not copied from building outline.
        basement = create_object(
            db,
            ObjectCreate(
                kind=Kind.UNDERGROUND,
                label=LABEL + " — basement",
                parent_id=uid("parcel"),
                semantic_type="UNDERGROUND_PARKING",
                is_synthetic=True,
            ),
            actor,
            uid("basement"),
        )
        create_geometry(
            db,
            basement.id,
            GeometryCreate(
                footprint=mapping(box(400006, 1440006, 400022, 1440022)),
                source_crs="EPSG:32644",
                metric_srid=32644,
                z_min=7,
                z_max=10,
                elevation_reference="EPSG:4979",
                source_category=Source.MANUAL,
                source_dataset_id=sources["floor-plan.png"],
                method="Independent synthetic basement plan, 3 metres below synthetic ground at elevation 10m",
            ),
            actor,
        )
        spaces.append(basement.id)
        validations = []
        for object_id in spaces:
            geometry = latest_geometry(db, object_id)
            job = ProcessingJob(
                kind="VALIDATE_PRISM", geometry_id=geometry.id, created_by=actor
            )
            db.add(job)
            db.flush()
            validations.append(job.id)
    for job_id in validations:
        result = finish_job(job_id)
        if not result["passed"]:
            raise RuntimeError("Synthetic nominal geometry failed validation")
    with get_session() as db, db.begin():
        for object_id in spaces:
            issue_identity(db, object_id, actor)
        export = queue_processing(
            db, ProcessingRequest(kind="EXPORT_ASSETS", object_id=uid("parcel")), actor
        )
        export_id = export.id
    exported = finish_job(export_id)
    with get_session() as db:
        bundle = require(db, AssetBundle, UUID(exported["asset_bundle_id"]))
        result = materialize(bundle, output_directory)
        result.update(
            {
                "building_height_m": height["height_value"],
                "floor_count": 5,
                "space_count": len(spaces),
                "suggested_plane_count": len(planes["suggested_planes"]),
                "models_executed": False,
                "accepted_geometry": False,
            }
        )
        (output_directory / "pipeline-report.json").write_text(
            json.dumps(result, indent=2)
        )
        return result


def materialize(bundle, output):
    output.mkdir(parents=True, exist_ok=True)
    for name, item in bundle.manifest.items():
        (output / name).write_bytes(read_bytes(item["key"]))
    return {
        "label": LABEL,
        "asset_bundle_id": str(bundle.id),
        "parcel_id": str(bundle.parcel_id),
        "files": list(bundle.manifest),
        "geometry_checks": bundle.validation,
        "status": "PROCESSED_NOT_LEGALLY_ACCEPTED",
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("output/phase2-demo"))
    args = parser.parse_args()
    print(json.dumps(demo(args.output), indent=2))
