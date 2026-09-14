# Phase 4 — governance and explainability

## Existing implementation retained

The phase-one PostGIS/FastAPI foundation, phase-two geometry engine, source pipeline, immutable geometry versions, proposed identity versions, Celery job model, real Blender/GLB exports, and phase-three Next.js/Cesium workspace remain in place.

## Implemented

- Versioned deterministic rule catalog (ASTRA-PRISM-3) with operations, tolerances, evaluated severity and correction guidance. New findings retain the rule definition that produced them.
- Geometry/object/relationship/recorded-right semantics. Explicit ACCESS, SHARED_USE and EASEMENT scopes can explain a unit/shared-space intersection; scoped RESTRICTION prevents automatic permitted classification. These records never override exclusive unit-volume overlap or certify legal title.
- Validation snapshots include relevant recorded rights, scopes and ruleset version. Changed records require revalidation before review.
- Append-only workflow events for draft geometry, actual validation execution/results, review submission, correction requests and prototype acceptance. No historical transitions are invented for pre-existing data.
- Officer decisions require a different actor from the submitter, current passing validation and a Proposed 3D ULPIN version tied to the geometry submitted.
- A connected property case UI: evidence upload/download, recorded rights, explicit right scopes, boundary revision, unit split/merge, provided property details, validation, proposed identity, review, decisions and preserved history.
- An officer review queue links to the same property records shown in the 3D explorer.
- Evidence/source dates, source classification, methods, supplied confidence and reviewer attestations remain distinct. AI display bands are explicitly a UI policy, not survey accuracy.
- Structured property, validation, provenance, review and change-history reports use the actual case records. JSON export and browser printing are available.
- Administrator membership updates with audit reasons and a last-active-administrator guard.
- Local Cesium browser distribution loading avoids a production bundler syntax error reproduced during browser verification. A post-build parser checks every shipped application chunk and the Cesium distribution. See the related upstream report: https://github.com/CesiumGS/cesium/issues/13379 .
- Frontend GitHub Actions checks and separate Vitest/Playwright discovery.

## Database changes

Migration 0005_governance adds:

| Record | Relationships and purpose |
|---|---|
| workflow_events | Object, geometry, actor, optional validation job/review decision; ordered immutable before/after states |
| right_scopes | Recorded right → explicit related spatial object, actor and reason |
| property_annotations | Object, supporting evidence, actor; ordered immutable label/address/land-use revisions |

New history tables use RLS and database mutation-rejection triggers. The backend role receives only the required grants. ACCESS is added to the existing property_rights constraint. Existing spatial tables, indexes, source objects, rights and audit records are preserved.

The migration was applied to the isolated astra_test, astra_ui_test and existing local astra_demo databases. It is forward-only because historical records must be retained.

## API additions

Authenticated /api/v1/governance routes:

- GET /rules
- GET /objects/{object_id}
- POST /objects/{object_id}/annotations
- POST /right-scopes
- GET /review-queue
- GET /members (admin)
- POST /members/{member_id} (admin)

Existing /datasets, /evidence, /rights, /pipeline/changes, /pipeline/validate, /ulpin and /reviews routes execute the mutations behind the new UI. Updated OpenAPI is in docs/openapi.json.

## Data flow

Source/evidence → geometry revision with explicit CRS and heights → durable validation job → calculated findings and versioned rules → current Proposed 3D ULPIN → surveyor submission → separate officer decision → immutable workflow/audit/history → case report and 3D explorer.

A corrected geometry uses the current source prism when its old GLB snapshot is stale; it is never rendered as the superseded property mesh. Regenerate assets through the existing exporter when an updated bundle is needed.

## Verification performed

- 54 Python tests passed, including real PostGIS integration and Blender/GLB generation.
- Tests cover immutable workflow history, stale validation after rights changes, scoped access/restriction semantics, optimistic property metadata revisions, address search and the last-administrator guard.
- 2 frontend geometry/view unit tests passed.
- 3 Chromium browser tests passed against a production build: phase-three navigation/3D/2D/clipping/exploded views/reports, three target viewport sizes, and the complete phase-four lifecycle.
- The lifecycle uploads synthetic evidence, records a synthetic right, introduces a measured exclusive-volume overlap, corrects the footprint, revalidates, records the current proposed identity, submits for review, accepts as a separate officer and verifies preserved geometry, identity and audit records. A signed VIEWER token is rejected from the mutation API.
- Dependency audit returned zero reported vulnerabilities.
- Production build, JavaScript chunk parsing, Ruff, Black, mypy, TypeScript and ESLint were checked. No success is claimed for remote CI merely because a workflow file exists.
- Split/merge conservation and history are exercised by backend integration tests; their new UI controls have not received a separate automated browser scenario.

Screenshots: output/phase4-conflict.png and output/phase4-accepted.png.

## Limits and deferred work

P0/P1 prototype functionality is implemented. P2 infrastructure what-if and survey-dataset change detection remain explicitly deferred.

This is an explicit-height vertical-prism cadastral prototype, not an arbitrary-solid legal cadastre or photoreal reconstsruction. No real owner, official 3D ULPIN standard, model output, imagery or accuracy number is invented.

Live Supabase sign-in, cloud deployment and real Redis/Celery broker delivery remain unverified because the required Auth configuration and working Docker/Redis runtime were unavailable. Browser tests use the guarded test host with real signed JWT verification, real database/storage/processing, and substituted limiter/broker transport. It is outside the deployed application package.

Evidence upload retains and signature-checks the source; it does not claim malware scanning, document authenticity or OCR. Reports reflect provided records, not legal conclusions. Property case histories currently return the complete history for one property; pagination is future scaling work.

## Main files

Backend: app/governance_models.py, app/rules.py, app/services/workflow.py, app/routers/governance.py, app/services/{objects,records,validation,topology}.py, app/routers/workspace.py, app/models.py, app/schemas.py, app/main.py, migrations/env.py, migrations/versions/0005_governance.{py,sql}, scripts/freeze_governance.py, tests/test_integration.py.

Frontend: src/components/{governance,workspace,map3d}.tsx, src/app/globals.css, scripts/{cesium-assets,verify-build}.mjs, package.json, vitest.config.mjs, playwright.config.ts, tests/phase3.spec.ts, tests/phase4.spec.ts.

Documentation/configuration: docs/openapi.json, docs/PHASE_4_RUN.md, docs/PHASE_4_REPORT.md, README.md, .github/workflows/frontend.yml.

Run commands and environment requirements are in PHASE_4_RUN.md. No new external service or secret is required beyond the existing backend, Auth and frontend configuration.
