"""Deterministic geometry utilities. No inferred heights or legal boundaries."""

import hashlib
import json
import math

from pyproj import CRS, Transformer
from shapely import normalize, to_wkb
from shapely.geometry import Polygon, mapping, shape
from shapely.geometry.polygon import orient
from shapely.ops import transform
from shapely.validation import explain_validity

from app.schemas import GeometryCreate


def polygon_from_geojson(value: dict) -> Polygon:
    try:
        polygon = shape(value)
    except Exception as exc:
        raise ValueError("Malformed GeoJSON geometry") from exc
    if not isinstance(polygon, Polygon):
        raise ValueError("This phase supports Polygon footprints only")
    if polygon.has_z:
        raise ValueError(
            "Footprints must be 2D; supply explicit vertical bounds separately"
        )
    if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
        raise ValueError(f"Invalid footprint: {explain_validity(polygon)}")
    if not all(
        math.isfinite(c)
        for ring in [polygon.exterior, *polygon.interiors]
        for pt in ring.coords
        for c in pt
    ):
        raise ValueError("Coordinates must be finite")
    if sum(len(r.coords) for r in [polygon.exterior, *polygon.interiors]) > 10000:
        raise ValueError("Footprint exceeds the 10,000 vertex limit")
    return polygon


def project_footprint(value: dict, source_crs: str, metric_srid: int):
    polygon = polygon_from_geojson(value)
    source = CRS.from_user_input(source_crs)
    metric = CRS.from_epsg(metric_srid)
    if not (source.is_geographic or source.is_projected) or len(source.axis_info) != 2:
        raise ValueError("Source CRS must describe two horizontal axes")
    if not metric.is_projected or any(
        abs(axis.unit_conversion_factor - 1) > 1e-9 for axis in metric.axis_info[:2]
    ):
        raise ValueError("Target CRS must be projected in metres")
    to_geo = Transformer.from_crs(source, 4326, always_xy=True, allow_ballpark=False)
    geographic = transform(to_geo.transform, polygon)
    polygon_from_geojson(mapping(geographic))
    minx, miny, maxx, maxy = geographic.bounds
    if minx < -180 or maxx > 180 or miny < -90 or maxy > 90 or maxx - minx > 180:
        raise ValueError("Geographic extent outside supported longitude/latitude range")
    area = metric.area_of_use
    if area and not (
        area.west <= minx <= maxx <= area.east
        and area.south <= miny <= maxy <= area.north
    ):
        raise ValueError("Footprint outside target CRS area of use")
    to_metric = Transformer.from_crs(4326, metric, always_xy=True, allow_ballpark=False)
    projected = transform(to_metric.transform, geographic)
    polygon_from_geojson(mapping(projected))
    if projected.area > 10_000_000:
        raise ValueError("Phase-one parcel extent exceeds 10 square kilometres")
    provenance = {
        "source": source.to_string(),
        "horizontal_target": "EPSG:4326",
        "metric_target": metric.to_string(),
        "always_xy": True,
        "horizontal_operation": to_geo.description,
        "metric_operation": to_metric.description,
        "vertical_transformation": "NONE; supplied heights retained in named reference",
    }
    return geographic, projected, provenance


def prism_shell_wkt(polygon: Polygon, low: float, high: float) -> str:
    """Closed oriented shell for a constant-Z extrusion, including courtyard holes."""
    polygon = orient(polygon, sign=1.0)

    def ring_text(points, z):
        return "(" + ",".join(f"{x:.12g} {y:.12g} {z:.12g}" for x, y in points) + ")"

    rings = [
        list(polygon.exterior.coords),
        *[list(r.coords) for r in polygon.interiors],
    ]
    faces = [
        "(" + ",".join(ring_text(list(reversed(r)), low) for r in rings) + ")",
        "(" + ",".join(ring_text(r, high) for r in rings) + ")",
    ]
    for ring in rings:
        for a, b in zip(ring[:-1], ring[1:], strict=True):
            points = [
                (a[0], a[1], low),
                (b[0], b[1], low),
                (b[0], b[1], high),
                (a[0], a[1], high),
                (a[0], a[1], low),
            ]
            faces.append(
                "(("
                + ",".join(f"{x:.12g} {y:.12g} {z:.12g}" for x, y, z in points)
                + "))"
            )
    return "POLYHEDRALSURFACE Z (" + ",".join(faces) + ")"


def geometry_digest(polygon: Polygon, request: GeometryCreate) -> str:
    # Exact canonical coordinates: no undocumented rounding / survey precision claim.
    metadata = json.dumps(
        {
            "z_min": request.z_min,
            "z_max": request.z_max,
            "elevation_reference": request.elevation_reference,
            "horizontal_crs": "EPSG:4326",
        },
        sort_keys=True,
    ).encode()
    return hashlib.sha256(
        to_wkb(normalize(polygon), byte_order=1) + metadata
    ).hexdigest()


def overlap_volume(
    a: Polygon, a_low: float, a_high: float, b: Polygon, b_low: float, b_high: float
) -> float:
    """Exact for supported vertical prisms in the SAME metric and vertical reference."""
    height = min(a_high, b_high) - max(a_low, b_low)
    if height <= 0:
        return 0.0
    return a.intersection(b).area * height
