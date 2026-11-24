"""Authorization: users can never see or change each other's data."""

from sqlalchemy import select

from app.core.db import sessionmaker
from app.models import Listing, SearchMatch, User
from tests.conftest import add_key


async def _alice_data(alice):
    s = (await alice.post("/api/searches", json={"title": "Camera", "max_budget": 300})).json()
    w = (await alice.post("/api/wishlist", json={"title": "Sony a6400"})).json()
    k = await add_key(alice)
    t = (await alice.post("/api/chat/threads")).json()
    p = (await alice.post("/api/budget/items", json={"title": "Lens", "amount": 150})).json()
    async with sessionmaker()() as db:
        user = await db.scalar(select(User).where(User.email == "alice@example.com"))
        listing = Listing(
            source="ebay", external_id="1", url="https://example.com/1", title="Sony a6400", content_hash="x"
        )
        db.add(listing)
        await db.flush()
        m = SearchMatch(user_id=user.id, search_id=__import__("uuid").UUID(s["id"]), listing_id=listing.id)
        db.add(m)
        await db.commit()
        mid = str(m.id)
    return s, w, k, t, p, mid


async def test_bob_cannot_access_alice(alice, bob):
    s, w, k, t, p, mid = await _alice_data(alice)
    for method, url, body in [
        ("GET", f"/api/searches/{s['id']}", None),
        ("PATCH", f"/api/searches/{s['id']}", {"title": "pwned"}),
        ("DELETE", f"/api/searches/{s['id']}", None),
        ("GET", f"/api/searches/{s['id']}/matches", None),
        ("POST", f"/api/searches/{s['id']}/duplicate", None),
        ("PATCH", f"/api/wishlist/{w['id']}", {"title": "pwned"}),
        ("DELETE", f"/api/wishlist/{w['id']}", None),
        ("PATCH", f"/api/ai/credentials/{k['id']}", {"label": "pwned"}),
        ("POST", f"/api/ai/credentials/{k['id']}/test", None),
        ("DELETE", f"/api/ai/credentials/{k['id']}", None),
        ("GET", f"/api/chat/threads/{t['id']}", None),
        ("PATCH", f"/api/budget/items/{p['id']}", {"amount": 1}),
        ("GET", f"/api/deals/{mid}", None),
        ("PATCH", f"/api/deals/{mid}", {"status": "rejected"}),
    ]:
        r = await bob.request(method, url, json=body)
        assert r.status_code == 404, (method, url, r.status_code)

    assert (await bob.get("/api/searches")).json() == []
    assert (await bob.get("/api/wishlist")).json() == []
    assert (await bob.get("/api/deals")).json() == []
    assert (await bob.get("/api/ai/credentials")).json()["own"] == []
    # Alice's things are untouched
    assert (await alice.get(f"/api/searches/{s['id']}")).json()["title"] == "Camera"


async def test_non_admin_cannot_use_admin_endpoints(alice, bob):
    for method, url in [
        ("GET", "/api/admin/users"),
        ("POST", "/api/admin/invites"),
        ("GET", "/api/admin/audit"),
    ]:
        r = await bob.request(method, url, json={})
        assert r.status_code == 403
    r = await bob.post(
        "/api/ai/credentials?shared=true",
        json={"provider": "anthropic", "label": "x", "api_key": "sk-ant-xxxxxxxxxxxx"},
    )
    assert r.status_code == 403


async def test_chat_focus_cannot_reference_other_users_listing(alice, bob, fake_ai):
    *_, mid = await _alice_data(alice)
    await add_key(bob)
    t = (await bob.post("/api/chat/threads")).json()
    r = await bob.post(f"/api/chat/threads/{t['id']}/messages", json={"text": "compare", "focus": [mid]})
    assert r.status_code == 404
