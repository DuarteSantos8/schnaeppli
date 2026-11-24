"""All known sources and their honest status."""

from __future__ import annotations

from functools import lru_cache

from app.sources.base import SourceAdapter, UnsupportedSource
from app.sources.ebay import EbayAdapter

_EMAIL_ALT = (
    "Planned: forward the site's own saved-search alert e-mails to Schnäppli's inbox "
    "adapter, or add single listings by link."
)


@lru_cache
def all_sources() -> dict[str, SourceAdapter]:
    sources: list[SourceAdapter] = [
        EbayAdapter(),
        UnsupportedSource(
            "ricardo",
            "Ricardo",
            "secondhand",
            "https://www.ricardo.ch",
            "Ricardo's API is for contracted sellers and partners, not for search, and its robots.txt "
            "disallows automated search pages.",
            _EMAIL_ALT,
        ),
        UnsupportedSource(
            "tutti",
            "tutti.ch",
            "secondhand",
            "https://www.tutti.ch",
            "No public API; robots.txt disallows the API and listing paths for automated clients.",
            _EMAIL_ALT,
        ),
        UnsupportedSource(
            "facebook",
            "Facebook Marketplace",
            "secondhand",
            "https://www.facebook.com/marketplace",
            "Meta offers no Marketplace search API, and its terms prohibit automated collection.",
            "No permitted alternative is known.",
        ),
        UnsupportedSource(
            "digitec",
            "Digitec",
            "retail",
            "https://www.digitec.ch",
            "No public product search API.",
            "Add single products by link (robots.txt permitting).",
        ),
        UnsupportedSource(
            "galaxus",
            "Galaxus",
            "retail",
            "https://www.galaxus.ch",
            "No public product search API.",
            "Add single products by link (robots.txt permitting).",
        ),
        UnsupportedSource(
            "interdiscount",
            "Interdiscount",
            "retail",
            "https://www.interdiscount.ch",
            "No public product search API.",
            "Add single products by link (robots.txt permitting).",
        ),
        UnsupportedSource(
            "toppreise",
            "Toppreise.ch",
            "retail",
            "https://www.toppreise.ch",
            "No public API for price comparisons.",
            "Add single products by link (robots.txt permitting).",
        ),
        UnsupportedSource(
            "amazon",
            "Amazon",
            "retail",
            "https://www.amazon.de",
            "Amazon's product API requires an Associates account with qualifying sales; not implemented yet.",
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
