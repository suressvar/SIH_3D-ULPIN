"""Real Blender GLBs + 3D Tiles 1.1, validated before publication."""

import hashlib
import json
import math
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from geoalchemy2.shape import to_shape
from pyproj import Transformer
from shapely.geometry import mapping
from sqlalchemy import select, text

from app.config import get_settings
from app.mesh import prism_mesh, validate_mesh
from app.models import SpatialObject, ULPINIdentity
from app.pipeline_models import AssetBundle, IdentityVersion
from app.pipeline_schemas import ProcessingRequest
from app.repositories import audit, current_geometries, require
from app.services.validation import snapshot
from app.storage import put_bytes


def export_tools():
    settings = get_settings()
    blender = settings.blender_executable or shutil.which("blender")
    node = settings.node_executable or shutil.which("node")
    verify = (
        Path(settings.gltf_verify_script)
        if settings.gltf_verify_script
        else Path(__file__).resolve().parents[3] / "tools/gltf/verify.mjs"
    )
    return blender, node, verify


def export_available():
    blender, node, verify = export_tools()
    return bool(
        blender
        and Path(blender).is_file()
        and node
        and verify.is_file()
        and (verify.parent / "node_modules/gltf-validator").is_dir()
    )


def glb_document(content: bytes):
    magic, version, length = struct.unpack_from("<III", content)
    if magic != 0x46546C67 or version != 2 or length != len(content):
        raise ValueError("Invalid GLB header")
    json_length, json_type = struct.unpack_from("<II", content, 12)
    if json_type != 0x4E4F534A:
        raise ValueError("GLB has no JSON chunk")
    document = json.loads(content[20 : 20 + json_length])
    offset = 20 + json_length
    binary = b""
    if offset < len(content):
        size, kind = struct.unpack_from("<II", content, offset)
        if kind != 0x004E4942:
            raise ValueError("Unexpected GLB buffer chunk")
        binary = content[offset + 8 : offset + 8 + size]
    return document, binary


def validate_glb_geometry(content):
    document, binary = glb_document(content)

    def accessor(index):
        item = document["accessors"][index]
        view = document["bufferViews"][item["bufferView"]]
        types: dict[int, np.dtype] = {
            5126: np.dtype("<f4"),
            5125: np.dtype("<u4"),
            5123: np.dtype("<u2"),
            5121: np.dtype("u1"),
        }
        width = {"SCALAR": 1, "VEC3": 3}[item["type"]]
        dtype = types[item["componentType"]]
        offset = view.get("byteOffset", 0) + item.get("byteOffset", 0)
        stride = view.get("byteStride", width * dtype.itemsize)
        return np.ndarray(
            (item["count"], width),
            dtype=dtype,
            buffer=binary,
            offset=offset,
            strides=(stride, dtype.itemsize),
        ).copy()

    results = []
    for mesh in document.get("meshes", []):
        for primitive in mesh["primitives"]:
            if primitive.get("mode", 4) != 4:
                raise ValueError("Only triangle primitives are supported")
            vertices = accessor(primitive["attributes"]["POSITION"]).astype("float64")
            faces = accessor(primitive["indices"]).reshape(-1, 3)
            # glTF duplicates vertices for hard normals. Weld identical positions for topology checking.
            unique, inverse = np.unique(vertices, axis=0, return_inverse=True)
            results.append(validate_mesh(unique, inverse[faces]))
    if not results:
        raise ValueError("GLB contains no triangle meshes")
    return {"mesh_count": len(results), "meshes": results}


def enu_frame(lon, lat, alt):
    longitude, latitude = math.radians(lon), math.radians(lat)
    rotation = np.array(
        [
            [
                -math.sin(longitude),
                -math.sin(latitude) * math.cos(longitude),
                math.cos(latitude) * math.cos(longitude),
            ],
            [
                math.cos(longitude),
                -math.sin(latitude) * math.sin(longitude),
                math.cos(latitude) * math.sin(longitude),
            ],
            [0, math.cos(latitude), math.sin(latitude)],
        ]
    )
    origin = np.array(
        Transformer.from_crs(4979, 4978, always_xy=True).transform(lon, lat, alt)
    )
    matrix = np.eye(4)
    matrix[:3, :3] = rotation
    matrix[:3, 3] = origin
    return origin, rotation, matrix.T.reshape(-1).tolist()


def box_volume(vertices):
    lo, hi = vertices.min(axis=0), vertices.max(axis=0)
    middle = (lo + hi) / 2
    half = np.maximum((hi - lo) / 2, 0.001) + 0.005
    return [*middle, half[0], 0, 0, 0, half[1], 0, 0, 0, half[2]]


def build_assets(db, job):
    db.execute(text("SELECT pg_advisory_xact_lock(26011002)"))
    request = ProcessingRequest.model_validate(job.parameters)
    parcel = require(db, SpatialObject, request.object_id)
    if parcel.kind != "PARCEL":
        raise ValueError("Export targets a parcel")
    if not export_available():
        raise ValueError(
            "Asset generation unavailable: configure Blender, Node.js, glTF Transform and Khronos validator"
        )
    geometries = current_geometries(db, parcel.id)
    states = snapshot(db, parcel.id)
    key = hashlib.sha256(
        json.dumps(
            {
                "snapshot": states,
                "placement": request.vertical_offset_to_ellipsoid,
                "exporter": "BLENDER_PRISM_V6_EXTERIOR",
                "identities": sorted(
                    (str(v.geometry_id), v.canonical_code)
                    for v in db.scalars(
                        select(IdentityVersion).where(
                            IdentityVersion.geometry_id.in_([g.id for g in geometries])
                        )
                    )
                ),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    cached = db.scalar(select(AssetBundle).where(AssetBundle.cache_key == key))
    if cached:
        job.output_assets = [
            {"asset_bundle_id": str(cached.id), "files": list(cached.manifest)}
        ]
        return {
            "asset_bundle_id": str(cached.id),
            "cached": True,
            "manifest": cached.manifest,
        }
    root_geom = next(g for g in geometries if g.object_id == parcel.id)
    anchor = to_shape(root_geom.footprint).centroid
    origin, rotation, tiles_transform = enu_frame(anchor.x, anchor.y, 0)
    ecef = Transformer.from_crs(4979, 4978, always_xy=True)
    objects = []
    geojson = []
    for geom in geometries:
        obj = require(db, SpatialObject, geom.object_id)
        identity = db.scalar(
            select(ULPINIdentity).where(ULPINIdentity.object_id == obj.id)
        )
        identity_version = db.scalar(
            select(IdentityVersion).where(IdentityVersion.geometry_id == geom.id)
        )
        props = {
            "object_id": str(obj.id),
            "label": obj.label,
            "kind": obj.kind,
            "parent_id": str(obj.parent_id) if obj.parent_id else None,
            "source": geom.source_category,
            "is_synthetic": obj.is_synthetic,
            "geometry_version": geom.version,
            "geometry_hash": geom.geometry_hash,
            "proposed_3d_ulpin": (
                identity_version.canonical_code if identity_version else None
            ),
            "persistent_identity": identity.identifier if identity else None,
            "identity_label": "Proposed 3D ULPIN",
            "vertical_reference": geom.elevation_reference,
            "z_min": geom.z_min,
            "z_max": geom.z_max,
            "height_estimated": geom.height_estimated,
        }
        geojson.append(
            {
                "type": "Feature",
                "id": str(obj.id),
                "properties": props,
                "geometry": mapping(to_shape(geom.footprint)),
            }
        )
        if obj.kind in {"PARCEL", "BUILDING", "FLOOR"}:
            continue
        if geom.z_min is None:
            raise ValueError(
                f"{obj.label} has no vertical extent; export cannot invent its height"
            )
        offset = (
            0
            if geom.elevation_reference == "EPSG:4979"
            else request.vertical_offset_to_ellipsoid
        )
        if offset is None:
            raise ValueError(
                "3D Tiles placement requires EPSG:4979 heights or an explicit visualization-only offset to ellipsoidal height"
            )
        vertices, faces = prism_mesh(
            to_shape(geom.metric_footprint), geom.z_min, geom.z_max
        )
        to_geo = Transformer.from_crs(geom.metric_srid, 4326, always_xy=True)
        lon, lat = to_geo.transform(vertices[:, 0], vertices[:, 1])
        x, y, z = ecef.transform(lon, lat, vertices[:, 2] + offset)
        local = (np.column_stack([x, y, z]) - origin) @ rotation
        validate_mesh(local, faces)
        color = (
            [0.12, 0.52, 0.51, 1]
            if obj.kind == "SHARED"
            else (
                [0.64, 0.68, 0.73, 1]
                if obj.kind == "UNDERGROUND"
                else [0.82, 0.84, 0.86, 1]
            )
        )
        objects.append(
            {
                "id": str(obj.id),
                "label": obj.label,
                "kind": obj.kind,
                "vertices": local.tolist(),
                "faces": faces.tolist(),
                "color": color,
                "metadata": {k: v for k, v in props.items() if v is not None},
                "box": box_volume(local),
            }
        )
    if not objects:
        raise ValueError("No bounded property spaces to export")
    appearance = None
    # Architectural dressing is available only for a complete synthetic building with a roof.
    spatial_objects = list(
        db.scalars(select(SpatialObject).where(SpatialObject.parcel_id == parcel.id))
    )
    buildings = [o for o in spatial_objects if o.kind == "BUILDING"]
    roof_present = any(
        o.kind == "FLOOR" and o.semantic_type == "ROOF" for o in spatial_objects
    )
    if parcel.is_synthetic and len(buildings) == 1 and roof_present:
        building = buildings[0]
        building_geom = next(g for g in geometries if g.object_id == building.id)
        levels = sorted(
            [
                (g.z_min, g.z_max)
                for g in geometries
                if any(
                    o.id == g.object_id
                    and o.kind == "FLOOR"
                    and o.semantic_type != "ROOF"
                    and o.parent_id == building.id
                    for o in spatial_objects
                )
            ]
        )
        if (
            building_geom.elevation_reference == "EPSG:4979"
            and levels
            and all(lo is not None and hi is not None for lo, hi in levels)
        ):

            def local_bounds(geometry):
                coordinates = np.asarray(to_shape(geometry.footprint).exterior.coords)
                xx, yy, zz = ecef.transform(
                    coordinates[:, 0], coordinates[:, 1], np.zeros(len(coordinates))
                )
                local = (np.column_stack([xx, yy, zz]) - origin) @ rotation
                return [
                    float(local[:, 0].min()),
                    float(local[:, 1].min()),
                    float(local[:, 0].max()),
                    float(local[:, 1].max()),
                ]

            bounds = local_bounds(building_geom)
            appearance = {
                "synthetic": True,
                "building_id": str(building.id),
                "bounds": [
                    *bounds[:2],
                    building_geom.z_min,
                    *bounds[2:],
                    building_geom.z_max,
                ],
                "parcel_bounds": local_bounds(root_geom),
                "levels": levels,
                "label": "Illustrative synthetic exterior and surroundings; not surveyed architecture or cadastral boundaries",
            }
    blender, node, verify = export_tools()
    with tempfile.TemporaryDirectory(prefix="astra-export-") as directory:
        work = Path(directory)
        (work / "input.json").write_text(
            json.dumps({"objects": objects, "appearance": appearance}), encoding="utf-8"
        )
        process = subprocess.run(
            [
                blender,
                "--background",
                "--factory-startup",
                "--python",
                str(Path(__file__).resolve().parents[1] / "blender_export.py"),
                "--",
                str(work / "input.json"),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if process.returncode or "ASTRA_EXPORT_COMPLETE" not in process.stdout:
            raise ValueError("Blender export failed: " + process.stderr[-1000:])
        optimized = subprocess.run(
            [node, str(verify), str(work)], capture_output=True, text=True, timeout=120
        )
        if optimized.returncode:
            raise ValueError("glTF verification failed: " + optimized.stderr[-1000:])
        geometrical_checks = {}
        for file in sorted(work.glob("*.glb")):
            geometrical_checks[file.name] = validate_glb_geometry(file.read_bytes())
        combined = np.vstack([np.asarray(item["vertices"]) for item in objects])
        classes = {
            "property": {
                "properties": {
                    "objectId": {"type": "STRING"},
                    "parentId": {"type": "STRING"},
                    "kind": {"type": "STRING"},
                    "synthetic": {"type": "BOOLEAN"},
                    "source": {"type": "STRING"},
                    "geometryVersion": {"type": "SCALAR", "componentType": "UINT32"},
                }
            }
        }
        children = []
        for item in objects:
            md = item["metadata"]
            children.append(
                {
                    "boundingVolume": {"box": item["box"]},
                    "geometricError": 0,
                    "content": {"uri": item["id"] + ".glb"},
                    "metadata": {
                        "class": "property",
                        "properties": {
                            "objectId": item["id"],
                            "parentId": md["parent_id"],
                            "kind": item["kind"],
                            "synthetic": md["is_synthetic"],
                            "source": md["source"],
                            "geometryVersion": md["geometry_version"],
                        },
                    },
                }
            )
        # The empty root represents an omitted scene. A zero tileset error causes
        # Cesium to skip traversal entirely; leaves alone have zero error.
        omitted_scene_error = float(np.linalg.norm(np.ptp(combined, axis=0)))
        tileset = {
            "asset": {
                "version": "1.1",
                "extras": {
                    "prototype": "Astra VI",
                    "label": (
                        "Demo / Synthetic Dataset"
                        if parcel.is_synthetic
                        else "Prototype mapping"
                    ),
                    "vertical_offset_to_ellipsoid": request.vertical_offset_to_ellipsoid,
                },
            },
            "geometricError": omitted_scene_error,
            "schema": {"id": "astra_property_schema", "classes": classes},
            "root": {
                "boundingVolume": {"box": box_volume(combined)},
                "transform": tiles_transform,
                "geometricError": omitted_scene_error,
                "refine": "ADD",
                "children": children,
            },
        }
        (work / "tileset.json").write_text(json.dumps(tileset, indent=2))
        (work / "properties.geojson").write_text(
            json.dumps({"type": "FeatureCollection", "features": geojson}, indent=2)
        )
        manifest = {}
        for file in sorted(work.iterdir()):
            if file.name == "input.json":
                continue
            content = file.read_bytes()
            if len(content) > get_settings().max_upload_bytes:
                raise ValueError(
                    "Generated asset exceeds configured storage transfer limit"
                )
            object_key, digest = put_bytes(content)
            manifest[file.name] = {
                "key": object_key,
                "sha256": digest,
                "bytes": len(content),
            }
        # Preserve only the complete, verified bundle. Unpublished storage orphans can be collected later.
        bundle = AssetBundle(
            parcel_id=parcel.id,
            job_id=job.id,
            cache_key=key,
            snapshot=states,
            placement={
                "anchor_lon": anchor.x,
                "anchor_lat": anchor.y,
                "frame": "WGS84 ECEF / local ENU",
                "vertical_offset_to_ellipsoid": request.vertical_offset_to_ellipsoid,
            },
            manifest=manifest,
            validation={
                "khronos_errors": 0,
                "geometry": geometrical_checks,
                "tileset": "1.1 schema with per-tile metadata; bounding boxes derived from all exported vertices",
                "lod": "single detail level, per-object streaming",
            },
            actor_id=job.created_by,
        )
        db.add(bundle)
        audit(
            db,
            job.created_by,
            "ASSET_BUNDLE_GENERATED",
            bundle,
            {"files": len(manifest)},
        )
        job.output_assets = [
            {"asset_bundle_id": str(bundle.id), "files": list(manifest)}
        ]
        return {
            "asset_bundle_id": str(bundle.id),
            "cached": False,
            "manifest": manifest,
        }
