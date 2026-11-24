# Changelog

All notable changes are documented here. The project follows semantic versioning
once it reaches 1.0.

## [0.1.0] - unreleased

First version.

- Name: Schnäppli (Swiss German for a real bargain), with the winking-ä logo.
- Appearance settings: light, dark or system theme; five accents; larger text;
  compact spacing; reduce motion; photo cards or compact rows; photos on/off;
  start page; which sections Home shows; the four phone tabs.
- Own pickers instead of the platform's select wheels, with a filter for long lists.
- API keys, setup tokens and invite codes no longer trigger password autofill.
- Faster navigation: page code is preloaded, the app frame stays put while a page
  loads, and resized listing photos are cached on the server.

- Natural-language search creation with clarifying questions and a review step.
- Multiple independent searches with schedules, sources, alerts, history; pause,
  resume, duplicate, archive, complete, delete.
- eBay Browse API adapter; add any listing by link (robots.txt respected).
- AI analysis with structured output (Anthropic, OpenAI, Gemini), photo checks,
  deterministic Deal Score with itemised breakdown, market value blending with
  comparable asking prices, price history and price-drop detection.
- Telegram linking with one-time codes, instant alerts, price drops, usage warnings,
  search failure notices, daily digests (long polling).
- Wishlist with accessories and inherited compatibility; monthly budget ledger.
- AI usage analytics and spending limits checked before every call.
- Shopping assistant chat scoped to the user's own data.
- Claude Code bridge: the admin can use their own Claude plan via the unmodified `claude` CLI on their machine (own account only).
- Transparent, resettable learning from feedback.
- Argon2id, server-side sessions, CSRF, rate limits, lockout, AES-GCM encrypted keys,
  setup token, invite-only registration, network allowlist, audit log, data export,
  account deletion.
- Installable PWA with offline reading of loaded data; signed image proxy; strict CSP.
- Docker Compose deployment with health checks, non-root read-only containers,
  automated daily database backups.
