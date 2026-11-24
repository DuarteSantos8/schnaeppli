# Configuration reference

All settings are environment variables with the `SCHNAEPPLI_` prefix (set in `.env`).
Secrets can also be given as `SCHNAEPPLI_<NAME>_FILE=/path/to/file`, which is how the
Compose file passes them.

## General

| Variable | Default | Description |
| --- | --- | --- |
| `SCHNAEPPLI_ENV` | `production` | `production`, `development` or `test`. API docs (`/api/docs`) only outside production. |
| `SCHNAEPPLI_PUBLIC_URL` | `http://localhost:8080` | Public base URL. `https://` turns on `Secure` cookies. Used for links in Telegram messages and the cross-origin check. |
| `SCHNAEPPLI_DATABASE_URL` | Compose sets it | SQLAlchemy async URL (`postgresql+asyncpg://…`). |
| `SCHNAEPPLI_REDIS_URL` | Compose sets it | Redis for jobs and rate limits. |
| `SCHNAEPPLI_REGISTRATION_MODE` | `invite` | Who can sign up after the admin: `invite`, `open`, `closed`. |
| `SCHNAEPPLI_SETUP_TOKEN` | empty | If set, required to create the first (admin) account. Recommended. |
| `SCHNAEPPLI_ALLOWED_NETWORKS` | empty | Comma-separated CIDRs allowed to use the app (checked in the app, in addition to your proxy/VPN). Empty disables the check. |
| `SCHNAEPPLI_TRUSTED_PROXIES` | `127.0.0.1/32` | Proxies whose `X-Forwarded-For` is trusted when determining the client IP. Include your Docker networks (`172.16.0.0/12`). |
| `SCHNAEPPLI_SESSION_DAYS` | `30` | Session lifetime. |
| `SCHNAEPPLI_SESSION_IDLE_DAYS` | `14` | Sessions unused this long expire. |
| `SCHNAEPPLI_DEFAULT_TIMEZONE` | `Europe/Zurich` | For new users. |
| `SCHNAEPPLI_DEFAULT_CURRENCY` | `CHF` | For new users. |
| `SCHNAEPPLI_LOG_LEVEL` | `INFO` | Logs are JSON; secrets are redacted. |
| `SCHNAEPPLI_BOT_CONTACT_URL` | empty | Added to the User-Agent of outbound page and image fetches; some sites require a contact URL from automated clients. |

## Secrets (files in `./secrets/`)

| File / variable | Description |
| --- | --- |
| `encryption_keys` / `SCHNAEPPLI_ENCRYPTION_KEYS` | **Required.** `id:base64key[,id2:base64key2]`, 32-byte keys. The first key encrypts; older keys still decrypt (rotation: put a new key first). |
| `telegram_bot_token` / `SCHNAEPPLI_TELEGRAM_BOT_TOKEN` | Bot token from @BotFather. Empty disables Telegram. |
| `ebay_client_id`, `ebay_client_secret` | eBay application keys (Production keyset). Empty disables eBay. |
| `SCHNAEPPLI_SHARED_AI_API_KEY` | Optional shared AI key from the environment (alternative to adding one in the app). |

## Integrations

| Variable | Default | Description |
| --- | --- | --- |
| `SCHNAEPPLI_TELEGRAM_BOT_USERNAME` | empty | Bot username without `@`, for the "Open in Telegram" link. |
| `SCHNAEPPLI_EBAY_MARKETPLACE` | `EBAY_CH` | eBay marketplace id (`EBAY_DE`, `EBAY_AT`, `EBAY_GB`, …). |
| `SCHNAEPPLI_EBAY_ENVIRONMENT` | `production` | `production` or `sandbox`. |
| `SCHNAEPPLI_SHARED_AI_PROVIDER` | empty | `anthropic`, `openai` or `gemini`, used with `SCHNAEPPLI_SHARED_AI_API_KEY`. |
| `SCHNAEPPLI_SHARED_AI_MODEL` | provider default | Model for the shared env key. |

## Compose-only

| Variable | Default | Description |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | — | Required. |
| `SCHNAEPPLI_BIND` | `127.0.0.1:8080` | Where the web container is published. Keep it on a private address. |
| `SCHNAEPPLI_PROXY_NETWORK` | `schnaeppli-proxy` | Docker network shared with your reverse proxy. |
| `BACKUP_DIR` | `./backups` | Database dumps. |
| `BACKUP_KEEP_DAYS` | `14` | Retention. |
| `BACKUP_HOUR` | `3` | Hour the dumps are aligned to (container time, UTC). |
| `BACKUP_INTERVAL_HOURS` | `24` | Hours between dumps. An overdue dump (server was off) runs right after start. Each dump is checked before it counts; `status.json` holds the last result. |

## Per-user settings (in the app)

Location and radius, delivery preference, timezone, currency, daily search times,
digest times/days/threshold, instant alert types, AI keys and models per task, AI
spending limits, whether listing towns may be shared with the AI, monthly shopping
budget.
