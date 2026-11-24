# Implementation status

Last updated 2026-11-24 (v0.1.0). Legend: ✅ done and tested ·
🟡 implemented, not yet verified against the real external service · 🟠 partial ·
⬜ not started.

## Verification notes

- Backend: 56 automated tests (auth, authorization/isolation, security, scoring,
  scheduling incl. DST, the full search → analysis → score → feedback → budget →
  digest pipeline with a fake AI provider and fake marketplace).
- The Claude Code bridge was verified end-to-end with a real Claude plan (text, structured output, photos).
- Other external services were **not** called with real credentials yet: no AI key, eBay key
  or Telegram bot was available during development. Those paths are marked 🟡.
- UI checked by screenshots at 402×874 (iPhone 16 Pro) and 1440×900 with demo data,
  not yet on a physical iPhone.

## Product

| Area | Status | Notes |
| --- | --- | --- |
| Natural-language search creation, clarifying questions, review & edit, confirm | ✅ / 🟡 | Flow tested with fake AI; real model output not yet seen |
| Flexible alternatives with reasons | ✅ / 🟡 | Prompted + schema field; quality depends on the model |
| Multiple searches: edit, duplicate, pause/resume, archive, complete, delete | ✅ | |
| Per-search schedule (default/custom/interval), timezone + DST | ✅ | |
| Search runs, dedupe, price history, price-drop detection | ✅ | |
| Free pre-filter (excluded words, wanted ads, over budget, condition) | ✅ | |
| AI quick scan, deep analysis, photo check | ✅ / 🟡 | Real provider calls untested |
| Deal Score with breakdown, labels incl. risky | ✅ | |
| Market value: AI estimate blended with comparable asking prices | ✅ | No sold-price source exists among the supported sources |
| Effective price incl. shipping (estimated where unknown) | ✅ | Swiss parcel estimate CHF 9 |
| Pickup distance from postal code (offline swisstopo table) | ✅ | Switzerland only |
| Wishlist with accessories, inherited compatibility, search from item | ✅ | |
| Accessory searches generated automatically from a main search | ⬜ | Manual via wishlist today |
| Bundle detection | 🟠 | Relevance "bundle" + score bonus; no per-item valuation |
| Monthly budget: bought / planned / interested, categories, history | ✅ | |
| Telegram: linking, alerts, price drops, warnings, failures, digests | ✅ / 🟡 | Logic tested; real bot not yet connected |
| Digest content: new count, best offers, drops, ending soon, savings | ✅ | |
| AI usage analytics (provider/model/task/search/day, per listing, per deep) | ✅ | Costs are estimates by design |
| Spending limits checked before calls, warnings, auto-pause | ✅ | |
| BYOK + shared admin keys, test connection, model per task | ✅ / 🟡 | |
| Claude Code bridge (admin's own plan, own account only) | ✅ | Verified live 2026-11-24: interpretation, listing analysis incl. injection flag, photo check, from the production container |
| Model capability metadata (vision) | ✅ | |
| Shopping assistant chat (own data only, listing refs) | ✅ / 🟡 | |
| Learning from feedback, transparent, resettable | ✅ | Simple feature weights |
| Favorites, rejected, purchased, notes | ✅ | |
| Similar listings (same identified product) | ✅ | |
| Expiring offers | 🟠 | Uses end time when the source provides it (eBay auctions) |

## Sources

| Source | Status |
| --- | --- |
| eBay Browse API | 🟡 implemented, needs keys; EBAY_CH search coverage to verify |
| Add by link (JSON-LD/OpenGraph, robots.txt) | ✅ parser tested; live sites vary |
| Your own shops (schema.org / WooCommerce, robots.txt) | ✅ implemented + tests; most big CH retailers close search to programs |
| Galaxus / Digitec (official MCP) | ✅ verified live 2026-11-24 |
| Ricardo, tutti.ch (inbox adapter for alert e-mails) | 🟡 implemented and tested with synthetic mails; real alert layouts to verify |
| Facebook, Interdiscount, Toppreise | shown as unsupported with reasons |
| Amazon PA-API | ⬜ planned |

## Platform

| Area | Status | Notes |
| --- | --- | --- |
| Auth: Argon2id, sessions, CSRF, rate limits, lockout, setup token, invites | ✅ | |
| User isolation | ✅ | Tested per resource |
| Encrypted API keys (AES-GCM, rotation) | ✅ | |
| Log redaction, safe errors, audit log | ✅ | |
| SSRF-safe fetching, signed image proxy | ✅ | DNS-rebinding window documented |
| Prompt-injection containment | ✅ | Tested that listing text can't break the fence |
| Data export, account deletion | ✅ | |
| PWA: manifest, icons, iOS splash, safe areas, offline reading | ✅ / 🟠 | Not tested on a physical device yet |
| Responsive layouts (phone bottom nav, desktop sidebar, ⌘K palette) | ✅ | Screenshot-checked |
| Dark mode, accents, text size, density, layout choices | ✅ | Settings → Appearance; stored per user, applied before first paint |
| Translations | ⬜ | English UI |
| Two-factor auth | ⬜ | |
| Frontend automated tests | ⬜ | vitest configured, no tests yet |
| Docker Compose, health checks, non-root read-only containers | ✅ | |
| DB backups + restore | ✅ | Interval dumps with integrity check and catch-up after downtime; restore tested into a scratch database |
| Crash recovery and outage report | ✅ | Heartbeat, interrupted runs restarted, missed digests sent late, admin report |
| CI (lint, tests, build, gitleaks) | 🟡 | Workflow written, runs once the repo is on GitHub |
