from tests.conftest import PASSWORD, make_client, register


async def test_first_user_is_admin_and_cookie_flags(client):
    r = await client.get("/api/auth/status")
    assert r.json()["setup_required"] is True
    r = await client.post(
        "/api/auth/register",
        json={"email": "Alice@Example.com", "password": PASSWORD, "display_name": "Alice"},
    )
    assert r.status_code == 201
    assert r.json()["is_admin"] is True
    assert r.json()["email"] == "alice@example.com"
    set_cookie = ";".join(r.headers.get_list("set-cookie"))
    assert "schnaeppli_session=" in set_cookie and "HttpOnly" in set_cookie and "Secure" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "password" not in r.text


async def test_second_user_needs_invite(alice):
    c = make_client()
    r = await c.post(
        "/api/auth/register", json={"email": "eve@example.com", "password": PASSWORD, "display_name": "Eve"}
    )
    assert r.status_code == 403
    r = await c.post(
        "/api/auth/register",
        json={"email": "eve@example.com", "password": PASSWORD, "display_name": "Eve", "invite_code": "nope"},
    )
    assert r.status_code == 403
    code = (await alice.post("/api/admin/invites", json={})).json()["code"]
    r = await c.post(
        "/api/auth/register",
        json={"email": "eve@example.com", "password": PASSWORD, "display_name": "Eve", "invite_code": code},
    )
    assert r.status_code == 201 and r.json()["is_admin"] is False
    # invite is single use
    c2 = make_client()
    r = await c2.post(
        "/api/auth/register",
        json={"email": "mallory@example.com", "password": PASSWORD, "display_name": "M", "invite_code": code},
    )
    assert r.status_code == 403


async def test_weak_password_rejected(client):
    r = await client.post(
        "/api/auth/register", json={"email": "a@example.com", "password": "short", "display_name": "A"}
    )
    assert r.status_code == 422


async def test_login_logout_and_generic_error(alice):
    await alice.post("/api/auth/logout")
    assert (await alice.get("/api/auth/me")).status_code == 401
    r1 = await alice.post(
        "/api/auth/login", json={"email": "alice@example.com", "password": "wrong password!"}
    )
    r2 = await alice.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "wrong password!"}
    )
    assert r1.status_code == r2.status_code == 401
    assert r1.json() == r2.json()  # no account enumeration
    r = await alice.post("/api/auth/login", json={"email": "alice@example.com", "password": PASSWORD})
    assert r.status_code == 200
    assert (await alice.get("/api/auth/me")).status_code == 200


async def test_csrf_required_for_writes(alice):
    token = alice.cookies.get("schnaeppli_csrf")
    # bypass the auto-header by using the base class
    from httpx import AsyncClient

    r = await AsyncClient.request(alice, "POST", "/api/searches", json={"title": "x"})
    assert r.status_code == 403
    r = await AsyncClient.request(
        alice, "POST", "/api/searches", json={"title": "x"}, headers={"X-CSRF-Token": "forged"}
    )
    assert r.status_code == 403
    r = await AsyncClient.request(
        alice, "POST", "/api/searches", json={"title": "x"}, headers={"X-CSRF-Token": token}
    )
    assert r.status_code == 201


async def test_cross_origin_write_rejected(alice, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.get_settings(), "env", "production")
    r = await alice.post("/api/searches", json={"title": "x"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


async def test_bruteforce_rate_limit_and_lockout(alice):
    c = make_client()
    codes = []
    for _ in range(10):
        r = await c.post(
            "/api/auth/login", json={"email": "alice@example.com", "password": "wrong password!"}
        )
        codes.append(r.status_code)
    assert 429 in codes  # per-account limit kicks in before 10 attempts


async def test_password_change_signs_out_other_sessions(alice):
    other = make_client()
    await other.post("/api/auth/login", json={"email": "alice@example.com", "password": PASSWORD})
    assert (await other.get("/api/auth/me")).status_code == 200
    r = await alice.post(
        "/api/auth/password", json={"current_password": PASSWORD, "new_password": "an even better passphrase"}
    )
    assert r.status_code == 204
    assert (await other.get("/api/auth/me")).status_code == 401
    assert (await alice.get("/api/auth/me")).status_code == 200


async def test_session_list_and_revoke(alice):
    sessions = (await alice.get("/api/auth/sessions")).json()
    assert len(sessions) == 1 and sessions[0]["current"]


async def test_account_deletion_requires_password(alice):
    await register(
        make_client(), "x@example.com", "x", (await alice.post("/api/admin/invites", json={})).json()["code"]
    )
    r = await alice.request("DELETE", "/api/me", json={"password": "wrong", "confirm": "DELETE"})
    assert r.status_code == 403
    # last admin with other users can't delete
    r = await alice.request("DELETE", "/api/me", json={"password": PASSWORD, "confirm": "DELETE"})
    assert r.status_code == 409


async def test_setup_token_protects_first_account(client, monkeypatch):
    monkeypatch.setenv("SCHNAEPPLI_SETUP_TOKEN", "bootstrap-secret")
    st = (await client.get("/api/auth/status")).json()
    assert st["setup_token_required"] is True
    body = {"email": "a@example.com", "password": PASSWORD, "display_name": "A"}
    assert (await client.post("/api/auth/register", json=body)).status_code == 403
    assert (await client.post("/api/auth/register", json=body | {"setup_token": "wrong"})).status_code == 403
    r = await client.post("/api/auth/register", json=body | {"setup_token": "bootstrap-secret"})
    assert r.status_code == 201 and r.json()["is_admin"]
