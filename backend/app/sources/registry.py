"""All known sources and their honest status."""

from __future__ import annotations

from functools import lru_cache

from app.sources.base import SourceAdapter, SourceStatus, UnsupportedSource
from app.sources.ebay import EbayAdapter
from app.sources.galaxus import GalaxusAdapter

_EMAIL_ALT = (
    "Works through the site's own saved-search e-mails: save the search there once, "
    "and Schnäppli reads the alert mails from its inbox (Settings → Sources)."
)


class AlertSource(SourceAdapter):
    """A marketplace reached through its own alert e-mails (see sources/inbox.py)."""

    def __init__(self, id: str, name: str, homepage: str, why: str, kind: str = "secondhand"):
        self.id, self.name, self.homepage, self._why, self.kind = id, name, homepage, why, kind

    def status(self) -> SourceStatus:
        from app.sources import inbox

        if inbox.configured():
            return SourceStatus("alerts", self._why, alternatives=_EMAIL_ALT)
        return SourceStatus(
            "needs_credentials",
            self._why,
            alternatives="Needs a mailbox for the alert e-mails, set up by the administrator "
            "(see docs/marketplaces.md).",
        )


@lru_cache
def all_sources() -> dict[str, SourceAdapter]:
    sources: list[SourceAdapter] = [
        EbayAdapter(),
        GalaxusAdapter(),
        AlertSource(
            "ricardo",
            "Ricardo",
            "https://www.ricardo.ch",
            "No public search API (the API is for contracted sellers), and the site blocks automated "
            "clients, so Schnäppli reads Ricardo's own saved-search e-mails instead.",
        ),
        AlertSource(
            "tutti",
            "tutti.ch",
            "https://www.tutti.ch",
            "No public API, and its robots.txt closes listing pages to automated clients, so Schnäppli "
            "reads tutti's own saved-search e-mails instead.",
        ),
        AlertSource(
            "facebook",
            "Facebook Marketplace",
            "https://www.facebook.com/marketplace",
            "Meta offers no Marketplace search API and its terms prohibit automated collection, so "
            "Schnäppli reads the e-mails of your Marketplace saved searches instead (they can arrive late).",
        ),
        UnsupportedSource(
            "interdiscount",
            "Interdiscount",
            "retail",
            "https://www.interdiscount.ch",
            "No public product search API, and the site turns automated clients away (403).",
            "Add single products by link.",
        ),
        AlertSource(
            "toppreise",
            "Toppreise.ch",
            "https://www.toppreise.ch",
            "Its API needs permission (requested) and the site shows programs a bot check, so Schnäppli "
            "reads Toppreise's own price-alert e-mails instead: set an alert on a product there.",
            kind="retail",
        ),
        UnsupportedSource(
            "amazon",
            "Amazon",
            "retail",
            "https://www.amazon.de",
            "Amazon's terms forbid automated access and its robots.txt shuts out AI agents. Its product API "
            "needs an Associates account with qualifying sales.",
            "Planned as an optional adapter for users with Associates access.",
            state="planned",
        ),
    ]
    return {s.id: s for s in sources}


def get_source(source_id: str) -> SourceAdapter | None:
    return all_sources().get(source_id)


def enabled_sources_for(search_sources: dict) -> list[SourceAdapter]:
    """Available sources the search uses. Empty config = all available sources."""
    out = []
    for sid, adapter in all_sources().items():
        if not adapter.status().available:
            continue
        cfg = (search_sources or {}).get(sid, {})
        if cfg.get("enabled", True):
            out.append(adapter)
    out.sort(key=lambda a: (search_sources or {}).get(a.id, {}).get("priority", 5))
    return out
