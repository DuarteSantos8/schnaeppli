from __future__ import annotations

import base64
import os
import tempfile

os.environ["SCHNAEPPLI_ENV"] = "test"
_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["SCHNAEPPLI_DATABASE_URL"] = f"sqlite+aiosqlite:///{_db.name}"
os.environ["SCHNAEPPLI_ENCRYPTION_KEYS"] = "t1:" + base64.b64encode(os.urandom(32)).decode()
os.environ["SCHNAEPPLI_PUBLIC_URL"] = "https://schnaeppli.test"
os.environ["SCHNAEPPLI_REGISTRATION_MODE"] = "invite"

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.ai import gateway  # noqa: E402
from app.ai.providers import Completion, Provider, Usage  # noqa: E402
from app.core.db import Base, set_engine  # noqa: E402
from app.core.ratelimit import reset_limiter_for_tests  # noqa: E402
from app.main import app  # noqa: E402

PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
async def fresh_db():
    engine = create_async_engine(os.environ["SCHNAEPPLI_DATABASE_URL"])
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    set_engine(engine)
    reset_limiter_for_tests()
    yield
    await engine.dispose()


class Client(AsyncClient):
    """Test client that echoes the CSRF cookie like the SPA does."""

    async def request(self, method, url, **kw):
        if method.upper() not in ("GET", "HEAD", "OPTIONS"):
            csrf = self.cookies.get("schnaeppli_csrf")
            if csrf:
                kw["headers"] = {**(kw.get("headers") or {}), "X-CSRF-Token": csrf}
        return await super().request(method, url, **kw)


def make_client() -> Client:
    return Client(
        transport=ASGITransport(app=app, client=("10.20.30.5", 1234)), base_url="https://schnaeppli.test"
    )


@pytest.fixture
async def client():
    async with make_client() as c:
        yield c


async def register(c: Client, email="alice@example.com", name="Alice", invite=None):
    r = await c.post(
        "/api/auth/register",
        json={"email": email, "password": PASSWORD, "display_name": name, "invite_code": invite},
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
async def alice(client):
    await register(client)
    return client


@pytest.fixture
async def bob(alice):
    r = await alice.post("/api/admin/invites", json={"note": "bob"})
    code = r.json()["code"]
    c = make_client()
    await register(c, "bob@example.com", "Bob", code)
    yield c
    await c.aclose()


# ------------------------------------------------------------------ fake AI
class FakeProvider(Provider):
    name = "anthropic"
    calls: list = []
    responses: dict = {}

    async def complete(self, model, prompt, schema=None):
        FakeProvider.calls.append({"model": model, "prompt": prompt, "schema": schema})
        key = schema.__name__ if schema else "text"
        data = FakeProvider.responses.get(key)
        if callable(data):
            data = data(prompt)
        parsed = schema.model_validate(data) if schema else None
        return Completion(
            text="" if schema else (data or "Hello from the fake model."),
            parsed=parsed,
            usage=Usage(input_tokens=1000, output_tokens=200),
            model=model,
        )

    async def list_models(self):
        return ["claude-opus-5-5"]


@pytest.fixture
def fake_ai(monkeypatch):
    FakeProvider.calls = []
    FakeProvider.responses = {}
    monkeypatch.setattr(
        gateway, "make_provider", lambda name, key, base_url=None: FakeProvider(key, base_url)
    )
    return FakeProvider


async def add_key(c: Client, provider="anthropic"):
    r = await c.post(
        "/api/ai/credentials",
        json={"provider": provider, "label": "mine", "api_key": "sk-ant-test-1234567890abcd"},
    )
    assert r.status_code == 201, r.text
    return r.json()
