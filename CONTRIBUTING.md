# Contributing to Schnäppli

Thanks for helping. Schnäppli is a small project; good issues and focused pull requests
are the most useful contributions.

## Before you start

- For anything bigger than a bug fix, open an issue first so we can agree on the approach.
- Marketplace adapters must use permitted access only (official APIs, robots.txt-respecting
  single page reads, or user-forwarded data). See [docs/marketplaces.md](docs/marketplaces.md).
- Never commit secrets, real user data, private hostnames or IP addresses.

## Development setup

See [docs/installation.md → Development](docs/installation.md#development).

## Checks

```bash
cd backend && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/pytest -q
cd frontend && npx tsc -p tsconfig.json --noEmit && npx vite build
```

New behaviour needs tests. Anything touching auth, authorization, secrets or AI input
handling needs a test in `backend/tests/test_security.py` or `test_isolation.py`.

## Style

- Python: ruff (lint + format), type hints, small functions.
- Frontend: TypeScript strict, Tailwind tokens from `src/index.css`. The UI keeps colour
  off the chrome: cobalt is reserved for the Deal Score, status colours only where
  something changed. No gradients, glows or icon-in-a-circle cards.
- Copy: plain, short, honest. Say "estimated" when something is.

## Pull requests

Keep them focused, describe what and why, include screenshots for UI changes (phone
and desktop), and fill in the template. By contributing you agree your contribution is
licensed under AGPL-3.0-or-later.
