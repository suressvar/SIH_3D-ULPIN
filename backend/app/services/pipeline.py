import hashlib
import io
from uuid import NAMESPACE_URL, UUID, uuid5

import cv2
import numpy as np
from fastapi import HTTPException
from geoalchemy2.shape import from_shape, to_shape
from rasterio.io import MemoryFile
from rasterio.transform import Affine
from shapely.geometry import mapping, shape
from sqlalchemy import select, text

from app.assistance import (
    enclosed_plan_regions,
    infer_building_probability,
    polygonize_probability,
    suggest_horizontal_levels,
)
from app.config import get_settings
from app.models import Kind, ProcessingJob, Source, SourceDataset, SpatialObject
from app.pipeline_models import HeightObservation, SpatialSuggestion, SuggestionDecision
from app.pipeline_schemas import (
    FloorLevelsInput,
    HeightInput,
    ProcessingRequest,
    SuggestionAdopt,
)
from app.raster_processing import estimate_height, inspect_raster
from app.repositories import audit, latest_geometry, require
from app.schemas import GeometryCreate, ObjectCreate
from app.services.objects import create_geometry, create_object
from app.storage import put_bytes, read_bytes


def source_bytes(db, dataset_id):
    source = require(db, SourceDataset, dataset_id)
    if source.status not in {"READY", "EVIDENCE_ONLY"}:
        raise ValueError("Dataset is not ready for processing")
    content = read_bytes(source.object_key)
    if hashlib.sha256(content).hexdigest() != source.sha256:
        raise ValueError("Source checksum mismatch")
    return source, content


def register_processing_source(
    db, content, filename, category, synthetic, actor, intent
):
    key, digest = put_bytes(content)
    source = SourceDataset(
        filename=filename[:255],
        media_type="application/octet-stream",
        source_category=category,
        object_key=key,
        sha256=digest,
        byte_size=len(content),
        status="READY",
        inspection={"intent": intent},
        is_synthetic=synthetic,
        created_by=actor,
    )
    try:
        if intent == "raster":
            source.inspection = {**source.inspection, **inspect_raster(content)}
            source.media_type = "image/tiff"
        elif intent == "points":
            points = np.load(io.BytesIO(content), allow_pickle=False)
            if (
                points.ndim != 2
                or points.shape[1] != 3
                or not 3 <= len(points) <= get_settings().max_point_count
                or not np.isfinite(points).all()
            ):
                raise ValueError(
                    "Point source must be a finite N x 3 NumPy array; explicit source CRS required at processing"
                )
            source.inspection = {
                **source.inspection,
                "format": "NPY",
                "point_count": len(points),
            }
        elif intent == "plan":
            image = cv2.imdecode(
                np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_GRAYSCALE
            )
            if image is None or image.size > get_settings().max_raster_pixels:
                raise ValueError("Plan source must be a decodable PNG or JPEG")
            source.inspection = {
                **source.inspection,
                "format": "IMAGE",
                "dimensions": list(image.shape),
                "alignment": "REQUIRED",
            }
        else:
            raise ValueError("Unknown processing input type")
    except Exception as exc:
        source.status = "REJECTED"
        source.error_message = str(exc)[:1000]
    db.add(source)
    audit(
        db,
        actor,
        "PROCESSING_SOURCE_REGISTERED",
        source,
        {"status": source.status, "is_synthetic": synthetic},
    )
    return source


def queue_processing(db, request: ProcessingRequest, actor):
    obj = require(db, SpatialObject, request.object_id)
    if obj.lifecycle != "ACTIVE":
        raise HTTPException(409, "Cannot process a superseded object")
    for dataset_id in [request.dataset_id, request.secondary_dataset_id]:
        if dataset_id:
            dataset = require(db, SourceDataset, dataset_id)
            if (
                dataset.status not in {"READY", "EVIDENCE_ONLY"}
                or dataset.is_synthetic != obj.is_synthetic
            ):
                raise HTTPException(
                    422,
                    "Dataset status or synthetic designation does not match the object",
                )
    job = ProcessingJob(
        kind=request.kind,
        input_dataset_id=request.dataset_id,
        parameters=request.model_dump(mode="json"),
        created_by=actor,
    )
    db.add(job)
    audit(db, actor, "JOB_QUEUED", job)
    return job


def process_assistance(db, job):
    request = ProcessingRequest.model_validate(job.parameters)
    obj = require(db, SpatialObject, request.object_id)
    geom = latest_geometry(db, obj.id)
    if geom is None:
        raise ValueError("Parent object has no reference footprint")
    if request.dataset_id is None:
        raise ValueError("Missing source")
    source, content = source_bytes(db, request.dataset_id)
    if source.is_synthetic != obj.is_synthetic:
        raise ValueError("Source designation differs from parent")
    if request.kind == "ESTIMATE_HEIGHT":
        if not request.vertical_reference:
            raise ValueError("A vertical reference is required")
        if obj.kind != Kind.BUILDING:
            raise ValueError("Height estimation targets a building")
        other, dem = source_bytes(db, request.secondary_dataset_id)
        result = estimate_height(
            content, dem, mapping(to_shape(geom.footprint)), request.vertical_reference
        )
        observation = HeightObservation(
            object_id=obj.id,
            dataset_id=source.id,
            secondary_dataset_id=other.id,
            actor_id=job.created_by,
            **result,
        )
        db.add(observation)
        audit(db, job.created_by, "HEIGHT_ESTIMATED", observation)
        return {
            "height_observation_id": str(observation.id),
            **result,
            "geometry_changed": False,
        }
    if request.kind == "SUGGEST_LEVELS":
        points = np.load(io.BytesIO(content), allow_pickle=False)
        if not request.source_crs or not request.vertical_reference:
            raise ValueError(
                "Point processing requires explicit horizontal CRS and vertical reference"
            )
        from pyproj import CRS

        crs = CRS.from_user_input(request.source_crs)
        if not crs.is_projected or any(
            abs(x.unit_conversion_factor - 1) > 1e-9 for x in crs.axis_info[:2]
        ):
            raise ValueError("Point source CRS must be projected in metres")
        return {
            "suggested_planes": suggest_horizontal_levels(points),
            "source_dataset_id": str(source.id),
            "vertical_reference": request.vertical_reference,
            "is_synthetic": source.is_synthetic,
            "geometry_changed": False,
        }
    if request.kind == "SUGGEST_BUILDINGS":
        if obj.kind != Kind.PARCEL:
            raise ValueError("Building suggestions require a parent parcel")
        inspect_raster(content)
        with MemoryFile(content) as mem, mem.open() as raster:
            if request.mode == "BINARY_MASK":
                if not source.is_synthetic:
                    raise ValueError(
                        "Demo binary mask mode requires an explicitly synthetic source"
                    )
                probability = raster.read(1).astype("float32")
                if probability.max() > 1:
                    probability /= 255
                category = "DERIVED"
            else:
                if raster.count < 3:
                    raise ValueError("Model extraction requires RGB imagery")
                rgb = np.moveaxis(raster.read([1, 2, 3]), 0, -1)
                probability = infer_building_probability(rgb)
                category = "AI_ESTIMATE"
            suggestions = polygonize_probability(
                probability,
                raster.transform,
                raster.crs.to_string(),
                request.threshold,
                request.min_area_m2,
                geom.metric_srid,
            )
            kind = "BUILDING"
    elif request.kind == "SUGGEST_UNITS":
        if (
            obj.kind != Kind.FLOOR
            or request.pixel_to_source is None
            or not request.source_crs
        ):
            raise ValueError(
                "Unit suggestions need a parent floor and explicit six-value image-to-source affine transform/CRS"
            )
        affine = Affine(*request.pixel_to_source)
        if abs(affine.determinant) < 1e-12:
            raise ValueError("Plan alignment is singular")
        image = cv2.imdecode(
            np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_GRAYSCALE
        )
        if image is None or image.size > get_settings().max_raster_pixels:
            raise ValueError("Unreadable plan")
        suggestions = enclosed_plan_regions(
            image, affine, request.source_crs, request.min_area_m2, geom.metric_srid
        )
        category = "DERIVED"
        kind = "UNIT"
    else:
        raise ValueError("Unsupported assistive operation")
    ids = []
    for index, value in enumerate(suggestions):
        polygon = shape(value["footprint"])
        if not to_shape(geom.footprint).intersects(polygon):
            continue
        suggestion = SpatialSuggestion(
            parent_id=obj.id,
            dataset_id=source.id,
            job_id=job.id,
            kind=kind,
            label=f"Suggested {kind.lower()} {index+1}",
            footprint=from_shape(polygon, srid=4326),
            source_category=category,
            confidence=None if request.mode == "BINARY_MASK" else value["confidence"],
            method=value["method"],
            parameters={
                "request": request.model_dump(mode="json"),
                "note": (
                    "Synthetic sample, not inference"
                    if request.mode == "BINARY_MASK"
                    else "Human verification required"
                ),
            },
            is_synthetic=source.is_synthetic,
        )
        db.add(suggestion)
        audit(db, job.created_by, "SPATIAL_SUGGESTION_CREATED", suggestion)
        ids.append(str(suggestion.id))
    return {
        "suggestion_ids": ids,
        "count": len(ids),
        "geometry_changed": False,
        "is_synthetic": source.is_synthetic,
    }


def adopt_suggestion(db, suggestion_id: UUID, request: SuggestionAdopt, actor):
    db.execute(text("SELECT pg_advisory_xact_lock(26011002)"))
    suggestion = require(db, SpatialSuggestion, suggestion_id)
    if db.scalar(
        select(SuggestionDecision).where(
            SuggestionDecision.suggestion_id == suggestion.id
        )
    ):
        raise HTTPException(409, "Suggestion already has a human decision")
    geometry = None
    if request.decision == "ADOPTED_AS_DRAFT":
        payload = request.geometry
        if payload is None:
            raise HTTPException(422, "Geometry required")
        # Preserve the suggestion as evidence even when the human corrects its boundary.
        if payload.source_dataset_id != suggestion.dataset_id:
            raise HTTPException(
                422, "Adoption must reference the suggestion's source dataset"
            )
        if payload.source_category not in {
            Source.MANUAL,
            Source.DERIVED,
            Source.AI_ESTIMATE,
        }:
            raise HTTPException(
                422, "Adoption does not confer survey or plan verification"
            )
        if request.target_kind and not (
            suggestion.kind == "UNIT" and request.target_kind in {"UNIT", "SHARED"}
        ):
            raise HTTPException(
                422, "Only a unit suggestion can be classified as a shared space"
            )
        obj = create_object(
            db,
            ObjectCreate(
                kind=Kind(request.target_kind or suggestion.kind),
                label=suggestion.label,
                parent_id=suggestion.parent_id,
                is_synthetic=suggestion.is_synthetic,
                semantic_type=request.semantic_type,
            ),
            actor,
            uuid5(
                NAMESPACE_URL,
                f"astra-suggestion:{suggestion.parent_id}:{suggestion.kind}:{suggestion.label}",
            ),
        )
        geometry = create_geometry(db, obj.id, payload, actor)
    decision = SuggestionDecision(
        suggestion_id=suggestion.id,
        geometry_id=geometry.id if geometry else None,
        decision=request.decision,
        reason=request.reason,
        actor_id=actor,
    )
    db.add(decision)
    audit(
        db,
        actor,
        "SUGGESTION_DECIDED",
        decision,
        {"status": "DRAFT" if geometry else "REJECTED"},
    )
    return decision


def record_height(db, request: HeightInput, actor):
    obj = require(db, SpatialObject, request.object_id)
    source = require(db, SourceDataset, request.dataset_id)
    if (
        obj.kind != Kind.BUILDING
        or source.status not in {"READY", "EVIDENCE_ONLY"}
        or obj.is_synthetic != source.is_synthetic
    ):
        raise HTTPException(422, "Height source must match a building and be usable")
    observation = HeightObservation(
        **request.model_dump(exclude={"reason"}),
        actor_id=actor,
        details={"method": request.reason},
    )
    db.add(observation)
    audit(db, actor, "HEIGHT_RECORDED", observation)
    return observation


def create_floor_levels(db, request: FloorLevelsInput, actor):
    db.execute(text("SELECT pg_advisory_xact_lock(26011002)"))
    building = require(db, SpatialObject, request.building_id)
    geom = latest_geometry(db, building.id)
    if building.kind != Kind.BUILDING or geom is None or geom.z_min is None:
        raise HTTPException(422, "Building requires an explicit mapped vertical extent")
    if request.vertical_reference != geom.elevation_reference:
        raise HTTPException(422, "Floor and building vertical references differ")
    existing = list(
        db.scalars(
            select(SpatialObject).where(
                SpatialObject.parent_id == building.id,
                SpatialObject.kind == "FLOOR",
                SpatialObject.lifecycle == "ACTIVE",
            )
        )
    )
    if {x.floor_number for x in existing} & {x.number for x in request.levels}:
        raise HTTPException(409, "A requested floor number already exists")
    outputs = []
    for level in request.levels:
        if level.elevation < geom.z_min or level.upper_elevation > geom.z_max:
            raise HTTPException(422, "Floor elevations exceed the building volume")
        for floor in existing:
            previous = latest_geometry(db, floor.id)
            if (
                previous
                and previous.z_min is not None
                and min(previous.z_max, level.upper_elevation)
                > max(previous.z_min, level.elevation)
            ):
                raise HTTPException(422, "Requested level overlaps an existing floor")
        obj = create_object(
            db,
            ObjectCreate(
                kind=Kind.FLOOR,
                label=level.label,
                parent_id=building.id,
                floor_number=level.number,
                semantic_type=level.semantic_type,
                is_synthetic=building.is_synthetic,
            ),
            actor,
            uuid5(NAMESPACE_URL, f"astra-floor:{building.id}:{level.number}"),
        )
        geometry = create_geometry(
            db,
            obj.id,
            GeometryCreate(
                footprint=mapping(to_shape(geom.footprint)),
                source_crs="EPSG:4326",
                metric_srid=geom.metric_srid,
                z_min=level.elevation,
                z_max=level.upper_elevation,
                elevation_reference=request.vertical_reference,
                source_category=request.source_category,
                source_dataset_id=request.dataset_id,
                method=request.reason,
            ),
            actor,
        )
        outputs.append({"object_id": str(obj.id), "geometry_id": str(geometry.id)})
    return outputs
