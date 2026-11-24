# Installation

Schnäppli runs as a Docker Compose stack: `web`, `api`, `worker`, `db` (PostgreSQL 16),
`redis`, a one-shot `migrate`, and a `backup` service.

## Requirements

- Docker Engine with Compose v2, about 1.5 GB of disk for images, 1 GB RAM is plenty.
- A reverse proxy with TLS on your private network (Caddy, Traefik, nginx), or a
  VPN such as WireGuard/Tailscale/OpenVPN. HTTPS is needed for secure cookies and
  for installing the PWA on iOS.
- An API key for at least one AI provider (Anthropic, OpenAI or Google Gemini).
- Optional: a Telegram bot, an eBay developer application.

## 1. Get the code and configure

```bash
git clone https://github.com/<you>/schnaeppli.git
cd schnaeppli
cp .env.example .env
```

Edit `.env`:

- `POSTGRES_PASSWORD`: a long random string (`openssl rand -hex 24`).
- `SCHNAEPPLI_PUBLIC_URL`: the HTTPS URL you'll open Schnäppli at.
- `SCHNAEPPLI_SETUP_TOKEN`: a random string (`openssl rand -hex 16`). The first account
  (the administrator) can only be created with it.
- `SCHNAEPPLI_ALLOWED_NETWORKS`: your LAN and VPN ranges, e.g. `192.168.0.0/24,10.10.0.0/24`.
- `SCHNAEPPLI_PROXY_NETWORK`: the Docker network your reverse proxy is on (or leave the
  default and use `SCHNAEPPLI_BIND` to publish on a private address).

## 2. Create the secrets

Secrets are mounted as files and never appear in environment variables.

```bash
mkdir -p secrets && chmod 700 secrets
echo "k1:$(openssl rand -base64 32)" > secrets/encryption_keys   # encrypts users' API keys
touch secrets/telegram_bot_token secrets/ebay_client_id secrets/ebay_client_secret secrets/claude_code_bridge_secret secrets/inbox_password
chmod 644 secrets/*   # readable inside the containers; the folder itself stays private
```

**Back up `secrets/encryption_keys` separately from database backups.** Without it,
stored API keys can't be decrypted (users would have to enter them again).

## 3. Start

```bash
docker compose up -d --build
docker compose ps        # all services should become healthy
```

Point your reverse proxy at the `web` container, port 8080. Example for Caddy on the
same Docker network:

```
schnaeppli.example.internal {
    tls internal
    reverse_proxy schnaeppli-web-1:8080
}
```

## 4. First sign-in

Open the URL, enter your name, e-mail, a password and the setup token. This account
is the administrator. Then:

1. **Settings → AI**: add your API key and press *Test*.
2. **Settings → General**: set your postal code (used locally for pickup distances).
3. **Settings → Notifications**: connect Telegram (after the admin configured a bot).
4. **New search**: describe what you want.

Invite others under **Settings → Admin → Invites**.

## Updating

```bash
git pull
docker compose up -d --build   # migrations run automatically before the API starts
```

## Backups and restore

The `backup` service writes a compressed `pg_dump` every day at `BACKUP_HOUR` into
`BACKUP_DIR` and keeps `BACKUP_KEEP_DAYS` days.

Restore into a fresh stack:

```bash
docker compose up -d db
gunzip -c backups/schnaeppli-YYYYMMDD-HHMM.sql.gz | docker compose exec -T db psql -U schnaeppli -d schnaeppli
docker compose up -d
```

Test a restore now and then (into a scratch database: `createdb -U schnaeppli restore_test`,
load the dump there, check the tables, `dropdb`).

## Development

```bash
# backend
cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
SCHNAEPPLI_ENV=development SCHNAEPPLI_REDIS_URL= SCHNAEPPLI_DATABASE_URL=sqlite+aiosqlite:///dev.db \
  .venv/bin/python -m scripts.seed_demo          # optional demo data (refuses in production)
SCHNAEPPLI_ENV=development SCHNAEPPLI_REDIS_URL= SCHNAEPPLI_DATABASE_URL=sqlite+aiosqlite:///dev.db \
  .venv/bin/uvicorn app.main:app --reload

# frontend
cd frontend && npm install && npm run dev        # proxies /api to 127.0.0.1:8000
```
