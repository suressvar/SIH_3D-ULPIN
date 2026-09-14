# Final audit implementation map

Preserve the existing stack and phase 1–4 modules. Audit order: API/storage failure handling → bounded database reads → viewer streaming/fallback and low-end behavior → a reproducible synthetic judge property → integrity/security/performance checks → full tests → final engineering report.

Confirmed findings:
- Property case history is unbounded and repeatedly downloads all geometry versions; change-member reads use an N+1 loop.
- Current-geometry lookup builds its distinct-version subquery across all parcels.
- Browser requests have no timeout; downloads have no explicit same-origin restriction.
- Cesium failure states offer manual recovery, while MapLibre can itself fail when WebGL is absent.
- Normal 3D loads all per-object GLBs; the existing generated 3D Tiles 1.1 manifest is not used for streaming.
- Live Docker Linux engine remains unavailable (read-only elevated check confirmed); do not claim real Redis transport verification.
- No trained AI checkpoint or reference dashboard image has been supplied. Preserve truthful capability reporting; do not fabricate an AI output or claim reference-image comparison.

Existing APIs, auth, spatial calculations, geometry versioning, evidence, review, immutable audit and generated assets will be reused. No new external service or unrelated feature is planned.

Completed local audit: see FINAL_ENGINEERING_REPORT.md for the implemented fixes, actual verification and unresolved external dependencies.
