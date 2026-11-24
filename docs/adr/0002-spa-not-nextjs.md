# ADR 0002: Vite SPA instead of Next.js

**Decision.** The frontend is a static React SPA built with Vite and served by nginx,
which also proxies `/api`.

**Why.** Everything is behind a login on a private network, so server rendering and
SEO buy nothing. A static bundle is simpler to self-host, makes a strict CSP easy,
works cleanly as an installable PWA with a service worker, and keeps the API on the
same origin (simple cookie + CSRF model).
