# Phase two implementation map

Existing phase-one models, endpoints, prism utilities, immutable history and authentication remain authoritative. Existing 33 tests will remain regression checks. No frontend rewrite.

Additive work: migration 0003; suggestion/decision and height observation records; processing input parameters; real Rasterio height estimation and OpenCV mask/plan polygonization; optional local-only SegFormer and PointNet++ interfaces; explicit levels and geometric point-cloud suggestions; expanded rule-based validation with affected geometry; canonical proposed identity revisions; evidence-backed split/merge history; verified Blender GLB and 3D Tiles 1.1 exports; deterministic five-floor dataset runner.

No model checkpoints are supplied. Models must report unavailable until local compatible weights are configured. Synthetic masks/points/raster values are declared fixtures, not inference. Geometry remains draft until human action, and survey verification requires an explicit officer attestation. Validation and acceptance are separate.

Use installed Blender 5.2 and existing isolated PostgreSQL/PostGIS for local verification. Preserve legacy seed and identifiers. The new demo is a separate namespace. Export shells represent cadastral volumes, not invented photogrammetric facade detail.
