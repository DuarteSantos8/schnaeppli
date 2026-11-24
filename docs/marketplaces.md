# Marketplaces

Each source is an adapter in `backend/app/sources/`. Adapters may only use permitted
access: official APIs, single user-initiated page reads that robots.txt allows, or data
the user forwards. Schnäppli doesn't scrape sites that forbid it and doesn't work around
bot protection or logins. Sources without a permitted route are registered as
unsupported, so the app shows their real status.

Status as of November 2026:

## eBay (supported) {#ebay}

Official **Browse API** (`item_summary/search`), client-credentials OAuth with the
public scope; no eBay user login involved.

Setup:

1. Create a free account at developer.ebay.com and an application.
2. Copy the **Production** App ID (Client ID) and Cert ID (Client Secret) into
   `secrets/ebay_client_id` and `secrets/ebay_client_secret`.
3. Set `SCHNAEPPLI_EBAY_MARKETPLACE` (default `EBAY_CH`; `EBAY_DE`, `EBAY_AT`, … also work).
4. Restart: `docker compose up -d`.

Notes: prices are **asking prices**, never sold prices (eBay's sold-price API is
restricted). Shipping costs are used when eBay returns them. Only the country is sent
to eBay as delivery context, not your postal code. eBay's default quota is 5,000
calls/day; Schnäppli makes about one call per search term per run.

Not yet verified with live keys: whether `EBAY_CH` returns search results for every
category. If it returns nothing, try `EBAY_DE`.

## Add by link (supported)

On a search, **Add by link** reads one page that you paste, only if the site's
robots.txt allows automated access, and extracts the structured product data shops
publish (schema.org JSON-LD, then OpenGraph). Works with most retailers. If a site
refuses automated access, Schnäppli says so; it doesn't retry around it.

## Ricardo (not supported)

Ricardo's API is for contracted sellers and partners and doesn't offer search; the
robots.txt disallows automated search pages. **Planned alternative:** an inbox adapter
that reads Ricardo's own saved-search alert e-mails that you forward to Schnäppli.

## tutti.ch (not supported)

No public API; robots.txt disallows the API and listing paths. Same planned
alternative as Ricardo.

## Facebook Marketplace (not supported)

No API, and Meta's terms prohibit automated collection. No permitted alternative is
known.

## Digitec, Galaxus, Interdiscount, Toppreise (no search)

No public product search APIs. Single product pages can be added by link where
robots.txt allows.

## Amazon (planned)

The Product Advertising API requires an Amazon Associates account with qualifying
sales. Planned as an optional adapter for users who have that access.

## Writing an adapter

Subclass `SourceAdapter`, implement `status()` (be honest about requirements) and
`search(SearchQuery) -> list[RawListing]`, register it in `sources/registry.py`, and
add tests with recorded responses. Respect the platform's terms, rate limits and
robots.txt. Pull requests that scrape against a site's terms won't be merged.
