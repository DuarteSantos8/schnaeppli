# Telegram

Telegram is Schnäppli's notification channel: instant alerts for exceptional deals
(and optionally good ones), price drops, search problems, AI budget warnings, and the
scheduled digest.

## Server setup (administrator)

1. In Telegram, talk to **@BotFather**, send `/newbot`, choose a name and a username.
2. Put the token into `secrets/telegram_bot_token` (one line, nothing else).
3. Set `SCHNAEPPLI_TELEGRAM_BOT_USERNAME=<username without @>` in `.env`.
4. `docker compose up -d` (restarts the API and worker).

The worker uses **long polling** (`getUpdates`), so no public webhook is needed;
Schnäppli can stay on your private network. Don't use the same bot token for another
service that also polls: Telegram delivers each update to only one poller.

## Linking an account (every user)

**Settings → Notifications → Connect Telegram.** Schnäppli shows a one-time code (valid
10 minutes) and a button that opens the bot with `/start <code>`. Schnäppli then stores
your chat id. In the bot, `/stop` disconnects.

- Codes are random, stored hashed and single use.
- One Telegram chat belongs to one Schnäppli account.
- Only private chats are accepted.

## What you receive

Deal alerts include the photo, title, price (with shipping and whether it's estimated),
source, Deal Score, estimated market value with its source, a one-line assessment and
buttons to open the listing or Schnäppli. Every notification is recorded with a dedupe key,
so nothing is sent twice. The digest stays quiet when nothing new was found.
