# Final run and judge demonstration

Run commands from the repository root in PowerShell. Preserve the existing databases and source storage. Do not reset or reseed by deleting records.

## Local dependencies and normal service startup

The existing Python 3.12 environment, Node dependencies, PostgreSQL 16/PostGIS 3.5 cluster and Blender 5.2 were used for verification. On a fresh machine, follow `README.md` and `PHASE_2_RUN.md` for installation and database provisioning. For containerized processing, use `compose.yaml` with `compose.processing.yaml`; the Linux Docker engine must work first.

Use the migration-owner connection only for migrations and fixture tools. The normal API and workers must use the restricted `astra_app` connection. Configure actual `SUPABASE_URL` and membership, `REDIS_URL`, `CORS_ORIGINS`, private storage, and the frontend API URL before normal authenticated operation. No test JWT is valid against a real Supabase project.

```powershell
$env:DATABASE_URL='postgresql+psycopg://astra@127.0.0.1:55439/astra_demo'
$env:BLENDER_EXECUTABLE='C:/Program Files/Blender Foundation/Blender 5.2/blender.exe'
./.venv/Scripts/python.exe -m alembic -c backend/alembic.ini upgrade head
./.venv/Scripts/python.exe -m app.judge_demo
```

This adds P001/B01 once, with original evidence and a deliberate conflict. Repeating the command preserves subsequent corrections/reviews. Earlier fixtures remain intact. All source coordinates, height references, parties and plan documents are synthetic. No AI inference is included.

Normal API command after configuring its restricted connection, actual authentication and Redis:

```powershell
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Run the Celery worker and scheduler using the existing Compose configuration. A missing broker leaves jobs queued; a missing shared rate limiter makes normal API requests return 503. The browser-test dispatcher below is an explicitly separate testing facility.

For the frontend, configure `frontend/.env.local` from its example, set `API_BACKEND_URL` to the normal backend, then:

```powershell
npm ci --prefix frontend
npm run build --prefix frontend
npm run start --prefix frontend
```

The production build copies/uses Cesium locally and verifies its browser scripts. A Next runtime or suitable proxy is required for the same-origin API forwarding.

## Repeatable browser verification on this machine

The browser tests use the existing `astra_ui_test` database, not `astra_demo`. Its corrections and reviews persist. Terminal 1:

```powershell
$env:DATABASE_URL='postgresql+psycopg://astra@127.0.0.1:55439/astra_ui_test'
$env:ENVIRONMENT='test'
$env:ASTRA_UI_TEST='1'
$env:SUPABASE_URL='http://127.0.0.1:8011'
$env:BLENDER_EXECUTABLE='C:/Program Files/Blender Foundation/Blender 5.2/blender.exe'
./.venv/Scripts/python.exe -m alembic -c backend/alembic.ini upgrade head
./.venv/Scripts/python.exe -m app.judge_demo
./.venv/Scripts/python.exe -m uvicorn ui_server:app --app-dir backend/tests --host 127.0.0.1 --port 8011 --log-level warning
```

Terminal 2, with port 3000 free and no simultaneous dev server using the same `.next` folder:

```powershell
$env:API_BACKEND_URL='http://127.0.0.1:8011'
npm run build --prefix frontend
npm run start --prefix frontend
```

Terminal 3:

```powershell
npm run e2e --prefix frontend
```

The final test prepares fresh version-matched assets through the actual API and job handler, reintroduces a disclosed test conflict if necessary, corrects it and records a new separate-officer decision. It does not delete history. Old phase-three/four fixtures must already exist for those older tests; their preparation is documented in `PHASE_2_RUN.md`.

The browser host creates short-lived signed sessions in ignored `data/ui-test/sessions.json`. Tests read them automatically. For a manual **local test** demonstration, use its surveyor token in “Use an existing access token”, and a separate browser session with its officer token for review. Never publish session files or traces containing them. Restarting the host rotates the test signing key. The host cannot start without its explicit test environment/database guard. It substitutes only Redis rate limiting/delivery, while JWT verification, DB membership, data, processing and assets remain real.

## Judge story

1. Search **DEMO26011P0001**, explicitly a synthetic parent reference.
2. Open P001 in 2D, select B01, switch to 3D and rotate/zoom.
3. Select F3 and A-302 to inspect a Proposed 3D ULPIN and root parcel relationship.
4. Select A-301 → **Property case** → inspect/download the illustrative source plan.
5. **Run validation** → inspect the measured overlap and **Show affected geometry**.
6. **Correct boundary** using `output/judge-demo/corrected-A301.geojson`, evidence and a reason. The JSON is source geometry input, not a hardcoded browser outcome.
7. Revalidate, record the current Proposed 3D ULPIN and submit for review.
8. A different officer selects the case from the review queue or search, records a reason and **Accept prototype**.
9. Browse workflow, audit and geometry-version history. Acceptance has no legal title effect.
10. Select B01 → exploded floors → B1 parking. Use Low-end mode to show 2D. A completely WebGL-free browser uses the source-footprint SVG fallback.

After geometry changes, previous generated bundles remain available historically. Regenerate current assets through `/pipeline/jobs` with `kind=EXPORT_ASSETS`, parcel ID and the explicit visualization elevation offset. The non-production synthetic fixture CLI is also available:

```powershell
./.venv/Scripts/python.exe -m app.refresh_assets 6feb850d-eba0-5836-865a-bd8cc84fcae6
```

## Checks and audit artifacts

```powershell
$env:TEST_DATABASE_URL='postgresql+psycopg://astra@127.0.0.1:55439/astra_test'
./.venv/Scripts/python.exe -m pytest backend/tests -q
./.venv/Scripts/python.exe -m ruff check backend
./.venv/Scripts/python.exe -m black --check backend
./.venv/Scripts/python.exe -m mypy --config-file backend/pyproject.toml backend/app
npm run lint --prefix frontend
npm run typecheck --prefix frontend
npm test --prefix frontend
./.venv/Scripts/python.exe -m app.integrity
./.venv/Scripts/python.exe -m app.benchmark_reads
```

The last two commands are read-only and inspect the database in `DATABASE_URL`. The benchmark requires the named judge property and an officer record. It reports local read/encoding timings, query count and response size; it does not measure cloud capacity. JSON outputs and screenshots are in `output/`.

## Final audit file map

- Backend: `db.py`, `main.py`, `repositories.py`, `governance_models.py`, governance/pipeline/workspace routers, `services/exports.py`, migration `0006_read_indexes.py`.
- New supporting tools: `judge_demo.py`, `refresh_assets.py`, `integrity.py`, `benchmark_reads.py`.
- Frontend: API helper and store, workspace/governance, 2D/3D viewers and fallback styling.
- Tests: backend integration/security tests, API timeout tests and `frontend/tests/final.spec.ts`; old browser assertions updated to current UI and persisted asset versions.
- Documentation: final plan/report/runbook, regenerated OpenAPI, README, secret/test-artifact ignore rules.

No repository reset, cloud publishing, new external service or technology replacement was performed.
