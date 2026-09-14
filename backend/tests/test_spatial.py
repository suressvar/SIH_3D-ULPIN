import json

import pytest
from pydantic import ValidationError
from shapely.geometry import Polygon, box, mapping

from app.schemas import GeometryCreate, JobCreate, ObjectCreate
from app.services.ingestion import inspect_geojson
from app.spatial import (
    geometry_digest,
    overlap_volume,
    polygon_from_geojson,
    prism_shell_wkt,
    project_footprint,
)


def payload(**changes):
    data = dict(
        footprint=mapping(box(400000, 1440000, 400020, 1440020)),
        source_crs="EPSG:32644",
        metric_srid=32644,
        source_category="MANUAL",
        method="Explicit synthetic coordinates",
    )
    return GeometryCreate(**(data | changes))


def test_projection_roundtrip_preserves_metric_area_and_records_operation():
    geographic, metric, history = project_footprint(
        payload().footprint, "EPSG:32644", 32644
    )
    assert metric.area == pytest.approx(400, rel=1e-8)
    assert 79 < geographic.centroid.x < 81
    assert 12 < geographic.centroid.y < 14
    assert history["vertical_transformation"].startswith("NONE")


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "Point", "coordinates": [80, 13]},
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]},
        {"type": "Polygon", "coordinates": []},
        {
            "type": "Polygon",
            "coordinates": [[[0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 0, 1]]],
        },
    ],
)
def test_invalid_footprints_are_rejected_without_repair(bad):
    with pytest.raises(ValueError):
        polygon_from_geojson(bad)


@pytest.mark.parametrize(
    "changes",
    [
        {"z_min": 0},
        {"z_min": 0, "z_max": 3},
        {"z_min": 3, "z_max": 0, "elevation_reference": "local"},
        {"confidence": 1.1},
        {"z_min": float("nan"), "z_max": 3, "elevation_reference": "local"},
    ],
)
def test_missing_or_inconsistent_height_and_confidence_rejected(changes):
    with pytest.raises(ValidationError):
        payload(**changes)


def test_no_default_height():
    assert payload().z_min is None
    assert payload().z_max is None


def test_metric_crs_and_area_of_use_required():
    with pytest.raises(ValueError, match="projected"):
        project_footprint(payload().footprint, "EPSG:32644", 4326)
    with pytest.raises(ValueError, match="area of use"):
        project_footprint(payload().footprint, "EPSG:32644", 32632)


def test_overlap_distinguishes_stacked_touching_and_contained_prisms():
    a, b = box(0, 0, 10, 10), box(2, 2, 4, 4)
    assert overlap_volume(a, 0, 3, b, 1, 2) == 4
    assert overlap_volume(a, 0, 3, a, 3, 6) == 0
    assert overlap_volume(a, 0, 3, box(10, 0, 20, 10), 0, 3) == 0


def test_courtyard_is_not_solid_property():
    courtyard = Polygon(
        [(0, 0), (10, 0), (10, 10), (0, 10)], [[(2, 2), (4, 2), (4, 4), (2, 4)]]
    )
    assert overlap_volume(courtyard, 0, 3, box(2.1, 2.1, 3.9, 3.9), 0, 3) == 0
    shell = prism_shell_wkt(courtyard, -3, 0)
    assert shell.startswith("POLYHEDRALSURFACE Z")
    assert "-3" in shell


def test_canonical_hash_ignores_ring_direction_but_tracks_height():
    a = box(0, 0, 10, 10)
    b = Polygon(list(a.exterior.coords)[::-1])
    request = payload(z_min=0, z_max=3, elevation_reference="SYNTHETIC")
    assert geometry_digest(a, request) == geometry_digest(b, request)
    assert geometry_digest(a, request) != geometry_digest(
        a, request.model_copy(update={"z_max": 4})
    )


def test_geojson_batch_is_all_or_nothing_and_never_guesses_metric_crs():
    doc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {}, "geometry": payload().footprint},
            {
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "Point", "coordinates": [0, 0]},
            },
        ],
    }
    with pytest.raises(ValueError, match="Feature 1"):
        inspect_geojson(json.dumps(doc).encode(), "EPSG:32644", 32644)
    with pytest.raises(ValueError, match="metric_srid"):
        inspect_geojson(json.dumps(doc).encode(), "EPSG:32644", None)


def test_job_contract_does_not_accept_imaginary_processing():
    with pytest.raises(ValidationError):
        JobCreate(kind="FAKE_AI_SUCCESS")
    with pytest.raises(ValidationError):
        JobCreate(kind="VALIDATE_PRISM")


def test_unit_requires_parent_and_existing_ulpin_is_parcel_only():
    with pytest.raises(ValidationError):
        ObjectCreate(kind="UNIT", label="302")
