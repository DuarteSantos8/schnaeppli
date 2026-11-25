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
- Setup guide in the browser (`/setup`): AI, postal code, your mailbox for Ricardo
  and tutti, saved searches with one-click links, Telegram, eBay key (admin), shops.
  Each step tested on the spot.
- Connect your own mailbox for Ricardo / tutti alerts: no extra mailbox or forwarding
  filter. Read-only, only mails from ricardo.ch and tutti.ch, password encrypted.
- eBay key entered by the administrator in the browser, checked with eBay before saving.
- Your own shops (Settings → Sources): add a shop by its search address; it's tested on
  the spot and searched with every search, where robots.txt allows and the shop
  publishes product data.
- robots.txt is now read like RFC 9309 (wildcards, longest match). The old parser
  ignored `*` rules.
- Fixed: gzip-compressed pages failed to load in link import and robots checks.
- Galaxus and Digitec through Galaxus' official MCP interface; their prices also
  serve as the new-price reference for used listings.
- Ricardo and tutti through their own saved-search e-mails: an IMAP inbox adapter,
  ready-made links on each search, status in Settings → Sources.
  Existing installs: `touch secrets/inbox_password` before `docker compose up`.
- Crash recovery: the worker notices when the server was offline, restarts
  interrupted search runs, catches up overdue searches, sends missed digests late
  and reports the outage to administrators (Telegram and Home).
- Backups: configurable interval, an overdue dump runs right after start, each dump
  is checked before it counts, and `status.json` records the result.
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
