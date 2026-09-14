# Astra VI — phase 2 implementation report

Verified locally on 13 September 2026. This extends the phase-one FastAPI/PostGIS implementation. It does not replace it.

## Implemented and tested

- GeoTIFF inspection and DSM/DEM alignment with Rasterio; explicit metre units and matching vertical references; nodata exclusion; median height and coverage statistics. Height is recorded as an estimate, never survey accuracy.
- OpenCV/Rasterio building-mask polygonization and enclosed floor-plan region suggestions. A surveyor must explicitly adopt or correct a suggestion. Extraction does not modify cadastral geometry.
- Bounded NumPy elevation DBSCAN and seeded RANSAC plane suggestions from NPY point coordinates. Floors use explicit arbitrary levels; five is only the demo fixture.
- Independent units, shared spaces and underground bounds with source links and geometry history.
- Closed polygon prisms, including concave footprints and holes; mesh winding, closure and positive volume checks.
- Deterministic topology explanations: parent bounds, exclusive overlaps, shared-use relationships, floating units, explicit complete-partition gaps and penetration into another parcel's prototype-accepted space. Applicable intersections have stored PostGIS affected geometry and vertical bounds.
- Proposed 3D ULPIN canonical encoding with parent reference, object identity and geometry hash. Exact repeated geometry retains its code while each geometry version retains its own link. Historical identities remain intact.
- Evidence-linked replacement, split and merge; optimistic geometry-version checks; split/merge area and height conservation; predecessor relationships; no automatic rights transfer.
- Real Blender GLBs, glTF Transform deduplication and Khronos glTF validation. Private, checksum-addressed files; versioned cached export bundles; GeoJSON and 3D Tiles 1.1 with tile metadata and glTF extras.
- FastAPI contracts for processing, suggestions, heights, floors, changes, provenance status, issue explanations, relationships and export downloads. Existing authentication, roles, rights, evidence, reviews and audit remain connected.

## Validation results

49 tests passed, including 14 tests using actual PostgreSQL/PostGIS and a real Blender export. Ruff and Black checks passed; mypy passed for 36 application files; pip reported no broken requirements.

The persistent synthetic pipeline ran in the project's isolated database on localhost port 55439, database astra_demo. Independent verification found:

| Item | Result |
|---|---:|
| Parcel / building | 1 / 1 |
| Floors / units | 5 / 10 |
| Shared corridors / independent basement | 5 / 1 |
| Current geometries | 23 |
| Proposed identity versions | 16 |
| Export files / GLBs | 20 / 17 |
| ERROR or CRITICAL validation findings | 0 |

The synthetic DSM minus DEM produced a 15 m building height. Six noisy horizontal point planes were suggested; the operator fixture independently supplied five explicit floor intervals. Unit extraction produced two apartment regions and one corridor region on each floor. Wall strips are intentionally not asserted to be a complete ownership partition.

Every exported file's checksum was checked. GLB meshes passed closure/winding checks and the Khronos validator reported zero errors. Tile content references, metadata object IDs, root orientation and bounds against exported GLB positions were checked. Formal OGC JSON-schema validation and browser/Cesium rendering have not been performed.

Results: [pipeline report](../output/phase2-demo/pipeline-report.json), [independent verification](../output/phase2-demo/verification.json), [GLB scene](../output/phase2-demo/scene.glb), [tileset](../output/phase2-demo/tileset.json), [GeoJSON](../output/phase2-demo/properties.geojson).

## Partially implemented

- SegFormer local model interface and PointNet++ TorchScript interface exist. Model loading/inference has not been tested with trained weights. No benchmark, AI accuracy, Grad-CAM or scientific confidence calibration is claimed.
- Point ingestion currently accepts bounded NPY arrays, not LAS/LAZ. PDAL/Open3D ingestion and general point-cloud reconstruction remain deferred.
- Plan segmentation identifies closed regions; doors, incomplete walls, scale and registration still require human handling. No OCR, room semantics or ownership inference is performed.
- Geometry is a vertical-prism cadastre, not arbitrary sloped/curved solids or photogrammetric building reconstruction.
- Tiles support per-object streaming at a single detail level. Multi-resolution LOD and large-city performance are not implemented or benchmarked.
- Provenance/validation/acceptance states are available through the API. The Next.js/Cesium surveyor and officer UI remains a later phase; no primary viewer was substituted.
- Docker processing-worker configuration is supplied but has not been built on this host.

## Blocked dependencies and untested integrations

Docker's Linux engine is still unavailable. A fresh check failed because its named pipe did not exist. Therefore this phase does not claim a successful Redis/Celery broker delivery test or container build. The existing durable Celery dispatcher and worker registrations remain in place.

The demo CLI ran the same real processing handlers directly, with persisted QUEUED/RUNNING/COMPLETED states. This is an explicit local execution fallback, not a simulated queue or fabricated result.

Compatible SegFormer/PointNet++ weights and optional PyTorch/transformers runtime are not supplied. Missing-model requests fail without generating inference. Supabase login and cloud object storage require credentials and were not exercised live.

Windows application control blocked a compiled scikit-learn component during development. The application now uses bounded NumPy implementations for its one-dimensional elevation clustering and plane fitting; the security policy was not bypassed.

## Demo fallback

All fixture sources and records are labelled **Demo / Synthetic Dataset**. Building-mask processing uses a known binary mask, not AI inference. Heights come from actual synthetic GeoTIFF calculations. Explicit operator fixture actions adopt boundaries and level intervals as draft geometry. The basement has independent footprint and extent.

No synthetic record is survey-verified, legally accepted, or represented as a government ownership record. All generated codes are **Proposed 3D ULPIN** prototype encodings.

## Database changes

Migrations 0003 and 0004 extend the existing private cadastre schema.

New tables: spatial_suggestions, suggestion_decisions, height_observations, identity_versions, geometry_changes, change_members, asset_bundles, geometry_attestations.

Existing tables gain spatial-object lifecycle/semantic type, processing parameters and job kinds, and validation affected geometry/status/CRITICAL severity. Foreign keys, spatial indexes, immutable-history triggers, RLS and backend-role grants accompany the additions. Migration 0004 permits repeated canonical codes across distinct historical geometry links. Original phase-one migrations and seed remain preserved.

## API and flow

The new /api/v1/pipeline routes cover capabilities, datasets, jobs, suggestions/decisions, heights, floors, validation, detailed issues, relationships, changes, history, identity versions and geometry status/attestations. Authenticated /api/v1/exports routes serve manifests and files. See [OpenAPI](openapi.json) for exact request and response contracts.

Original file → inspected source record → queued processing → suggestion or height observation → explicit surveyor adoption → PostGIS geometry version → validation job/issues → proposed identity version → evidence/officer review → export bundle and private files.

Processing never establishes legal rights. Existing rights and evidence services remain separate from geometric proximity.

## Files and operation

Added application modules: assistance, raster_processing, mesh, pipeline_models, pipeline_schemas, demo_pipeline, verify_demo, blender_export; pipeline/history/topology/exports services; pipeline router; migrations 0003–0004; processing tests; glTF verification tools and optional worker container.

Extended existing config, models, schemas, object/record/validation services, repositories, worker, API startup and migration metadata. Updated dependency lock, environment example and OpenAPI. The entire repository remains uncommitted as it was before this phase; no working modules were reset.

See [run instructions](PHASE_2_RUN.md).

## Technical limits

A global transaction lock currently serializes geometry mutations, semantic updates, validation and export snapshots. It prevents inconsistent prototype snapshots, but lengthy export jobs can delay writes. Replace it with scoped locking/version snapshots before scaling.

File processing is bounded by upload, raster and point limits, but production isolation, malware scanning and large-file streaming require further work. Invalid sources remain recorded with failure reasons. Storage orphans from failed jobs need later garbage collection.

GeoJSON contains footprints plus explicit vertical metadata; it is not an interoperable solid-geometry encoding. Tiles metadata follows the selected 1.1 structure; EXT_structural_metadata is not claimed. Geographic placement requires explicit ellipsoidal elevation or a declared visualization offset. No height or datum offset is silently guessed.

The models describe source and processing confidence, not legal certainty. Validation is limited to implemented rules; it does not establish structural safety, title, or absence of all real-world conflicts.

## Technical references

- [OGC 3D Tiles 1.1](https://docs.ogc.org/cs/22-025r4/22-025r4.html): tiles, transforms and metadata.
- [Blender glTF export API](https://docs.blender.org/api/current/bpy.ops.export_scene.html): real GLB export.
- [Rasterio reprojection](https://rasterio.readthedocs.io/en/stable/topics/reproject.html): raster grid alignment.
