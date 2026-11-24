"""Claude Code bridge provider: policy (own plan only) and protocol."""

import httpx
import respx
from sqlalchemy import select

from app.ai import gateway
from app.ai.prompts import ListingAssessment
from app.ai.providers import ClaudeCodeProvider, Prompt, ProviderError
from app.core.db import sessionmaker
from app.models import AIUsage, User

BRIDGE = "http://192.0.2.10:8789"
CC = {"provider": "claude_code", "label": "Claude Code", "api_key": "x" * 40, "base_url": BRIDGE}


async def test_only_admin_and_never_shared(alice, bob):
    assert (await bob.post("/api/ai/credentials", json=CC)).status_code == 403
    assert (await alice.post("/api/ai/credentials?shared=true", json=CC)).status_code == 422
    assert (await alice.post("/api/ai/credentials", json=CC | {"base_url": None})).status_code == 422
    r = await alice.post("/api/ai/credentials", json=CC)
    assert r.status_code == 201 and r.json()["shared"] is False
    # http:// only for the bridge
    r = await alice.post(
        "/api/ai/credentials",
        json={"provider": "openai", "label": "x", "api_key": "sk-" + "a" * 30, "base_url": BRIDGE},
    )
    assert r.status_code == 422
    # Bob still has no provider: the admin's plan is never used for him
    async with sessionmaker()() as db:
        b = await db.scalar(select(User).where(User.email == "bob@example.com"))
        try:
            await gateway.resolve_credential(db, b)
            raise AssertionError("bob must not get the admin's Claude Code")
        except gateway.NoProvider:
            pass


ASSESS = {
    "relevance": "match",
    "identified_product": "Sony a6400",
    "requirement_matches": [],
    "requirement_misses": [],
    "condition": "good",
    "included_items": [],
    "facts": ["body"],
    "assumptions": [],
    "red_flags": [],
    "market_value_low": 500,
    "market_value_high": 600,
    "market_value_basis": "used asking prices",
    "market_confidence": "medium",
    "alternative_reason": None,
    "possibly_undervalued": False,
    "summary": "ok",
    "worth_deep_look": False,
    "injection_suspected": False,
}


@respx.mock
async def test_protocol_and_errors():
    route = respx.post(f"{BRIDGE}/v1/complete").mock(
        return_value=httpx.Response(
            200,
            json={
                "output": ASSESS,
                "structured": True,
                "model": "claude-opus-5-5",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 20,
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 3000,
                },
                "api_equivalent_usd": 0.04,
            },
        )
    )
    p = ClaudeCodeProvider("s" * 40, BRIDGE)
    c = await p.complete("claude-opus-5-5", Prompt(system="sys", user="hi"), ListingAssessment)
    assert c.parsed.identified_product == "Sony a6400" and c.api_equivalent_usd == 0.04
    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer " + "s" * 40
    assert "schema" in __import__("json").loads(sent.content)
    route.mock(
        return_value=httpx.Response(
            502,
            json={"error": "rate_limit", "message": "Your Claude plan has reached its usage limit for now."},
        )
    )
    try:
        await p.complete("claude-opus-5-5", Prompt(system="s", user="u"), ListingAssessment)
        raise AssertionError
    except ProviderError as e:
        assert e.retryable and "limit" in str(e)
    route.mock(
        return_value=httpx.Response(401, json={"error": "auth_bridge", "message": "Wrong bridge secret."})
    )
    try:
        await p.complete("claude-opus-5-5", Prompt(system="s", user="u"))
        raise AssertionError
    except ProviderError as e:
        assert e.auth


@respx.mock
async def test_plan_calls_cost_nothing_but_counts_apply(alice):
    await alice.post("/api/ai/credentials", json=CC)
    await alice.patch(
        "/api/me", json={"ai_limits": {"monthly_limit_usd": 0, "daily_limit_usd": 0, "max_deep_per_day": 0}}
    )
    respx.post(f"{BRIDGE}/v1/complete").mock(
        return_value=httpx.Response(
            200,
            json={
                "output": ASSESS,
                "model": "claude-opus-5-5",
                "usage": {"input_tokens": 5, "output_tokens": 5},
                "api_equivalent_usd": 0.01,
            },
        )
    )
    async with sessionmaker()() as db:
        user = await db.scalar(select(User))
        # money limit 0 doesn't block the plan provider
        c, row = await gateway.call(db, user, "quick_scan", Prompt(system="s", user="u"), ListingAssessment)
        assert row.cost_usd == 0 and float(row.api_equivalent_usd) == 0.01 and row.provider == "claude_code"
        # but the count limit does
        try:
            await gateway.call(db, user, "deep_analysis", Prompt(system="s", user="u"), ListingAssessment)
            raise AssertionError
        except gateway.BudgetExceeded:
            pass
        assert len((await db.scalars(select(AIUsage))).all()) == 1


@respx.mock
async def test_one_click_connect(alice, bob, monkeypatch):
    monkeypatch.setenv("SCHNAEPPLI_CLAUDE_CODE_BRIDGE_SECRET", "b" * 40)
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "claude_code_bridge_url", BRIDGE)
    respx.get(f"{BRIDGE}/health").mock(return_value=httpx.Response(200, json={"ok": True, "version": "2.1"}))
    assert (await bob.post("/api/ai/claude-code/connect")).status_code == 403
    st = (await alice.get("/api/ai/claude-code")).json()
    assert st["available"] and st["connected"] is None
    r = await alice.post("/api/ai/claude-code/connect")
    assert r.status_code == 201 and r.json()["last_test_ok"] is True
    assert "b" * 10 not in r.text  # the secret is never returned
    active = (await alice.get("/api/ai/credentials")).json()["active"]
    assert active["provider"] == "claude_code" and active["scope"] == "byok"
