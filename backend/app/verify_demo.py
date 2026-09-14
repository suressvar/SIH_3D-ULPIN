"""Read-only checks of the persistent synthetic database and its exported assets."""

import hashlib
import json
from pathlib import Path

import numpy as np
from geoalchemy2.shape import to_shape
from sqlalchemy import func, select

from app.db import get_session
from app.demo_pipeline import uid
from app.models import (
    GeometryVersion,
    ProcessingJob,
    SpatialObject,
    ULPINIdentity,
    ValidationIssue,
)
from app.pipeline_models import AssetBundle, IdentityVersion
from app.repositories import current_geometries
from app.services.exports import glb_document, validate_glb_geometry
from app.services.history import canonical_identity_code
from app.storage import read_bytes


def verify():
    with get_session() as db:
        parcel = db.get(SpatialObject, uid("parcel"))
        if parcel is None or not parcel.is_synthetic:
            raise ValueError("Expected the phase-two synthetic parcel")
        geometries = current_geometries(db, parcel.id)
        objects = list(
            db.scalars(
                select(SpatialObject).where(
                    (SpatialObject.id == parcel.id)
                    | (SpatialObject.parcel_id == parcel.id)
                )
            )
        )
        counts = {
            kind: sum(o.kind == kind for o in objects)
            for kind in sorted({o.kind for o in objects})
        }
        assert counts == {
            "PARCEL": 1,
            "BUILDING": 1,
            "FLOOR": 5,
            "UNIT": 10,
            "SHARED": 5,
            "UNDERGROUND": 1,
        }
        for geometry in geometries:
            assert to_shape(geometry.footprint).is_valid
            if geometry.shell is not None:
                assert db.scalar(
                    select(func.ST_IsClosed(GeometryVersion.shell)).where(
                        GeometryVersion.id == geometry.id
                    )
                )
        versions = list(
            db.scalars(
                select(IdentityVersion)
                .join(GeometryVersion)
                .where(GeometryVersion.object_id.in_([o.id for o in objects]))
            )
        )
        assert len(versions) == 16
        for version in versions:
            geom = db.get(GeometryVersion, version.geometry_id)
            assert geom is not None
            expected, _ = canonical_identity_code(
                parcel.existing_ulpin or f"PARCEL-UUID:{parcel.id}",
                geom.object_id,
                geom.geometry_hash,
            )
            assert version.canonical_code == expected
        assert (
            db.scalar(
                select(func.count())
                .select_from(ULPINIdentity)
                .where(ULPINIdentity.object_id.in_([o.id for o in objects]))
            )
            == 16
        )
        bundle = db.scalar(
            select(AssetBundle)
            .where(AssetBundle.parcel_id == parcel.id)
            .order_by(AssetBundle.created_at.desc())
        )
        assert bundle is not None
        contents = {}
        for name, asset in bundle.manifest.items():
            content = read_bytes(asset["key"])
            assert hashlib.sha256(content).hexdigest() == asset["sha256"]
            assert len(content) == asset["bytes"]
            contents[name] = content
            if name.endswith(".glb"):
                validate_glb_geometry(content)
        tileset = json.loads(contents["tileset.json"])
        assert tileset["asset"]["version"] == "1.1"
        root = tileset["root"]
        matrix = np.array(root["transform"]).reshape(4, 4).T
        assert np.linalg.det(matrix[:3, :3]) > 0
        np.testing.assert_allclose(
            matrix[:3, :3].T @ matrix[:3, :3], np.eye(3), atol=1e-10
        )
        assert len(root["children"]) == 16

        def bounds(box):
            center = np.array(box[:3])
            half = np.abs(np.array(box[3:]).reshape(3, 3)).sum(axis=0)
            return center - half, center + half

        root_lo, root_hi = bounds(root["boundingVolume"]["box"])
        for tile in root["children"]:
            uri = tile["content"]["uri"]
            assert uri in contents and Path(uri).name == uri
            md = tile["metadata"]["properties"]
            assert md["synthetic"] is True and tile["metadata"]["class"] == "property"
            document, _ = glb_document(contents[uri])
            assert len(document["nodes"]) == 1
            node = document["nodes"][0]
            assert not any(
                k in node for k in ("matrix", "translation", "rotation", "scale")
            )
            assert node["extras"]["object_id"] == md["objectId"]
            primitive = document["meshes"][node["mesh"]]["primitives"][0]
            accessor = document["accessors"][primitive["attributes"]["POSITION"]]
            # glTF y-up to 3D Tiles z-up, as specified by OGC 3D Tiles.
            lo, hi = accessor["min"], accessor["max"]
            local_lo = np.array([lo[0], -hi[2], lo[1]])
            local_hi = np.array([hi[0], -lo[2], hi[1]])
            tile_lo, tile_hi = bounds(tile["boundingVolume"]["box"])
            assert np.all(local_lo >= tile_lo) and np.all(local_hi <= tile_hi)
            assert np.all(tile_lo >= root_lo - 0.01) and np.all(
                tile_hi <= root_hi + 0.01
            )
        gltf_report = json.loads(contents["gltf-validation.json"])
        errors = db.scalar(
            select(func.count())
            .select_from(ValidationIssue)
            .join(ProcessingJob, ValidationIssue.job_id == ProcessingJob.id)
            .where(
                ProcessingJob.geometry_id.in_([g.id for g in geometries]),
                ValidationIssue.severity.in_(["ERROR", "CRITICAL"]),
            )
        )
        assert errors == 0
        return {
            "label": "Demo / Synthetic Dataset",
            "counts": counts,
            "geometry_versions_current": len(geometries),
            "deterministic_identity_versions": len(versions),
            "asset_files": len(contents),
            "glb_files": sum(n.endswith(".glb") for n in contents),
            "validation_errors": errors,
            "tiles_content_and_bounds_checked": True,
            "formal_ogc_schema_validation": False,
            "khronos_report": gltf_report,
            "legal_acceptance": False,
        }


if __name__ == "__main__":
    report = verify()
    output = Path("output/phase2-demo/verification.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps({k: v for k, v in report.items() if k != "khronos_report"}, indent=2)
    )
