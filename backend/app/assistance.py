"""Assistive algorithms. No output from these functions is accepted cadastral geometry."""

import importlib.util
from pathlib import Path

import cv2
import numpy as np
from pyproj import Transformer
from rasterio.features import shapes
from rasterio.transform import Affine
from shapely.geometry import mapping, shape
from shapely.ops import transform

from app.config import get_settings


class ModelUnavailable(ValueError):
    pass


def model_status():
    settings = get_settings()
    segformer = (
        bool(settings.segformer_weights)
        and Path(settings.segformer_weights).is_dir()
        and settings.segformer_building_class is not None
        and importlib.util.find_spec("torch") is not None
        and importlib.util.find_spec("transformers") is not None
    )
    pointnet = (
        bool(settings.pointnet_weights)
        and Path(settings.pointnet_weights).is_file()
        and importlib.util.find_spec("torch") is not None
    )
    return {
        "segformer": {
            "available": segformer,
            "reason": "Requires local segmentation weights, transformers, PyTorch and explicit building class ID",
        },
        "pointnet++": {
            "available": pointnet,
            "reason": "Requires a locally supplied TorchScript PointNet++ model with documented N x 3 -> N logits contract",
        },
    }


def infer_building_probability(rgb: np.ndarray) -> np.ndarray:
    if not model_status()["segformer"]["available"]:
        raise ModelUnavailable(
            "SegFormer unavailable: configure local compatible weights and building class; no inference performed"
        )
    import torch
    from transformers import AutoImageProcessor, SegformerForSemanticSegmentation

    settings = get_settings()
    processor = AutoImageProcessor.from_pretrained(
        settings.segformer_weights, local_files_only=True
    )
    model = SegformerForSemanticSegmentation.from_pretrained(
        settings.segformer_weights, local_files_only=True
    ).eval()
    with torch.inference_mode():
        logits = model(**processor(images=rgb, return_tensors="pt")).logits
        logits = torch.nn.functional.interpolate(
            logits, size=rgb.shape[:2], mode="bilinear", align_corners=False
        )
        class_id = settings.segformer_building_class
        if class_id is None or not 0 <= class_id < logits.shape[1]:
            raise ValueError("Building class is outside the supplied model label space")
        return logits.softmax(dim=1)[0, class_id].cpu().numpy()


def polygonize_probability(
    probability: np.ndarray,
    affine: Affine,
    source_crs: str,
    threshold: float,
    min_area_m2: float,
    metric_srid: int,
):
    if probability.ndim != 2 or probability.size > get_settings().max_raster_pixels:
        raise ValueError("Expected a bounded, single-band probability mask")
    if not np.isfinite(probability).all() or np.any(
        (probability < 0) | (probability > 1)
    ):
        raise ValueError("Probability mask must be finite and between zero and one")
    binary = (probability >= threshold).astype("uint8")
    # Connected components remove only explicitly small regions; boundaries are not silently smoothed.
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=4)
    to_metric = Transformer.from_crs(source_crs, metric_srid, always_xy=True)
    to_geo = Transformer.from_crs(source_crs, 4326, always_xy=True)
    suggestions = []
    for component in range(1, count):
        component_mask = labels == component
        for geometry, value in shapes(
            component_mask.astype("uint8"),
            mask=component_mask,
            transform=affine,
            connectivity=4,
        ):
            if value != 1:
                continue
            polygon = shape(geometry)
            if not polygon.is_valid or polygon.is_empty:
                raise ValueError(
                    "Polygonized mask is invalid; human correction required"
                )
            metric = transform(to_metric.transform, polygon)
            if metric.area < min_area_m2:
                continue
            suggestions.append(
                {
                    "footprint": mapping(transform(to_geo.transform, polygon)),
                    "confidence": float(probability[component_mask].mean()),
                    "area_m2": metric.area,
                    "method": "Threshold + OpenCV connected components + Rasterio polygonization",
                    "threshold": threshold,
                }
            )
    return sorted(suggestions, key=lambda x: shape(x["footprint"]).bounds)


def enclosed_plan_regions(
    image: np.ndarray,
    affine: Affine,
    source_crs: str,
    min_area_m2: float,
    metric_srid: int,
):
    """Closed-space candidates only. Open doors/walls can merge regions; no ownership inference."""
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
    if gray.size > get_settings().max_raster_pixels:
        raise ValueError("Plan exceeds configured pixel limit")
    _, walls = cv2.threshold(
        gray.astype("uint8"), 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU
    )
    free = (walls == 0).astype("uint8")
    count, labels = cv2.connectedComponents(free, connectivity=4)
    border = set(
        np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]).tolist()
    )
    candidates = np.isin(
        labels, [x for x in range(1, count) if x not in border]
    ).astype("float32")
    outputs = polygonize_probability(
        candidates, affine, source_crs, 0.5, min_area_m2, metric_srid
    )
    for output in outputs:
        output["confidence"] = None
        output["method"] = (
            "OpenCV Otsu wall threshold + enclosed region detection; not an AI score"
        )
    return outputs


def pointnet_floor_scores(points: np.ndarray):
    if not model_status()["pointnet++"]["available"]:
        raise ModelUnavailable(
            "PointNet++ unavailable: no compatible local TorchScript weights"
        )
    import torch

    model = torch.jit.load(get_settings().pointnet_weights, map_location="cpu").eval()
    with torch.inference_mode():
        scores = (
            model(torch.from_numpy(points.astype("float32"))).sigmoid().cpu().numpy()
        )
    if scores.shape != (len(points),):
        raise ValueError("PointNet++ adapter expects one logit per input point")
    return scores


def suggest_horizontal_levels(points: np.ndarray, tolerance_m=0.08, min_samples=20):
    points = np.asarray(points, dtype="float64")
    if (
        points.ndim != 2
        or points.shape[1] != 3
        or not 3 <= len(points) <= get_settings().max_point_count
    ):
        raise ValueError(
            "Point cloud requires N x 3 coordinates within configured limit"
        )
    if not np.isfinite(points).all():
        raise ValueError("Point cloud has non-finite coordinates")
    clusters = dbscan_elevations(points[:, 2], tolerance_m, min_samples)
    results = []
    for label in sorted(set(clusters) - {-1}):
        group = points[clusters == label]
        coefficients, inlier_mask = ransac_plane(group, tolerance_m)
        if np.linalg.norm(coefficients[:2]) > 0.02:
            continue
        inliers = group[inlier_mask]
        results.append(
            {
                "elevation": float(np.median(inliers[:, 2])),
                "point_count": len(inliers),
                "inlier_fraction": float(len(inliers) / len(group)),
                "confidence": None,
                "method": "DBSCAN elevation clusters + seeded RANSAC horizontal planes",
                "status": "SUGGESTED",
                "note": "Observed planes are not automatically floors, ceilings or ownership boundaries",
            }
        )
    return sorted(results, key=lambda x: x["elevation"])


def dbscan_elevations(values, eps, min_samples):
    """Exact 1D DBSCAN with deterministic border assignment and bounded memory."""
    values = np.asarray(values)
    order = np.argsort(values, kind="stable")
    sorted_values = values[order]
    left = np.searchsorted(sorted_values, sorted_values - eps, side="left")
    right = np.searchsorted(sorted_values, sorted_values + eps, side="right")
    core = (right - left) >= min_samples
    labels = np.full(len(values), -1, dtype=int)
    core_indices = np.flatnonzero(core)
    cluster = -1
    previous = None
    for index in core_indices:
        if previous is None or sorted_values[index] - sorted_values[previous] > eps:
            cluster += 1
        labels[index] = cluster
        previous = index
    for index in np.flatnonzero(~core):
        nearby = core_indices[
            (core_indices >= left[index]) & (core_indices < right[index])
        ]
        if len(nearby):
            labels[index] = labels[nearby[0]]
    result = np.full(len(values), -1, dtype=int)
    result[order] = labels
    return result


def ransac_plane(points, tolerance, trials=100):
    rng = np.random.default_rng(0)
    # Center XY before fitting to preserve precision for projected coordinates.
    center = points[:, :2].mean(axis=0)
    design = np.column_stack([points[:, :2] - center, np.ones(len(points))])
    best = np.zeros(len(points), dtype=bool)
    for _ in range(trials):
        indices = rng.choice(len(points), 3, replace=False)
        if np.linalg.matrix_rank(design[indices]) < 3:
            continue
        coefficients = np.linalg.lstsq(design[indices], points[indices, 2], rcond=None)[
            0
        ]
        mask = np.abs(design @ coefficients - points[:, 2]) <= tolerance
        if mask.sum() > best.sum():
            best = mask
    if best.sum() < 3:
        raise ValueError("Insufficient non-collinear points for a horizontal plane")
    coefficients = np.linalg.lstsq(design[best], points[best, 2], rcond=None)[0]
    return coefficients, best
