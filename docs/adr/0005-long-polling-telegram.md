# ADR 0005: Telegram via long polling

**Decision.** The worker polls `getUpdates` instead of registering a webhook.

**Why.** Schnäppli is meant to be reachable only on a private network or VPN, so
Telegram can't call in. Long polling is outbound-only and needs no public endpoint.
