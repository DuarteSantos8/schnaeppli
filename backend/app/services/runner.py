"""Search runs: collect listings from sources. No AI here; analysis is queued
separately and limited per run."""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import utcnow
from app.models import SearchMatch, SearchProfile, SearchRun, User
from app.services import app_secrets
from app.services import listings as listing_svc
from app.services.schedule import next_search_run
from app.sources import shops
from app.sources.base import SearchQuery, SourceError
from app.sources.registry import enabled_sources_for

log = structlog.get_logger()
MAX_QUERIES = 6
SHOP_QUERIES = 2  # user-added shops get fewer requests per run


def queries_for(search: SearchProfile) -> list[str]:
    spec = search.spec or {}
    qs = [q for q in spec.get("queries", []) if q and q.strip()]
    if not qs:
        qs = [p["name"] for p in spec.get("desired_products", [])]
        if spec.get("allow_alternatives", True):
            qs += [p["name"] for p in spec.get("alternatives", [])]
    if not qs:
        qs = [search.title]
    seen, out = set(), []
    for q in qs:
        k = q.strip().lower()
        if k not in seen:
            seen.add(k)
            out.append(q.strip()[:100])
    return out[:MAX_QUERIES]


async def run_search(db: AsyncSession, search_id: uuid.UUID) -> tuple[SearchRun, list[uuid.UUID]]:
    """Returns the run and the match ids to analyse (already limited)."""
    search = await db.get(SearchProfile, search_id)
    if search is None:
        raise ValueError("search not found")
    user = await db.get(User, search.user_id)
    assert user
    run = SearchRun(search_id=search.id)
    db.add(run)
    await db.flush()

    await app_secrets.refresh(db)  # an eBay key added in the browser since the last run
    sources = enabled_sources_for(search.sources)
    sources += [
        a
        for a in await shops.adapters_for(db, user.id)
        if (search.sources or {}).get(a.id, {}).get("enabled", True)
    ]
    report: dict = {}
    new_match_ids: list[uuid.UUID] = []
    repriced: list[uuid.UUID] = []
    seen_listing_ids: set[uuid.UUID] = set()
    if not sources:
        report["_"] = {"error": "No automated source is available. Configure eBay or add listings by link."}

    for adapter in sources:
        stats = {"queries": 0, "results": 0, "new": 0}
        qs = queries_for(search)
        for q in qs[:SHOP_QUERIES] if isinstance(adapter, shops.ShopAdapter) else qs:
            try:
                results = await adapter.search(
                    SearchQuery(
                        text=q,
                        max_price=float(search.max_budget) * 1.25 if search.max_budget else None,
                        currency=search.currency,
                        condition=search.condition,
                        country=user.country or "CH",
                    )
                )
            except SourceError as e:
                stats["error"] = str(e)[:200]
                log.warning("source_failed", source=adapter.id, error=str(e))
                if not e.retryable:
                    break
                continue
            stats["queries"] += 1
            stats["results"] += len(results)
            for raw in results:
                if not raw.external_id or not raw.url:
                    continue
                listing, _is_new, previous = await listing_svc.upsert_listing(db, raw)
                if listing.id in seen_listing_ids:
                    continue
                seen_listing_ids.add(listing.id)
                match, created = await listing_svc.ensure_match(db, user, search, listing, previous)
                await db.flush()
                if created:
                    stats["new"] += 1
                    if match.analysis_state == "queued":
                        new_match_ids.append(match.id)
                elif match.price_dropped_at and previous is not None and match.analysis_state == "done":
                    repriced.append(match.id)
        report[adapter.id] = stats
    await shops.record(db, sources)

    # Retry earlier matches that were queued but not analysed (e.g. budget reset).
    conds = [SearchMatch.search_id == search.id, SearchMatch.analysis_state.in_(("queued", "limited"))]
    if new_match_ids:
        conds.append(SearchMatch.id.not_in(new_match_ids))
    pending = (await db.scalars(select(SearchMatch.id).where(*conds).limit(50))).all()
    limit = int((user.ai_limits or {}).get("max_analyses_per_run", 15))
    to_analyse = (new_match_ids + list(pending))[:limit]

    run.fetched = sum(v.get("results", 0) for v in report.values() if isinstance(v, dict))
    run.new_matches = sum(v.get("new", 0) for v in report.values() if isinstance(v, dict))
    run.source_report = report
    errors = [f"{k}: {v['error']}" for k, v in report.items() if isinstance(v, dict) and v.get("error")]
    run.status = "failed" if errors and run.fetched == 0 else ("partial" if errors else "ok")
    run.error = "; ".join(errors)[:500] or None
    run.finished_at = utcnow()
    search.last_run_at = run.finished_at
    search.last_error = run.error
    search.next_run_at = next_search_run(search, user, run.finished_at)
    await db.commit()
    return run, to_analyse + repriced
