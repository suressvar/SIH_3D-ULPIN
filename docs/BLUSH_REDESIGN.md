# Blush UI redesign

Palette: #FFF5F5 (canvas), #F7D6D0 (selected surfaces), #E2B4BD (borders and accents), #4A4A4A (text and primary actions). Severity colours remain distinct for validation issues.

Design references:
- https://dribbble.com/shots/27467616-Real-Estate-Dashboard-Design — property dashboard hierarchy and cards.
- https://www.awwwards.com/inspiration/pastel-scroll-project-page — restrained pastel editorial direction.

Changed the login composition and application-wide presentation: navigation, cards, forms, tables, property context, inspector tabs, governance controls, reports and settings. Login artwork is an abstract decorative illustration, not a survey or property reconstruction. Cesium geometry, API operations and role verification remain unchanged.

Local credentials are unchanged. Use the existing email/password form or the advanced access-token option. Unconfigured social-provider buttons are no longer advertised.

The theme is isolated in frontend/src/app/blush.css, loaded after existing structural styles. It preserves the existing GIS layout and responsive viewer controls. Screenshot and navigation checks are in frontend/tests/blush.spec.ts.

Verified: production build (including TypeScript and lint), 7 unit tests, both demo role logins, desktop/mobile menu checks, and real exterior/floor/zoom/download browser test. Populated-page screenshots reviewed in output/blush; spatial view in output/reference-redesign/dashboard.png.
