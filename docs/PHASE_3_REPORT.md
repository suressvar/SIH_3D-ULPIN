# Phase 3 verification checkpoint

Completed before beginning phase 4.

- Added a Next.js 15 App Router frontend with TypeScript, Tailwind, shadcn-style Radix button primitives, Lucide, Zustand and TanStack Query. Existing backend/database and Cesium stack were preserved.
- Added bounded, authenticated workspace overview, search, parcel scene and issue read models. Search covers stored labels, existing/proposed identifiers and explicit longitude/latitude. No street addresses or imagery are invented.
- Cesium loads real phase-two GLBs with object IDs and the exported ENU placement. Exploded floors transform the view only; clipping planes slice real GLB geometry. MapLibre renders source footprints in 2D. Missing elevation alignment is not silently guessed.
- Dynamic floors, unit inspection, evidence downloads, rights, validation highlights, source confidence, jobs, reports and selection use the same backend records.
- Low-end mode lowers resolution, suppresses labels/structural decoration and loads only ground-floor/underground GLB assets; other source footprints/prisms remain accessible. High-detail cross-section is disabled in low-end mode. Terrain and external basemaps are unconfigured.
- All six menus, global search, parcel/building/floor/unit selection, modes, exploded/slice changes, validation navigation, report generation, keyboard shortcut and 1366×768, 1440×900, 1920×1080 layouts were tested in Chromium.
- Browser tests: 2 passed. Geometry view unit tests: 2 passed. Backend regression tests: 50 passed, including real PostGIS and Blender exports. TypeScript, ESLint and Python typing checks passed. Next.js production build passed. Dependency audit: zero reported vulnerabilities with exact package versions and lockfile.
- Real browser testing caught and fixed MapLibre sizing, grid overflow, text encoding and stale build-cache problems. No page errors remained in the main browser scenario.

## Boundaries

The reference image was not present in the supplied attachments; the written visual requirements were used. The viewer presents actual cadastral volumes, not fabricated building facades.

Supabase configuration was not supplied. Sign-in integration exists; live Supabase sign-in was not tested. Browser verification uses a dedicated astra_ui_test database and locally signed expiring JWTs in an isolated test host. Normal JWT verification and RBAC execute. Only the Redis limiter and broker transport are substituted in that test harness, which is outside the application package and refuses non-test databases.

The existing Docker/Redis limitation still applies. No cloud deployment, multi-level mesh LOD, real terrain or photoreal reconstruction is claimed. GLBs are loaded per object; the exported 3D Tiles files remain available. Browser tests check view controls and geometry rendering; no accuracy or performance benchmark is claimed.

Screenshots are in output/phase3-workspace.png, output/phase3-exploded-section.png and output/phase3-building.png. Phase 4 continues from this verified checkpoint.
