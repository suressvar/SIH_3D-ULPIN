# Phase one implementation report

## A. What existed before

Only Git metadata. No frontend, backend, package manager configuration, API, database schema, 3D code or environment file existed. Nothing working was replaced. The proposal DOCX and conversation architecture/dashboard references informed the design. This phase follows the user's foundation scope; it does not build a cosmetic dashboard.

## B. What changed

Created a FastAPI Python package, private PostGIS schema, typed SQLAlchemy/GeoAlchemy2 models, two Alembic migrations, Pydantic contracts, geometry services, private source storage, GeoJSON ingestion, persisted Celery jobs, validation findings, proposed identities, evidence/rights, review decisions, audit history, Supabase JWT verification and backend-managed RBAC.

Added local Docker Compose configuration, dependency lock, CI checks, deterministic synthetic seed, a sample GeoJSON file, tests and architectural documentation. A local ignored .env was copied from the example; it contains no Supabase or R2 credentials.

## C. Database schema

Thirteen domain tables:
app_users, spatial_objects, spatial_relationships, source_datasets, geometry_versions, evidence, property_rights, processing_jobs, validation_issues, ulpin_identities, review_cases, review_decisions, audit_events.

SpatialObject represents Parcel, Building, Floor, PropertyUnit, UndergroundSpace, SharedSpace, Easement and InfrastructureSpace by constrained kind. Parent/root foreign keys and triggers preserve hierarchy. This is an explicit supertype design, not missing tables for those entities.

Geometry uses PostGIS Polygon footprints and optional POLYHEDRALSURFACEZ shells with GiST indexes, rather than JSON geometry storage. Heights, CRS, provenance and immutable versions are maintained separately. Details: [architecture](ARCHITECTURE.md).

## D. API structure

37 OpenAPI paths, grouped by auth, parcels, buildings, floors, units, underground, shared spaces, easements, infrastructure, geometry, 3d, datasets, processing, validation, identities, evidence, rights, reviews and audit.

Routers call services; services use repositories and spatial utilities; database sessions delimit transactions. Responses use Pydantic schemas. There is no invented government endpoint or fake login.

The /3d endpoint returns actual persisted geometry/provenance for a future viewer; it does not claim to generate GLB or 3D Tiles. [Machine-readable contract](openapi.json).

## E. Data flow

Uploaded original bytes -> private object storage and dataset record -> queued processing row -> Redis/Celery dispatch -> validated GeoJSON -> parcel/geometry/provenance -> explicit-height volume creation -> queued prism validation -> findings and geometry snapshot -> Proposed 3D ULPIN -> rights/evidence -> review -> append-only history -> API.

Unsupported AI, raster and point-cloud processing is explicitly unavailable. PDF/PNG/JPEG upload is evidence storage only.

## F. Files created or modified

All tracked source files are new. Principal locations:

| Location | Contents |
|---|---|
| backend/app/models.py | Domain schema and spatial columns |
| backend/app/schemas.py | Pydantic API contracts |
| backend/app/routers/ | Resource endpoints |
| backend/app/services/ | Object, geometry, ingestion, validation and review logic |
| backend/app/spatial.py | CRS transformation, canonical geometry hashing and prism mathematics |
| backend/app/auth.py | JWT validation and RBAC |
| backend/app/storage.py | Local development and R2 private storage |
| backend/app/worker.py | Persisted dispatch, worker state transitions and interruption handling |
| backend/app/seed.py | Idempotent synthetic fixture |
| backend/app/manage.py | Administrator membership provisioning |
| backend/migrations/ | Frozen initial schema and provenance-hardening migration |
| backend/tests/ | Local and real PostGIS tests |
| backend/fixtures/demo-parcel.geojson | Synthetic sample upload |
| backend/requirements.lock | Resolved Python dependency versions |
| compose.yaml, infra/init-db.sql | Local database/Redis/API/worker setup |
| .github/workflows/backend.yml | CI definition |
| README.md, docs/ | Runbook, architecture, implementation map and contracts |

The ignored data/test-runtime directory holds a temporary native PostgreSQL/PostGIS test environment. It is not application source or a production deployment.

## G. Commands required to run

Complete copyable commands are in [README](../README.md). Main sequence:

1. Copy .env.example to .env and configure real Supabase settings.
2. docker compose up -d db redis
3. docker compose build
4. Run Alembic upgrade head with the administrator database URL.
5. Run python -m app.seed with the administrator database URL.
6. Provision actual Supabase user membership with python -m app.manage.
7. docker compose up -d api worker scheduler
8. Open http://localhost:8000/docs and supply a valid Supabase user bearer token.

Only health and capability routes work without sign-in. No frontend is present yet.

## H. Environment variables

DATABASE_URL, REDIS_URL, ENVIRONMENT, CORS_ORIGINS, SUPABASE_URL, JWT_AUDIENCE, STORAGE_BACKEND, STORAGE_ROOT, R2_ENDPOINT, R2_BUCKET, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, MAX_UPLOAD_BYTES, REQUESTS_PER_MINUTE.

TEST_DATABASE_URL is used only by the integration tests. See [.env.example](../.env.example) and the README environment table. Supabase and R2 credentials are not supplied or invented.

## I. What is genuinely functional and verified

- Coordinate transformation, explicit vertical bounds and canonical geometry hashing.
- Input rejection without silent repair or loss of original uploaded bytes.
- PostGIS migrations and actual storage of closed 3D prism shells.
- Parent hierarchy checks and source/geometry/audit immutability.
- Persistent synthetic seed: one parcel, one building, three floors, six apartments, one shared corridor and one basement.
- Real geometric overlap findings, including the seeded 51 cubic metre overlaps.
- Passing validation required for proposed identities and review.
- Geometry changes invalidate stale validation snapshots.
- Separate submitter/reviewer requirement and persistent review decisions.
- API reads of persisted 3D geometry and synthetic rights.
- Actual queued-job cancellation and duplicate-handler delivery protection.
- Runtime database role permits expected writes while blocking history tampering.
- JWT signature, issuer, audience and expiry checks using locally generated test keys; backend role checks.

Local tests and PostGIS integration tests pass. Cloud credentials and Redis broker transport are not substituted with simulated success.

## J. Intentionally deferred or not verified

- Next.js/Cesium UI and realistic rendered materials/terrain: deferred to frontend/3D phase.
- GLB, 3D Tiles 1.1 and structural metadata assets: deferred, capability marked unavailable.
- AI models, model weights, LiDAR, DEM/DSM processing, floor-plan extraction: deferred adapters.
- Live Supabase authentication and R2 access: implemented foundations, not verified against an account.
- Celery worker through a live Redis broker and Docker image build: not yet verified because Docker Desktop fails to start. Worker business handlers and durable job records are tested against real PostGIS.
- Cloud deployment, HTTPS ingress, distributed monitoring, load tests and frontend tests: deferred.
- Arbitrary 3D solids, gap detection, cross-parcel conflict analysis and legal adjudication: outside this phase's validation scope.
- Membership tenancy: one project team per deployment; not a multi-tenant service.
- Relationship table is available as schema; split/merge and cross-parcel relationship management APIs are deferred.

## K. Technical risks and verification evidence

Verification used an isolated PostgreSQL 16 / PostGIS 3.5.3 runtime in the ignored project data folder after Docker Desktop crashed at its dockerInference socket. The installed system database was not modified.

Checks: 33 tests passed, including eight tests exercising real PostGIS. Ruff, Black and mypy passed; pip check found no broken requirements. Docker Compose configuration validation passed. The isolated test database was stopped after verification. Two upstream TestClient deprecation warnings remain; they do not indicate failing application tests.

- The initial runtime database role must exist before migration grants/policies are applied; Compose provisions it. Hosted configuration needs equivalent explicit provisioning.
- Celery jobs use coarse real progress stages; running cancellation is not implemented.
- Original files live outside database transactions. A failed database registration can leave an unreferenced private object; garbage collection is future work.
- Evidence signature checks are not malware scanning or approval verification.
- Vertical references must match before comparisons. A projected horizontal SRID does not identify the vertical datum.
- Unit conflicts are potential spatial conflicts for review, not ownership judgments.
- Proposed identity is stable by object UUID. Canonical geometry hash tracks revisions separately.
- Dependency versions are locked, but Docker/platform installation and deployed-service checks remain necessary.
- No tested geometry or synthetic ownership assertion is claimed to represent a real property.
