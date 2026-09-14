import io
from uuid import UUID

import cv2
import numpy as np
import pytest
from pyproj import Transformer
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box, mapping
from shapely.ops import transform

from app.assistance import (
    enclosed_plan_regions,
    polygonize_probability,
    suggest_horizontal_levels,
)
from app.demo_pipeline import fixture_inputs, geotiff
from app.mesh import prism_mesh, validate_mesh
from app.raster_processing import estimate_height
from app.services.exports import enu_frame
from app.services.history import canonical_identity_code


def footprint():
    return mapping(
        transform(
            Transformer.from_crs(32644, 4326, always_xy=True).transform,
            box(400004, 1440004, 400024, 1440024),
        )
    )


def test_dsm_dem_actual_height_and_explicit_datum():
    inputs = fixture_inputs()
    result = estimate_height(
        inputs["dsm.tif"], inputs["dem.tif"], footprint(), "EPSG:4979"
    )
    assert result["height_value"] == 15
    assert result["base_elevation"] == 10
    assert result["estimated"] and result["confidence"] is None
    assert result["details"]["valid_pixel_count"] == 400
    with pytest.raises(ValueError, match="tags"):
        estimate_height(inputs["dsm.tif"], inputs["dem.tif"], footprint(), "UNKNOWN")


def test_integer_elevations_nodata_remain_missing():
    affine = from_origin(400000, 1440032, 1, 1)
    ground = np.full((32, 32), 10, dtype="int16")
    surface = np.full((32, 32), 25, dtype="int16")
    surface[10:20, 10:20] = -9999
    result = estimate_height(
        geotiff(surface, affine, "m"),
        geotiff(ground, affine, "m"),
        footprint(),
        "EPSG:4979",
    )
    assert result["height_value"] == 15
    assert result["details"]["valid_pixel_count"] == 300


def test_extraction_has_independent_unit_and_corridor_candidates():
    inputs = fixture_inputs()
    with MemoryFile(inputs["mask.tif"]) as mem, mem.open() as src:
        outputs = polygonize_probability(
            src.read(1), src.transform, str(src.crs), 0.5, 1, 32644
        )
    assert len(outputs) == 1
    assert outputs[0]["area_m2"] == 400
    image = cv2.imdecode(
        np.frombuffer(inputs["floor-plan.png"], dtype="uint8"), cv2.IMREAD_GRAYSCALE
    )
    regions = enclosed_plan_regions(
        image, from_origin(400004, 1440024, 1, 1), "EPSG:32644", 1, 32644
    )
    assert len(regions) == 3
    assert sorted(x["area_m2"] for x in regions) == [18, 126, 144]
    assert all(x["confidence"] is None for x in regions)


def test_floor_planes_deterministic_not_auto_adopted():
    points = np.load(io.BytesIO(fixture_inputs()["planes.npy"]), allow_pickle=False)
    first = suggest_horizontal_levels(points)
    assert first == suggest_horizontal_levels(points)
    assert len(first) == 6


@pytest.mark.parametrize(
    "polygon",
    [
        box(0, 0, 5, 8),
        Polygon([(0, 0), (5, 0), (5, 2), (2, 2), (2, 5), (0, 5)]),
        Polygon(
            [(0, 0), (8, 0), (8, 8), (0, 8)], holes=[[(2, 2), (2, 4), (4, 4), (4, 2)]]
        ),
    ],
)
def test_prisms_are_closed_with_correct_volume(polygon):
    vertices, faces = prism_mesh(polygon, -3, 2)
    result = validate_mesh(vertices, faces)
    assert result["volume"] == pytest.approx(polygon.area * 5)
    with pytest.raises(ValueError):
        validate_mesh(vertices, faces[:-1])


def test_identity_hash_repeat_and_change():
    object_id = UUID(int=1)
    a, _ = canonical_identity_code("PARCEL-UUID:demo", object_id, "a" * 64)
    assert a == canonical_identity_code("PARCEL-UUID:demo", object_id, "a" * 64)[0]
    assert a != canonical_identity_code("PARCEL-UUID:demo", object_id, "b" * 64)[0]
    assert a.startswith("ASTRA-P3D-2-")


def test_enu_transform_is_right_handed_and_ecef_anchored():
    origin, rotation, flat = enu_frame(80, 13, 10)
    matrix = np.array(flat).reshape(4, 4).T
    assert np.linalg.det(rotation) == pytest.approx(1)
    np.testing.assert_allclose(rotation.T @ rotation, np.eye(3), atol=1e-12)
    np.testing.assert_allclose(matrix[:3, 3], origin)


def test_missing_models_do_not_produce_inference(monkeypatch):
    import app.assistance as assistance
    from app.config import Settings

    monkeypatch.setattr(
        assistance,
        "get_settings",
        lambda: Settings(segformer_weights="", pointnet_weights=""),
    )
    with pytest.raises(assistance.ModelUnavailable, match="no inference"):
        assistance.infer_building_probability(np.zeros((4, 4, 3), dtype="uint8"))
    with pytest.raises(assistance.ModelUnavailable):
        assistance.pointnet_floor_scores(np.zeros((10, 3)))
