"""Ricardo / tutti alert mails: parsing, routing and import."""

from email.message import EmailMessage

from sqlalchemy import select

from app.core.db import sessionmaker
from app.models import Listing, SearchMatch, SearchProfile
from app.services import inbox_import
from app.sources import inbox
from app.sources.inbox import InboxBatch, parse_alert

RICARDO_HTML = """
<html><head><style>.x{color:red}</style></head><body>
<table><tr><td>
  <a href="https://click.mail.ricardo.ch/?u=https%3A%2F%2Fwww.ricardo.ch%2Fde%2Fa%2Fsony-cyber-shot-dsc-rx100-1287654321%2F%3Futm_source%3Dalert">
    <img src="https://img.ricardostatic.ch/t_400x300/abc.jpg" width="200"></a>
  <a href="https://www.ricardo.ch/de/a/sony-cyber-shot-dsc-rx100-1287654321/">Sony Cyber-shot DSC-RX100, wie neu</a>
  <p>Sofort kaufen: CHF 185.00</p>
  <a href="https://www.ricardo.ch/de/a/sony-cyber-shot-dsc-rx100-1287654321/">Ansehen</a>
</td></tr><tr><td>
  <a href="https://www.ricardo.ch/de/a/canon-ixus-70-defekt-1299999999/">Canon Ixus 70 defekt</a>
  <span>Aktuelles Gebot 12.–</span>
  <img src="https://www.ricardo.ch/logo.png">
</td></tr></table>
<a href="https://www.ricardo.ch/de/myricardo/">Suchabo verwalten</a>
</body></html>
"""

TUTTI_TEXT = """Neue Inserate für deinen Suchauftrag "Olympus mju"

Olympus mju II, Film getestet
CHF 160
https://www.tutti.ch/de/vi/zuerich/foto-video/olympus-mju-ii-film-getestet/71234567
"""


def _mail(
    subject: str, html: str | None = None, text: str | None = None, sender="noreply@ricardo.ch"
) -> bytes:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, "schnaeppli@example.com", subject
    if html:
        m.set_content("see html")
        m.add_alternative(html, subtype="html")
    else:
        m.set_content(text or "")
    return bytes(m)


def test_parse_ricardo_alert_follows_redirects_and_finds_price_and_photo():
    a = parse_alert(_mail("Neue Angebote für «Sony RX100»", html=RICARDO_HTML))
    assert a.site == "ricardo" and a.search_name == "Sony RX100"
    by_id = {x.external_id: x for x in a.listings}
    assert set(by_id) == {"1287654321", "1299999999"}  # the account link isn't a listing
    rx = by_id["1287654321"]
    assert rx.title == "Sony Cyber-shot DSC-RX100, wie neu"
    assert str(rx.price) == "185.00"
    assert rx.url == "https://www.ricardo.ch/de/a/sony-cyber-shot-dsc-rx100-1287654321/"
    assert rx.images == ["https://img.ricardostatic.ch/t_400x300/abc.jpg"]
    ixus = by_id["1299999999"]
    assert str(ixus.price) == "12" and ixus.images == []  # logos are not listing photos


def test_parse_tutti_plain_text_alert():
    a = parse_alert(_mail('Neue Inserate für "Olympus mju"', text=TUTTI_TEXT, sender="info@tutti.ch"))
    assert a.site == "tutti" and a.search_name == "Olympus mju"
    (it,) = a.listings
    assert it.external_id == "71234567" and str(it.price) == "160"


def test_mail_without_alert_links_is_ignored():
    a = parse_alert(_mail("Hallo", text="Ein ganz normales Mail ohne Inserate."))
    assert a.listings == [] and not a.had_links


async def test_import_routes_to_matching_search_only(alice, monkeypatch):
    cam = (
        await alice.post("/api/searches", json={"title": "Sony RX100 compact camera", "max_budget": 300})
    ).json()
    await alice.post("/api/searches", json={"title": "NAS with 4 drive bays", "max_budget": 600})
    seen = []

    async def fake_fetch(sender_ok=lambda f: True):
        alert = parse_alert(_mail("Neue Angebote für «Sony RX100»", html=RICARDO_HTML))
        return InboxBatch([alert], unreadable=1, checked_at=None), [b"1", b"2"]

    async def fake_seen(ids):
        seen.extend(ids)

    monkeypatch.setattr(inbox, "configured", lambda: True)
    monkeypatch.setattr(inbox, "fetch_alerts", fake_fetch)
    monkeypatch.setattr(inbox, "mark_seen", fake_seen)
    async with sessionmaker()() as db:
        ids = await inbox_import.import_alerts(db)
        matches = (
            await db.execute(select(SearchMatch, SearchProfile, Listing).join(SearchProfile).join(Listing))
        ).all()
        assert {s.title for _m, s, _l in matches} == {"Sony RX100 compact camera"}
        assert {lst.source for _m, _s, lst in matches} == {"ricardo"}
        assert str(matches[0][0].search_id) == cam["id"]
        st = await inbox_import.status(db)
    assert st["imported"] == 2 and st["unreadable"] == 1 and st["totals"]["ricardo"] == 2
    assert seen == [b"1", b"2"]  # marked read only after storing
    assert len(ids) <= 2


async def test_import_failure_is_recorded_not_raised(alice, monkeypatch):
    async def broken(sender_ok=lambda f: True):
        raise OSError("login failed")

    monkeypatch.setattr(inbox, "configured", lambda: True)
    monkeypatch.setattr(inbox, "fetch_alerts", broken)
    async with sessionmaker()() as db:
        assert await inbox_import.import_alerts(db) == []
        assert "login failed" in (await inbox_import.status(db))["error"]


FACEBOOK_HTML = """<html><body>
<p>Neue Angebote für deine gespeicherte Suche „Fujifilm X100“</p>
<a href="https://www.facebook.com/n/?marketplace%2Fitem%2F1234567890123%2F&amp;aref=1&amp;medium=email">
  <img src="https://scontent.xx.fbcdn.net/v/x100.jpg" width="120"></a>
<a href="https://www.facebook.com/n/?marketplace%2Fitem%2F1234567890123%2F&amp;aref=1">Fujifilm X100V silber</a>
<span>CHF 1’150</span>
</body></html>"""

TOPPREISE_HTML = """<html><body>
<p>Preisalarm: Ihr Wunschpreis wurde erreicht</p>
<a href="https://www.toppreise.ch/preisvergleich/Digitalkameras/FUJIFILM-X100VI-Silber-p771234?utm_source=preisalarm">FUJIFILM X100VI Silber</a>
<p>Neuer Bestpreis: CHF 1'399.00 bei einem Händler</p>
</body></html>"""


def test_facebook_and_toppreise_alert_mails():
    fb = parse_alert(
        _mail("Neue Angebote für „Fujifilm X100“", html=FACEBOOK_HTML, sender="notification@facebookmail.com")
    )
    (item,) = fb.listings
    assert item.source == "facebook" and item.external_id == "1234567890123"
    assert item.url.rstrip("/") == "https://www.facebook.com/marketplace/item/1234567890123"
    assert item.title == "Fujifilm X100V silber" and str(item.price) == "1150" and not item.is_new_retail
    tp = parse_alert(
        _mail("Preisalarm «FUJIFILM X100VI»", html=TOPPREISE_HTML, sender="noreply@toppreise.ch")
    )
    (item,) = tp.listings
    assert item.source == "toppreise" and item.external_id == "771234" and item.is_new_retail
    assert str(item.price) == "1399.00" and item.condition == "new"
    from app.sources.mailbox import _from_any, _sender_is_alert

    assert _sender_is_alert("Facebook <notification@facebookmail.com>") and not _sender_is_alert(
        "x@facebook.example"
    )
    assert _from_any()[:4] == ["OR", "FROM", '"ricardo.ch"', "OR"]
