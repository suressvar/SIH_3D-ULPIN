# Run the phase-two pipeline

Use Python 3.12 and the existing PostgreSQL/PostGIS setup. Run commands from the repository root. The example .env documents the original service ports; the isolated test runtime on this machine uses port 55439.

## Dependencies

```powershell
./.venv/Scripts/python.exe -m pip install -r backend/requirements.lock
./.venv/Scripts/python.exe -m pip install --no-deps -e backend
npm ci --prefix tools/gltf
```

Install Blender separately. The local verified executable is:

```powershell
$env:BLENDER_EXECUTABLE='C:/Program Files/Blender Foundation/Blender 5.2/blender.exe'
```

Node must be on PATH or set NODE_EXECUTABLE. GLTF_VERIFY_SCRIPT normally resolves to tools/gltf/verify.mjs. SegFormer/PointNet++ weights are optional; leave configuration empty when absent. A blank SEGFORMER_BUILDING_CLASS should be omitted, not assigned an empty integer value.

## Existing isolated database on this machine

Start only the project's existing cluster if stopped:

```powershell
& './data/test-runtime/pgsql/bin/pg_ctl.exe' -D './data/test-runtime/cluster-v2' -l './data/test-runtime/postgres.log' -o '-p 55439 -h 127.0.0.1' -w start
$env:DATABASE_URL='postgresql+psycopg://astra@127.0.0.1:55439/astra_demo'
./.venv/Scripts/python.exe -m alembic -c backend/alembic.ini upgrade head
./.venv/Scripts/python.exe -m app.demo_pipeline --output output/phase2-demo
./.venv/Scripts/python.exe -m app.verify_demo
```

This admin connection is for the isolated fixture/migration tools. Use the configured astra_app database role for the application server. Do not expose this local trust-authenticated test database to the network.

The demo already exists. Repeating the demo command materializes its saved bundle without duplicating cadastral records. An unfinished demo is explicitly reported rather than silently deleted. Inspect its jobs before any recovery.

On another machine, create a dedicated PostgreSQL database and backend role using the phase-one instructions, set DATABASE_URL to it, and run the same migrations/demo commands. The bundled test-runtime directory is machine-local and ignored by Git.

## API and asynchronous worker

Configure the usual DATABASE_URL, REDIS_URL, SUPABASE_URL, JWT_AUDIENCE, CORS_ORIGINS and storage settings from .env.example.

```powershell
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# Separate terminals, when Redis is running:
./.venv/Scripts/python.exe -m celery -A app.worker.celery_app worker --pool=solo --loglevel=INFO
./.venv/Scripts/python.exe -m celery -A app.worker.celery_app beat --loglevel=INFO
```

Windows uses the solo worker pool. Heavy GPU work belongs in the planned Linux workstation/container environment. The dispatcher submits durable queued jobs; result state resides in PostgreSQL.

Authenticated routes require a real Supabase JWT and active local RBAC membership. Synthetic CLI actors are inactive; there is no demo login bypass. Swagger documentation is at /docs.

When Docker is repaired, the optional Blender worker override is:

```powershell
docker compose -f compose.yaml -f compose.processing.yaml up --build
```

This override is supplied but not verified by a container build on this host. Migrate with the administrative connection as described in the phase-one README before serving application requests.

## Tests

```powershell
$env:TEST_DATABASE_URL='postgresql+psycopg://astra@127.0.0.1:55439/astra_test'
$env:BLENDER_EXECUTABLE='C:/Program Files/Blender Foundation/Blender 5.2/blender.exe'
./.venv/Scripts/python.exe -m pytest backend/tests -q -p no:cacheprovider
./.venv/Scripts/python.exe -m ruff check backend
./.venv/Scripts/python.exe -m black --check backend
./.venv/Scripts/python.exe -m mypy --config-file backend/pyproject.toml backend/app
./.venv/Scripts/python.exe -m pip check
```

PostGIS tests require the dedicated astra_test database and roll back their records. The real export test skips explicitly when Blender/Node tools are missing; never count a skipped export as a successful asset test.

## New environment settings

BLENDER_EXECUTABLE, NODE_EXECUTABLE, GLTF_VERIFY_SCRIPT configure real asset tooling. SEGFORMER_WEIGHTS, SEGFORMER_BUILDING_CLASS, POINTNET_WEIGHTS configure optional locally supplied model adapters. MAX_RASTER_PIXELS, MAX_POINT_COUNT and MAX_VERTICAL_EXTENT_M bound processing. Existing upload, auth, database and storage settings remain required as appropriate.

The current output is actual cadastral volumes and metadata. A Cesium application UI, detailed building appearance, multi-level LOD, trained-model inference and cloud deployment are not included in this phase.
