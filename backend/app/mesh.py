"""Closed, consistently wound triangle meshes for valid vertical prisms."""

from collections import Counter

import mapbox_earcut
import numpy as np
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient


def prism_mesh(polygon: Polygon, low: float, high: float):
    if (
        not polygon.is_valid
        or polygon.is_empty
        or not np.isfinite([low, high]).all()
        or high <= low
    ):
        raise ValueError("Invalid prism input")
    polygon = orient(polygon, sign=1)
    rings = [
        np.asarray(r.coords[:-1], dtype="float64")
        for r in [polygon.exterior, *polygon.interiors]
    ]
    vertices_2d = np.vstack(rings)
    ends = np.cumsum([len(r) for r in rings]).astype("uint32")
    n = len(vertices_2d)
    vertices = np.vstack(
        [
            np.column_stack([vertices_2d, np.full(n, low)]),
            np.column_stack([vertices_2d, np.full(n, high)]),
        ]
    )
    caps = mapbox_earcut.triangulate_float64(vertices_2d, ends).reshape(-1, 3)
    faces = []
    for triangle in caps:
        a, b, c = map(int, triangle)
        normal = np.cross(vertices[b] - vertices[a], vertices[c] - vertices[a])[2]
        if normal < 0:
            b, c = c, b
        faces.extend([(a, c, b), (a + n, b + n, c + n)])
    start = 0
    for end in ends:
        for a in range(start, int(end)):
            b = start if a + 1 == end else a + 1
            faces.extend([(a, b, b + n), (a, b + n, a + n)])
        start = int(end)
    triangle_faces = np.asarray(faces, dtype="int64")
    result = validate_mesh(vertices, triangle_faces)
    expected = polygon.area * (high - low)
    if not np.isclose(result["volume"], expected, rtol=1e-7, atol=1e-6):
        raise ValueError("Mesh volume does not match the source prism")
    return vertices, triangle_faces


def validate_mesh(vertices, faces):
    vertices, faces = np.asarray(vertices, dtype="float64"), np.asarray(
        faces, dtype="int64"
    )
    if (
        vertices.ndim != 2
        or vertices.shape[1] != 3
        or not np.isfinite(vertices).all()
        or faces.ndim != 2
        or faces.shape[1] != 3
    ):
        raise ValueError("Invalid vertex or triangle layout")
    if faces.min() < 0 or faces.max() >= len(vertices):
        raise ValueError("Triangle index outside vertex range")
    directed: Counter[tuple[int, int]] = Counter()
    undirected: Counter[tuple[int, ...]] = Counter()
    for face in faces:
        for a, b in zip(face, np.roll(face, -1), strict=True):
            directed[(int(a), int(b))] += 1
            undirected[tuple(sorted((int(a), int(b))))] += 1
    if any(n != 2 for n in undirected.values()) or any(
        directed[(a, b)] != 1 or directed[(b, a)] != 1 for a, b in undirected
    ):
        raise ValueError("Mesh is not a closed, consistently wound manifold")
    # Translate before signed-volume calculation to avoid cancellation at UTM magnitudes.
    relative = vertices - vertices.mean(axis=0)
    triangles = relative[faces]
    areas = np.linalg.norm(
        np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]),
        axis=1,
    )
    if np.any(areas < 1e-12):
        raise ValueError("Degenerate triangle")
    volume = float(
        np.einsum(
            "ij,ij->i", triangles[:, 0], np.cross(triangles[:, 1], triangles[:, 2])
        ).sum()
        / 6
    )
    if volume <= 0:
        raise ValueError("Mesh has inverted winding or non-positive volume")
    return {
        "closed": True,
        "consistent_winding": True,
        "volume": volume,
        "vertices": len(vertices),
        "triangles": len(faces),
    }
