# Reference dashboard redesign

Implemented in the existing Next.js / FastAPI / PostGIS / Cesium application. The supplied image guided the layout and visual hierarchy; its address, identity, owner and metrics were not copied into records.

## Experience

- Monochrome navigation and header, parcel card, site preview, central Cesium viewer and building inspector.
- Actual floor and unit counts, measured footprint and recorded height come from the database.
- Building / Volumes switches between an illustrative exterior and recorded cadastral geometry. Floor, unit, shared-space, underground and conflict selections expose source geometry. Changed building/floor/parcel versions invalidate the illustrative view.
- Authenticated model and site thumbnails come from the generated Blender mesh. The site preview is labelled illustrative, not satellite imagery.
- Camera, zoom, 2D fallback, floor exploration, validation, evidence, rights, officer review and audit history retain their existing connections.
- Download 3D model returns the current illustrative asset when that view is active, with an explicit illustrative filename. Volume mode downloads the source model.

## Geometry and truthfulness

The B01 exterior is **illustrative synthetic architecture**: windows, balconies, terrace, foliage, streets and surrounding blocks are design illustrations. They are not extracted from a scan, approved plan or real ownership record. Its main dimensions and existing floor levels use the synthetic fixture. It creates no extra floor or ownership claim and never replaces stored cadastre geometry. A real building facade needs supplied BIM, photogrammetry or surveyed modelling inputs.

The exporter creates this optional asset only for an eligible explicitly synthetic fixture with one building, known levels, roof and supported height datum. Other parcels continue using the existing volume pipeline. AI extraction, government integration and legal recognition are not implied.

The same real export job writes private GLB files, PNG previews, appearance specification, source GLBs, 3D Tiles and validation results. Every file is checksum tracked in an immutable bundle. Exterior mesh validity does not imply legal/topological validity of ownership rights.

## Implementation

- `backend/app/illustrative_exterior.py`: deterministic Blender architecture, shared canopy geometry and rendered thumbnails.
- `backend/app/blender_export.py`, `backend/app/services/exports.py`: optional exterior stage, cache version and complete validated bundle publication.
- `backend/app/routers/pipeline.py`: correct media type for authenticated PNG assets.
- `frontend/src/components/workspace.tsx`, `frontend/src/app/globals.css`: reference layout, real previews, metrics and actions.
- `frontend/src/components/map3d.tsx`, `map2d.tsx`: appearance selection, soft lighting, camera and 2D zoom.
- `frontend/src/components/asset-preview.tsx`, `frontend/src/lib/api.ts`: protected asset fetching and cleanup.
- `frontend/src/lib/store.ts`, `view-math.ts`: view state and current-version eligibility.
- `frontend/tests/reference.spec.ts`, `final.spec.ts`, `src/lib/view-math.test.ts`: downloads, view transitions and regression checks.

## Local preview

Use the existing service instructions in `FINAL_RUN.md`. Search **DEMO26011P0001**, select **Building B01**, and choose **Building** in 3D. This is explicitly a Demo / Synthetic Dataset. No new external credentials are required for this redesign. The local browser host remains a testing harness with real JWT verification, PostGIS and processing; it substitutes Redis transport/rate limiting. Live Redis, Supabase, cloud deployment and real surveyed facade inputs remain unverified.

Assets were regenerated without deleting history in `astra_demo` and `astra_ui_test`. The demo exterior bundle is `67234778-768e-4ea2-b3d0-54e48a529550`. Its 477,844-byte GLB passed the Khronos validator with zero errors; 75 deduplicated mesh definitions passed closedness and winding checks. See `output/reference-redesign/asset-verification.json`.

The reference screenshot is captured from the actual application at `output/reference-redesign/dashboard.png`. It is not an image layered over the viewer.

## Verification

- Backend: 57 tests passed in the general run; the skipped Blender integration test then passed separately with Blender configured (58 tests covered).
- Frontend: 7 Vitest tests passed, including stale-geometry, individual-property and conflict eligibility checks.
- Browser: all 8 scenarios passed across the full run and the targeted rerun after fixing decorative arrows in accessible button names. Coverage includes downloads, floor selection, real 3D Tiles, evidence, correction, separate-officer decisions, audit history, no-WebGL fallback, constrained CPU/network and desktop responsive sizes.
- Production build and browser bundle parsing passed. Ruff, Black, mypy, ESLint and TypeScript checks passed.
- The final software-rendering adjustment is checked with the reference browser test. Software WebGL uses clean PBR lighting without unstable shadow maps; hardware shadow quality still needs verification on the target presentation machine.

OneDrive intermittently caused Next.js to fail while cleaning an earlier generated build folder. A fresh build folder resolved it; temporary build copies were cleaned up. This does not alter source data.
