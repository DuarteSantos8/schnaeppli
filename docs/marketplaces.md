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

## Galaxus and Digitec (supported) {#galaxus}

Through Galaxus' **official MCP interface for AI assistants** (`https://mcp.galaxus.ch`,
opened November 2026): no account or key, the shop's own product database, one tool
(`search_products`). Digitec shares the catalogue. The websites themselves block
automated clients, and Schnäppli never visits them.

Results are new retail products with current prices incl. VAT (no stock or delivery
times). Schnäppli also hands those prices to the analysis as the new-price reference
for used listings of the same search. Searches set to "used only" skip this source. A
price floor of a fifth of the budget keeps accessories out of searches for the main
item. Turn it off with `SCHNAEPPLI_GALAXUS_ENABLED=false`.

## Ricardo and tutti.ch (through their alert e-mails) {#alerts}

Neither has a public search API, and both turn automated clients away (Ricardo
answers 403; tutti's robots.txt closes listing pages). What both offer is a saved
search that e-mails new listings. Schnäppli reads those mails from a mailbox of its
own over IMAP, every five minutes, takes the listings out (link, title, price,
photo) and puts them into the matching search. It doesn't open the listing pages.

Setup (administrator, once):

1. Create a mailbox only for Schnäppli, e.g. `schnaeppli@your-domain`, and an app
   password for it. Don't use your personal mailbox: Schnäppli marks mails as read.
2. In `.env`: `SCHNAEPPLI_INBOX_IMAP_HOST` (e.g. `imappro.zoho.eu`),
   `SCHNAEPPLI_INBOX_IMAP_USER` (the address). Put the app password into
   `secrets/inbox_password`. Optional: `SCHNAEPPLI_INBOX_OWNER_EMAIL` (whose account the
   alerts belong to; default the first admin) and `SCHNAEPPLI_INBOX_ALLOWED_SENDERS`.
3. `docker compose up -d`.

Then, as the user:

1. In the mailbox your Ricardo / tutti accounts use, add a filter that forwards mails
   from `ricardo.ch` and `tutti.ch` to Schnäppli's address.
2. On each search, Schnäppli shows ready-made Ricardo and tutti links. Open them and
   save the search there.

Routing: a listing goes to the search whose own search terms best match the saved
search's name and the listing title. Listings that fit no active search are skipped
and counted. If alert mails stop yielding listings (layout changes), Settings →
Sources says so.

Limits: only listings that appear after the saved search was created arrive, and the
analysis has the alert's title, price and photo, not the full description.

## Your own shops {#shops}

Settings → Sources → **Your shops**: add any shop, and Schnäppli searches it with every
one of your searches (two search terms per run). Paste the address of a results page
from the shop's own search (Schnäppli finds the search word in it), or put `{query}`
where the word goes. A WooCommerce shop's plain address works too: Schnäppli then uses
WooCommerce's public Store API.

Adding a shop runs one real search and shows the first results, so you see straight
away whether it works. Schnäppli reads only what shops publish for machines:

- the schema.org product data (JSON-LD or microdata) on the search page, or
- the WooCommerce Store API.

It never fetches a page that robots.txt closes (wildcard rules included). It doesn't
get around bot checks either. A shop that answers 403/429 or shows a captcha is marked
"Blocks programs" and paused for a week. One request per shop and term, a few seconds
apart per host, cached for 30 minutes. Many large retailers close their search pages
to programs, and the test tells you so. eBay, Galaxus/Digitec, Ricardo, tutti and Amazon
can't be added here: the first four are built in, and Amazon forbids automated access.

## Facebook Marketplace (not supported)

No API, and Meta's terms prohibit automated collection. No permitted alternative is
known.

## Interdiscount, Toppreise (no search)

No public product search APIs. Interdiscount answers programs with 403, Toppreise with a
bot check, and Schnäppli doesn't get around either.
Single product pages can be added by link where robots.txt allows.

## Amazon (planned)

The Product Advertising API requires an Amazon Associates account with qualifying
sales. Planned as an optional adapter for users who have that access.

## Writing an adapter

Subclass `SourceAdapter`, implement `status()` (be honest about requirements) and
`search(SearchQuery) -> list[RawListing]`, register it in `sources/registry.py`, and
add tests with recorded responses. Respect the platform's terms, rate limits and
robots.txt. Pull requests that scrape against a site's terms won't be merged.
