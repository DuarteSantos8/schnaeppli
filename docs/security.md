# Security & privacy

Schnäppli holds accounts, AI API keys, a Telegram link and your shopping intentions.
It is designed to run on a private network or behind a VPN, never on the open
internet.

## Deployment model

- **Keep it private.** Put it behind a VPN or on your LAN, with a reverse proxy that
  terminates TLS. Don't forward a public port to it. A secret URL is not access
  control.
- **Three layers** in the reference deployment: no public port; an IP allowlist at
  the reverse proxy; and the app's own `SCHNAEPPLI_ALLOWED_NETWORKS` check (computed from
  the peer address and only trusted proxies' `X-Forwarded-For`).
- **Bootstrap**: set `SCHNAEPPLI_SETUP_TOKEN` so nobody else can create the admin account
  on a fresh instance. Registration after that is invite-only by default.
- PostgreSQL and Redis are on an internal Docker network without published ports.
- Containers run as non-root with read-only filesystems, `no-new-privileges` and
  dropped capabilities (backend).

## Authentication & sessions

- Passwords hashed with **Argon2id** (64 MiB, t=3, p=2), rehashed when parameters change.
  Minimum 10 characters; trivially repetitive passwords and the e-mail name are rejected.
- Server-side sessions; the cookie holds a random token, the database only its SHA-256.
  Cookies are `HttpOnly`, `Secure` (on HTTPS) and `SameSite=Lax`.
- **CSRF**: every state-changing request needs an `X-CSRF-Token` header that matches a
  per-session token (double-submit, bound to the session), plus an Origin check.
- **Brute force**: per-IP and per-account login rate limits (Redis), account lockout
  after repeated failures, identical errors for unknown e-mail and wrong password,
  constant-time password checks.
- Changing the password signs out all other devices; sessions can be revoked
  individually.

## Authorization

Every query is scoped to the signed-in user. Requests for another user's object
return 404, not 403, so existence isn't revealed. Admin endpoints check the role.
Tests cover cross-user access for every resource type (`backend/tests/test_isolation.py`).

## Secrets

- Users' AI keys are encrypted with **AES-256-GCM**. The ciphertext is bound to its
  database row (associated data), keys have ids for rotation, and the encryption key
  is a file mounted as a Docker secret, separate from the database and its backups.
- Keys are never returned to the browser (only the last four characters), never logged,
  and API errors are rewritten so they can't contain them.
- Logs pass through a redaction filter (Telegram bot tokens in URLs, `sk-…` keys,
  `password=`/`token=` pairs). The HTTP client's URL logging is disabled because
  Telegram URLs contain the bot token.
- No secret is ever placed in the frontend bundle or in environment variables seen
  by the browser.

## AI and untrusted content

Listing titles, descriptions, seller text and photos are **untrusted input**.

- They are placed after the instructions inside `<untrusted_listing>` blocks;
  look-alike tags are neutralised and text is length-limited.
- The model has **no tools**. It can only return JSON matching a fixed schema. It
  can't change settings, read other users' data, reach the network or touch secrets.
- The Deal Score is computed in code from the model's structured answer
  ([ADR 0003](adr/0003-deterministic-score.md)). Listings that try to manipulate the
  assessment are flagged and labelled *risky*.
- The assistant chat sees only the current user's data, given to it as read-only
  context; it can suggest actions but never perform them.

## Outbound requests

- Pages fetched for "add by link" and listing photos go through a guarded client:
  https only, standard port, no credentials in URLs, every redirect hop must resolve
  to a **public** address (blocks localhost, private ranges, cloud metadata), size and
  time limits, robots.txt respected for pages.
- Listing photos are served to the browser through an **authenticated, HMAC-signed
  proxy** that downscales them and strips metadata. Only URLs the server itself
  emitted can be fetched, so it isn't an open proxy, and the browser contacts no
  third parties (CSP `img-src 'self'`).
- Known limitation: the public-address check happens before the connection, so a
  DNS answer that changes between check and connect (DNS rebinding) is theoretically
  possible. Exposure is limited because only signed or user-pasted URLs are fetched.

## Privacy

- Location is a postal code or town; a street address is never requested. Distances
  are computed on your server from an offline postal code table.
- What goes to your AI provider: your search descriptions, public listing text and
  photos, and, for the assistant, your searches, budget and found listings. Never your
  e-mail, password, postal code or address. Listing towns are shared only if you turn
  that on.
- No analytics, telemetry or third-party requests from the browser.
- Users can export all their data as JSON and delete their account (everything is
  removed, including keys, chats and usage history).
- Learned preferences are visible and resettable, and never leave the instance.

## Web hardening

Strict Content Security Policy without third-party origins, HSTS, `X-Frame-Options:
DENY`, `nosniff`, `Referrer-Policy: no-referrer`, a restrictive Permissions-Policy,
request size limits, safe error messages (no stack traces), and security events in an
audit log visible to admins.

## Dependencies

Run `pip-audit` and `npm audit` regularly. At the time of writing, `npm audit` reports
moderate advisories only in build-time tooling (`workbox-build` → `glob`/`minimatch`),
which is not shipped to the browser.

## Reporting a vulnerability

Please don't open a public issue. Contact the maintainer privately (see the
repository's security policy) with steps to reproduce.
