import numpy as np
from rasterio.features import geometry_mask
from rasterio.io import MemoryFile
from rasterio.warp import Resampling, reproject, transform_geom

from app.config import get_settings


def inspect_raster(content: bytes):
    with MemoryFile(content) as mem, mem.open() as src:
        if src.driver != "GTiff" or src.crs is None:
            raise ValueError("A georeferenced GeoTIFF with explicit CRS is required")
        if src.width * src.height > get_settings().max_raster_pixels:
            raise ValueError(
                "Raster exceeds configured pixel limit; preprocess into smaller windows"
            )
        return {
            "format": src.driver,
            "crs": src.crs.to_string(),
            "extent": list(src.bounds),
            "width": src.width,
            "height": src.height,
            "bands": src.count,
            "nodata": str(src.nodata),
            "units": list(src.units),
        }


def estimate_height(
    dsm_bytes: bytes, dem_bytes: bytes, footprint: dict, vertical_reference: str
):
    """Resample DEM to DSM grid, retain nodata, compare only footprint pixels."""
    if not vertical_reference.strip():
        raise ValueError("A common vertical reference must be declared")
    inspect_raster(dsm_bytes)
    inspect_raster(dem_bytes)
    with MemoryFile(dsm_bytes) as dsm_mem, MemoryFile(dem_bytes) as dem_mem:
        with dsm_mem.open() as dsm, dem_mem.open() as dem:
            for src in (dsm, dem):
                if src.count != 1:
                    raise ValueError("Elevation datasets must have one band")
                if src.units[0] not in ("m", "metre", "meter"):
                    raise ValueError("Elevation band units must explicitly be metres")
                if src.tags().get("VERTICAL_REFERENCE") != vertical_reference:
                    raise ValueError(
                        "Both GeoTIFF VERTICAL_REFERENCE tags must match the requested reference"
                    )
            surface = dsm.read(1, masked=True).astype("float64").filled(np.nan)
            ground_source = dem.read(1, masked=True).astype("float64").filled(np.nan)
            ground = np.full(surface.shape, np.nan)
            reproject(
                source=ground_source,
                destination=ground,
                src_transform=dem.transform,
                src_crs=dem.crs,
                src_nodata=np.nan,
                dst_transform=dsm.transform,
                dst_crs=dsm.crs,
                dst_nodata=np.nan,
                resampling=Resampling.bilinear,
            )
            local_polygon = transform_geom("EPSG:4326", dsm.crs, footprint)
            inside = geometry_mask(
                [local_polygon], surface.shape, dsm.transform, invert=True
            )
            valid = inside & np.isfinite(surface) & np.isfinite(ground)
            if valid.sum() < 4:
                raise ValueError(
                    "Fewer than four comparable elevation pixels inside footprint"
                )
            differences = surface[valid] - ground[valid]
            median = float(np.median(differences))
            if median <= 0:
                raise ValueError(
                    "DSM minus DEM does not support a positive building height"
                )
            return {
                "height_value": median,
                "base_elevation": float(np.median(ground[valid])),
                "height_source": "DEM_DSM",
                "confidence": None,
                "vertical_reference": vertical_reference,
                "estimated": True,
                "details": {
                    "valid_pixel_count": int(valid.sum()),
                    "valid_coverage_fraction": float(
                        valid.sum() / max(inside.sum(), 1)
                    ),
                    "negative_difference_pixels": int((differences < 0).sum()),
                    "height_iqr_m": float(
                        np.percentile(differences, 75) - np.percentile(differences, 25)
                    ),
                    "method": "Median DSM minus reprojected DEM within footprint; no inferred accuracy",
                },
            }
