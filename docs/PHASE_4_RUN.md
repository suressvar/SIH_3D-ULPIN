# Phase 4 run and judge walkthrough

Use the existing phase-two backend and data; do not recreate the repository or clear its database. See PHASE_2_RUN.md for PostGIS, storage, Blender and worker setup.

## Apply the governance migration

Run from the repository root with DATABASE_URL set to the intended database's migration-owner connection:

```powershell
./.venv/Scripts/python.exe -m alembic -c backend/alembic.ini upgrade head
```

Migration 0005 adds append-only workflow events, evidence-backed property annotations and explicit right scopes; it adds ACCESS to the recorded-right vocabulary. Existing records remain intact. Old validation snapshots require revalidation under ASTRA-PRISM-3. There is no fabricated backfill of old workflow events.

Use the restricted astra_app connection for the normal API and worker, not the migration owner.

## Frontend

```powershell
npm ci --prefix frontend
Copy-Item frontend/.env.example frontend/.env.local
npm run dev --prefix frontend
```

Edit frontend/.env.local with API_BACKEND_URL and the actual NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY. Provision existing Supabase identities as project members using the existing app.manage CLI. The advanced access-token form also uses normal backend JWT verification.

The normal API, Redis, Celery worker and scheduler must run. Unavailable workers leave jobs queued; the UI does not manufacture completion.

For a production build:

```powershell
npm run build --prefix frontend
npm run start --prefix frontend
```

Cesium's pinned browser distribution is copied locally during npm installation and loaded only when opening 3D. It is not fetched from a CDN. The post-build parser checks application chunks and Cesium for invalid JavaScript.

## Connected walkthrough

1. Find the synthetic source pipeline parcel through global search.
2. Explore its building, five floors, units, shared circulation and basement.
3. Select a unit and expand **Property case**.
4. As a surveyor, upload evidence and record a provided right. Optionally scope access/shared rights to a specific related space.
5. Use **Correct boundary** to submit source longitude/latitude polygon coordinates and explicit vertical limits with evidence and a reason. This records a new draft and preserves the previous geometry.
6. Run validation and inspect calculated conflicts, measured overlap, rule definition and source evidence. **Show affected geometry** uses the actual stored intersection.
7. Correct the source boundary and revalidate. Record the **Proposed 3D ULPIN** for the current geometry.
8. Submit for review. A different officer opens the case from **Validation → Officer review queue**, records a reason, and accepts the prototype or returns it for correction.
9. Inspect workflow transitions, reviewer decisions, before/after geometry IDs and identity versions. Acceptance does not certify legal title.
10. Open Reports for structured property, validation, provenance, review and change-history reports. Download JSON or print.

Split divides a unit at its footprint's centre longitude; merge requires adjacent units on the same floor. The backend checks area conservation, vertical compatibility and optimistic geometry versions. Neither action transfers rights automatically. Non-rectangular results that cannot form single polygons are rejected explicitly.

## Verification

```powershell
./.venv/Scripts/python.exe -m ruff check backend
./.venv/Scripts/python.exe -m black --check backend
./.venv/Scripts/python.exe -m mypy --config-file backend/pyproject.toml backend/app
./.venv/Scripts/python.exe -m pytest backend/tests -q
npm run lint --prefix frontend
npm run typecheck --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
```

PostGIS tests require TEST_DATABASE_URL ending in /astra_test; otherwise integration tests are skipped explicitly.

The browser tests require the guarded backend/tests/ui_server.py host, a dedicated astra_ui_test database seeded with the phase-two fixtures, and frontend API_BACKEND_URL=http://127.0.0.1:8011. That host requires ENVIRONMENT=test and ASTRA_UI_TEST=1. It writes temporary signed JWTs to ignored data/ui-test/sessions.json; do not publish that file.

The browser host executes actual JWT verification, RBAC, PostGIS, file storage and processing algorithms. Only Redis request limiting and broker delivery are substituted by the test harness. It is not a deployment authentication mode.

```powershell
npm run e2e --prefix frontend -- phase3.spec.ts phase4.spec.ts
```

GitHub Actions now includes frontend lint, typing, unit tests, production build and script parsing. Remote CI execution is separate from local verification.
