# ADR 0004: Only permitted marketplace access

**Decision.** Adapters use official APIs, user-initiated single page reads that
robots.txt allows, or data the user forwards. Sources without such a route are
listed as unsupported, with the reason, instead of being scraped.

**Why.** Scraping against terms of service or around bot protection is fragile,
can get users' IPs blocked, and isn't something an open-source project should ship.
Being honest in the UI about what works builds more trust than a fake integration.
