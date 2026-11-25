"""Setup in the browser: own mailbox (read-only, only alert mails), eBay key, the step list."""

import httpx
import pytest
import respx
from sqlalchemy import select

from app.core.db import sessionmaker
from app.models import MailConnection, SearchMatch
from app.services import inbox_import
from app.sources import mailbox
from tests.test_inbox import RICARDO_HTML, _mail

PASSWORD = "abcd efgh ijkl mnop"  # how Google shows an app password  # noqa: S105


class FakeIMAP:
    """Enough of imaplib.IMAP4_SSL; records every command so we can prove nothing is changed."""

    mails: dict[int, bytes] = {}
    password = PASSWORD.replace(" ", "")
    uidvalidity = 7
    log: list[tuple] = []

    def __init__(self, host, port, timeout=None):
        FakeIMAP.log.append(("connect", host, port))

    def login(self, user, password):
        FakeIMAP.log.append(("login", user))
        if password != FakeIMAP.password:
            raise mailbox.imaplib.IMAP4.error("AUTHENTICATIONFAILED")
        return "OK", [b""]

    def select(self, folder, readonly=False):
        FakeIMAP.log.append(("select", folder, readonly))
        return "OK", [str(len(self.mails)).encode()]

    def response(self, code):
        return code, [str(FakeIMAP.uidvalidity).encode()]

    def uid(self, command, *args):
        FakeIMAP.log.append(("uid", command, *args))
        if command == "SEARCH":
            low = 1
            if "UID" in args:
                low = int(args[args.index("UID") + 1].split(":")[0])
            hits = [u for u in sorted(self.mails) if u >= low] or ([max(self.mails)] if self.mails else [])
            return "OK", [" ".join(map(str, hits)).encode()]
        if command == "FETCH":
            assert args[1] == "(BODY.PEEK[])"
            return "OK", [(b"1 (BODY[] {1}", self.mails[int(args[0])]), b")"]
        raise AssertionError(f"unexpected command {command}")

    def store(self, *a):
        raise AssertionError("must never change the mailbox")

    def logout(self):
        return "BYE", []


@pytest.fixture(autouse=True)
def _fake_imap(monkeypatch):
    async def public(host):
        return None

    monkeypatch.setattr(mailbox, "_assert_public", public)
    monkeypatch.setattr(mailbox.imaplib, "IMAP4_SSL", FakeIMAP)
    FakeIMAP.mails = {}
    FakeIMAP.log = []
    FakeIMAP.uidvalidity = 7
    from app.api import setup

    setup._attempts.clear()


async def test_connect_gmail_reads_only_and_stores_the_password_encrypted(alice):
    FakeIMAP.mails = {41: _mail("Neue Angebote für «Sony RX100»", html=RICARDO_HTML)}
    r = await alice.post("/api/setup/mail", json={"address": "duo@gmail.com", "password": PASSWORD})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["found"] == 1 and body["connection"]["provider"] == "gmail"
    assert ("connect", "imap.gmail.com", 993) in FakeIMAP.log
    assert all(e[2] is True for e in FakeIMAP.log if e[0] == "select")  # EXAMINE, never SELECT
    async with sessionmaker()() as db:
        conn = (await db.scalars(select(MailConnection))).one()
        assert FakeIMAP.password not in conn.encrypted_password
    export = (await alice.get("/api/me/export")).text
    assert FakeIMAP.password not in export and "imap.gmail.com" in export


async def test_wrong_password_explains_app_passwords_and_saves_nothing(alice):
    r = await alice.post("/api/setup/mail", json={"address": "duo@gmail.com", "password": "my-normal-pw"})
    assert r.status_code == 422 and "app password" in r.json()["detail"]
    assert (await alice.get("/api/setup/mail")).json()["connection"] is None


async def test_outlook_is_explained_not_attempted(alice):
    r = await alice.post("/api/setup/mail", json={"address": "duo@hotmail.com", "password": "x"})
    assert r.status_code == 422 and "Microsoft" in r.json()["detail"]
    assert FakeIMAP.log == []


async def test_alert_mails_reach_the_search_once_and_only_from_ricardo_or_tutti(alice):
    s = (
        await alice.post("/api/searches", json={"title": "Sony RX100 compact camera", "max_budget": 300})
    ).json()
    FakeIMAP.mails = {
        5: _mail("Neue Angebote für «Sony RX100»", html=RICARDO_HTML),
        6: _mail("Sony RX100 günstig!", html=RICARDO_HTML, sender="phish@example.com"),
    }
    await alice.post("/api/setup/mail", json={"address": "duo@gmail.com", "password": PASSWORD})
    r = (await alice.post("/api/setup/mail/check")).json()
    assert r["imported"] == 2 and r["connection"]["totals"] == {"ricardo": 2}
    assert r["connection"]["search_names"] == ["Sony RX100"]
    async with sessionmaker()() as db:
        matches = (await db.scalars(select(SearchMatch))).all()
        assert {str(m.search_id) for m in matches} == {s["id"]}  # the fake sender's mail added nothing more
        conn = (await db.scalars(select(MailConnection))).one()
        assert conn.last_uid == 6 and conn.uidvalidity == 7
        FakeIMAP.log = []
        await inbox_import.import_user_mail(db, conn)  # nothing new: no mail is fetched again
        assert not [e for e in FakeIMAP.log if e[:2] == ("uid", "FETCH")]
    overview = (await alice.get("/api/setup")).json()
    assert overview["mail"]["state"] == "ok" and overview["alerts_arrived"] and overview["search"]


async def test_changed_password_shows_up_as_login_problem(alice):
    await alice.post("/api/setup/mail", json={"address": "duo@gmail.com", "password": PASSWORD})
    FakeIMAP.password = "changed"  # noqa: S105
    try:
        conn = (await alice.post("/api/setup/mail/check")).json()["connection"]
    finally:
        FakeIMAP.password = PASSWORD.replace(" ", "")
    assert conn["state"] == "login" and "refused" in conn["state_detail"]


@respx.mock
async def test_admin_adds_ebay_key_in_the_browser(alice, bob):
    route = respx.post("https://api.ebay.com/identity/v1/oauth2/token").mock(
        side_effect=[httpx.Response(401), httpx.Response(200, json={"access_token": "t", "expires_in": 7200})]
    )
    key = {"client_id": "Duarte-Schnaepp-PRD-1234567890", "client_secret": "PRD-abcdef1234567890"}
    assert (await bob.put("/api/setup/ebay", json=key)).status_code == 403
    assert (await alice.put("/api/setup/ebay", json=key)).status_code == 422  # eBay said no
    r = await alice.put("/api/setup/ebay", json=key)
    assert r.status_code == 200 and r.json()["configured"] and route.call_count == 2
    ebay = next(s for s in (await alice.get("/api/sources")).json() if s["id"] == "ebay")
    assert ebay["state"] == "ready"
    assert (await alice.delete("/api/setup/ebay")).json()["configured"] is False
