async def test_ui_prefs_defaults_and_update(alice):
    me = (await alice.get("/api/auth/me")).json()
    assert me["ui_prefs"]["theme"] == "system"
    assert me["ui_prefs"]["phone_tabs"] == ["home", "deals", "searches", "assistant"]

    prefs = {**me["ui_prefs"], "theme": "dark", "accent": "forest", "density": "compact",
             "phone_tabs": ["deals", "searches", "wishlist", "budget"], "start_page": "deals"}
    r = await alice.patch("/api/me", json={"ui_prefs": prefs})
    assert r.status_code == 200, r.text
    got = r.json()["ui_prefs"]
    assert got["theme"] == "dark" and got["accent"] == "forest" and got["start_page"] == "deals"
    assert (await alice.get("/api/auth/me")).json()["ui_prefs"]["phone_tabs"][0] == "deals"


async def test_ui_prefs_validation(alice):
    base = (await alice.get("/api/auth/me")).json()["ui_prefs"]
    for bad in ({"theme": "neon"}, {"phone_tabs": ["home", "deals"]}, {"accent": "#ff0000"},
                {"start_page": "admin"}):
        r = await alice.patch("/api/me", json={"ui_prefs": {**base, **bad}})
        assert r.status_code == 422, bad
