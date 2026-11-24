# Architecture

Schnäppli is a modular monolith: one backend codebase, run as two processes (the API
and a background worker), plus a static web app.

```
            browser / iPhone PWA
                     │ HTTPS (your reverse proxy, private network / VPN)
              ┌──────▼──────┐
              │  web (nginx)│  static SPA, strict CSP, proxies /api
              └──────┬──────┘
                     │
              ┌──────▼──────┐          ┌─────────────┐
              │ api (FastAPI)│◄────────►│ PostgreSQL  │
              └──────┬──────┘          └─────────────┘
                     │ enqueue                ▲
              ┌──────▼──────┐                 │
              │    Redis    │◄──────┐         │
              └─────────────┘       │         │
                             ┌──────┴──────┐  │
                             │ worker (arq) │─┘
                             └──────┬──────┘
          outbound only: AI providers, eBay API, Telegram (long polling), listing images
```

## Backend modules (`backend/app`)

| Module | Responsibility |
| --- | --- |
| `core/` | config, database, security (Argon2id, AES-GCM, client IP), rate limiting, safe outbound HTTP, logging with redaction, job queue |
| `models/` | SQLAlchemy models: users & sessions, searches, listings, matches, analyses, wishlist, purchases, AI usage, credentials, Telegram, notifications |
| `api/` | HTTP endpoints; every query is scoped to the signed-in user |
| `ai/` | provider adapters (Anthropic, OpenAI, Gemini), model catalogue & prices, the **gateway** (credential choice, budget check, usage recording), prompts & schemas |
| `sources/` | marketplace adapters (eBay Browse API, add-by-link) and the honest registry of unsupported sources |
| `services/` | search runner, listing upsert & dedupe, analysis, scoring, scheduling, digest, notifications, Telegram, learning, geo |
| `worker.py` | arq jobs and the per-minute scheduler tick; runs the Telegram poller |

## The three independent jobs

1. **Search run** (`run_search_job`): queries each enabled source with the search's
   terms, upserts listings (deduplicated by source + external id), records price
   changes, creates matches and applies the free pre-filter. No AI.
2. **Analysis** (`analyze_match_job`): one AI call per new match, limited per run
   and by the user's budget. Results are cached by a hash of the listing content
   *without its price* plus the search spec, so a price change only rescores.
   Photos are checked only for promising listings.
3. **Digest** (`digest_job`): summarises existing scores. It never analyses
   listings; an optional short AI intro is one small call.

A cron tick every minute enqueues due searches (per-search schedules, user
timezone, DST-safe) and digests.

## Deal Score

The model returns structured facts (relevance, condition, included items, red
flags, a market range with basis and confidence). `services/scoring.py` turns them
into a score:

- base points from the effective price vs. estimated market value
  (blended with asking prices of comparable listings once there are three or more),
- adjustments for condition, alternatives vs. exact matches, bundles, unmet
  requirements, red flags, photo findings, budget and pickup distance,
- learned preferences (at most ±10),
- low confidence pulls the score towards 50,
- labels: exceptional ≥85, good ≥70, fair ≥50, overpriced below; *risky* overrides
  when the price is implausibly low, information is missing, or the listing text
  tried to manipulate the assessment.

## Frontend (`frontend/`)

React 19 + Vite + Tailwind 4, TanStack Query, React Router, Radix primitives for
dialogs and menus. Installable PWA (service worker via vite-plugin-pwa): the app
shell is precached, previously loaded API data is readable offline
(network-first), listing photos are cached. Fonts are bundled; the browser makes no
third-party requests. Listing photos come through the backend's signed,
authenticated image proxy.

## Decisions

See [adr/](adr/) for the reasoning behind the main choices.
