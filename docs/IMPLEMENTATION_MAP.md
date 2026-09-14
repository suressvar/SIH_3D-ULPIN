# Phase one implementation map

Inspection on 2026-09-12 found only `.git` metadata. No source, API, database configuration, package manifest, environment file, UI, 3D implementation, or applicable AGENTS.md was present. No working code is being replaced. The proposal DOCX was read; architecture and dashboard references are available in the conversation, not as repository assets.

This phase creates a Python package managed by pip with a checked-in resolved requirements lock, FastAPI services and PostGIS persistence. Alembic is introduced because the empty repository had no migration system. Next.js 15, CesiumJS and the rest of the specified frontend stack remain reserved for the subsequent frontend phase.

## Domain decisions before coding

- SpatialObject is a typed supertype: PARCEL, BUILDING, FLOOR, UNIT, UNDERGROUND, SHARED, EASEMENT, INFRASTRUCTURE. This avoids duplicating geometry, rights and audit columns across eight tables.
- Every non-parcel has a parent and a root parcel. Database triggers check parent type and root consistency; cross-parcel affected relationships are explicit separate links, not a second ownership hierarchy.
- GeometryVersion stores PostGIS 2D footprints in EPSG:4326 plus a metric projected footprint and optional POLYHEDRALSURFACEZ shell. Height reference and bounds are separate. Only explicitly bounded vertical prisms are supported initially. No generic solid validity claim.
- SourceDataset records original bytes, hash, validation status, format and inspection metadata. Failed ingestion retains source and rejection details.
- Rights refer to a spatial object and evidence; they are recorded assertions, not adjudicated title. Shared spaces and easements are first-class object kinds.
- Immutable geometry versions, evidence and audit records preserve history. Reviews reference the exact geometry version and require fresh validation before acceptance.
- Celery jobs are persisted before dispatch; a dispatcher polls queued rows, making broker outages recoverable. Workers claim jobs atomically and never mark incomplete work completed.
- Supabase verifies identity with asymmetric JWT signing keys; roles come from a server-managed local user table, never user_metadata. No authentication bypass or demo login endpoint.
- API data stays in private `cadastre` schema, with least-privilege runtime database role. No browser direct database access.

## Vertical slice

GeoJSON bytes -> durable source -> queued ingestion -> format/CRS/geometry validation -> parcel + geometry + provenance -> API reads. Manual surveyed/estimated footprints with explicit height metadata -> projected prism shell -> queued validation -> issue records -> proposed identity -> evidence/rights -> review -> append-only audit. No AI output or GLB asset is invented.

## Deliberately deferred

Cesium/Next.js UI; GLB/3D Tiles rendering and streaming; AI model execution/training; point clouds; raster processing; automated floor-plan extraction; arbitrary non-prismatic solids; external government integration; cloud deployment. Capability API reports these unavailable. The required tools for these stages remain the proposal stack, not substitute services.
