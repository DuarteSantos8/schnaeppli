# Claude Code as Schnäppli's AI (your own Claude plan)

If you're signed in to Claude Code on the machine you run Schnäppli on (or another
machine on your network), Schnäppli can use that installation as its AI instead of an
API key. Requests run through the **unmodified `claude` CLI on your machine** with
your own login, so analyses are covered by your Claude plan instead of API billing.

## Rules

Anthropic allows you to use Claude Code with your own plan; it does **not** allow
apps to collect Claude.ai credentials or to route *other people's* requests through
your plan. So:

- Schnäppli never sees or stores your Claude credentials. It only talks to a small bridge
  that starts `claude -p` on your machine.
- The provider is available only to the administrator who connects it, for their own
  account. It can't be shared with other users of your instance; they need their own
  API key.
- Your plan's usage limits apply. Schnäppli analyses listings in the background, so keep
  "Analyses per search run" moderate.

## Setup

1. On the machine with Claude Code, sign in once: run `claude` and use `/login`.
2. Create a secret: `openssl rand -base64 36 | tr -d '/+='`.
3. Run the bridge (Python 3, no dependencies), e.g. as a systemd service:

   ```ini
   # /etc/systemd/system/schnaeppli-claude-code-bridge.service
   [Service]
   Environment=SCHNAEPPLI_BRIDGE_SECRET=<secret>
   Environment=SCHNAEPPLI_BRIDGE_HOST=<this machine's LAN address>
   Environment=SCHNAEPPLI_BRIDGE_PORT=8789
   Environment=SCHNAEPPLI_BRIDGE_ALLOW=<address Schnäppli's containers connect from>/32
   Environment=HOME=/home/<you>
   ExecStart=/usr/bin/python3 /path/to/schnaeppli/bridge/claude_code_bridge.py
   User=<the user that is signed in to claude>
   Restart=on-failure
   NoNewPrivileges=true
   PrivateTmp=true
   ```

   Better: put the variables in an `EnvironmentFile` with mode 0600.
4. In Schnäppli's `.env`: `SCHNAEPPLI_CLAUDE_CODE_BRIDGE_URL=http://<bridge address>:8789`, and
   put the same secret into `secrets/claude_code_bridge_secret`. `docker compose up -d`.
5. In Schnäppli: **Settings → AI → Claude Code on this server → Connect**.

## What the bridge does

- Accepts requests only from the allowed addresses and with the secret.
- Runs `claude -p` in an empty temporary folder with **no tools** (only `Read`, limited
  to that folder, when photos are attached), `--restricted`, without your MCP servers,
  and without saving sessions. The folder is deleted afterwards.
- Uses `--system-prompt` and `--json-schema` for Schnäppli's structured answers.
- At most `SCHNAEPPLI_BRIDGE_PARALLEL` (default 2) `claude` processes at once.
- Returns the token counts Claude Code reports. Schnäppli shows them in AI usage, with the
  API-equivalent value for comparison; no money is counted against your USD limits,
  but the per-day limits for deep analyses and photo checks still apply.
