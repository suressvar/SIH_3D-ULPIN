import json
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Kind, ProcessingJob, SourceDataset
from app.repositories import audit, require
from app.schemas import GeometryCreate, ObjectCreate
from app.services.objects import create_geometry, create_object
from app.spatial import polygon_from_geojson, project_footprint
from app.storage import put_bytes, read_bytes


def register_dataset(
    db: Session,
    content: bytes,
    filename: str,
    source_category: str,
    actor: UUID,
    is_synthetic: bool,
    intent: str,
    source_crs: str | None,
    metric_srid: int | None,
):
    key, digest = put_bytes(content)
    evidence_format = (
        "application/pdf"
        if content.startswith(b"%PDF-")
        else (
            "image/png"
            if content.startswith(b"\x89PNG\r\n\x1a\n")
            else "image/jpeg" if content.startswith(b"\xff\xd8\xff") else None
        )
    )
    status = "UPLOADED"
    error = None
    if intent == "evidence":
        status = "EVIDENCE_ONLY" if evidence_format else "REJECTED"
        error = (
            None
            if evidence_format
            else "Evidence supports PDF, PNG or JPEG signatures in this phase"
        )
    dataset = SourceDataset(
        filename=filename[:255],
        media_type=evidence_format or "application/octet-stream",
        source_category=source_category,
        object_key=key,
        sha256=digest,
        byte_size=len(content),
        status=status,
        error_message=error,
        is_synthetic=is_synthetic,
        created_by=actor,
        inspection={
            "intent": intent,
            "declared_source_crs": source_crs,
            "metric_srid": metric_srid,
        },
    )
    db.add(dataset)
    audit(
        db, actor, "DATASET_REGISTERED", dataset, {"sha256": digest, "status": status}
    )
    if intent == "parcel":
        job = ProcessingJob(
            kind="INGEST_GEOJSON", input_dataset_id=dataset.id, created_by=actor
        )
        db.add(job)
        audit(db, actor, "JOB_QUEUED", job)
    return dataset


def inspect_geojson(content: bytes, source_crs: str | None, metric_srid: int | None):
    if metric_srid is None:
        raise ValueError(
            "A projected metric_srid is required; no coordinate system is guessed"
        )
    try:
        document = json.loads(content)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Expected UTF-8 GeoJSON; source retained") from exc
    if not isinstance(document, dict):
        raise ValueError("GeoJSON must be an object")
    if "crs" in document:
        raise ValueError(
            "Legacy embedded GeoJSON CRS is unsupported; provide explicit source_crs after checking the source"
        )
    crs = source_crs or "EPSG:4326"
    if document.get("type") == "FeatureCollection":
        features = document.get("features")
    elif document.get("type") == "Feature":
        features = [document]
    else:
        raise ValueError("Provide a Feature or FeatureCollection of Polygon parcels")
    if not isinstance(features, list) or not 1 <= len(features) <= 100:
        raise ValueError("Upload must contain between 1 and 100 parcel features")
    normalized = []
    for i, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError(f"Feature {i}: malformed feature")
        try:
            polygon_from_geojson(feature["geometry"])
            geo, _, transform_info = project_footprint(
                feature["geometry"], crs, metric_srid
            )
        except (ValueError, KeyError, RuntimeError) as exc:
            raise ValueError(f"Feature {i}: {exc}") from exc
        props = feature.get("properties") or {}
        if not isinstance(props, dict):
            raise ValueError(f"Feature {i}: properties must be an object")
        if props.get("existing_ulpin") is not None:
            ObjectCreate(
                kind=Kind.PARCEL,
                label="validation",
                existing_ulpin=props["existing_ulpin"],
            )
        normalized.append(
            (
                feature["geometry"],
                str(props.get("label", f"Imported parcel {i + 1}"))[:160],
                props.get("existing_ulpin"),
                list(geo.bounds),
                transform_info,
            )
        )
    return crs, normalized


def ingest_geojson(db: Session, job: ProcessingJob):
    if job.input_dataset_id is None:
        raise ValueError("Ingestion job is missing its source")
    dataset = require(db, SourceDataset, job.input_dataset_id)
    content = read_bytes(dataset.object_key)
    import hashlib

    if hashlib.sha256(content).hexdigest() != dataset.sha256:
        raise ValueError("Stored source checksum mismatch")
    crs, features = inspect_geojson(
        content,
        dataset.inspection.get("declared_source_crs"),
        dataset.inspection.get("metric_srid"),
    )
    dataset.status = "READY"
    dataset.media_type = "application/geo+json"
    dataset.inspection = {
        **dataset.inspection,
        "detected_format": "GeoJSON",
        "source_crs": crs,
        "feature_count": len(features),
        "extents_epsg4326": [f[3] for f in features],
    }
    outputs = []
    for geometry, label, ulpin, _, _ in features:
        obj = create_object(
            db,
            ObjectCreate(
                kind=Kind.PARCEL,
                label=label,
                existing_ulpin=ulpin,
                is_synthetic=dataset.is_synthetic,
            ),
            job.created_by,
        )
        geom = create_geometry(
            db,
            obj.id,
            GeometryCreate(
                footprint=geometry,
                source_crs=crs,
                metric_srid=dataset.inspection["metric_srid"],
                source_category=dataset.source_category,
                source_dataset_id=dataset.id,
                method="Validated GeoJSON polygon import; no height inference",
            ),
            job.created_by,
        )
        outputs.append({"object_id": str(obj.id), "geometry_id": str(geom.id)})
    audit(
        db, job.created_by, "DATASET_INGESTED", dataset, {"feature_count": len(outputs)}
    )
    return {"objects": outputs, "source_crs": crs}
