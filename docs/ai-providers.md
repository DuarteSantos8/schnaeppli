# AI providers & costs

Schnäppli uses the official SDKs of Anthropic, OpenAI and Google Gemini behind one
provider interface. Each user can bring their own key; an administrator can add a
shared key that users without their own fall back to.

## Adding a key

**Settings → AI → Add API key.** The key is tested (a model list and a one-word
completion) and stored encrypted. Under *Models per task* you can choose a model per
analysis type.

- **Anthropic**: create a key at console.anthropic.com. A Claude.ai subscription
  can't be used by third-party apps; you need an API key.
- **OpenAI**: platform.openai.com → API keys.
- **Google Gemini**: aistudio.google.com → Get API key.

## Analysis types

| Task | When | Notes |
| --- | --- | --- |
| Understanding requests | creating a search | structured output |
| Quick scan | each new listing that passes the free pre-filter | the main cost driver, limited per run |
| Photo check | promising listings, or on request | needs a vision-capable model |
| Deep analysis | on request | more context, more tokens |
| Digest intro | each digest with results | short |
| Assistant | each chat message | |

## Costs

None of the providers returns a monetary cost with a response. Schnäppli records the
**token counts each provider reports** (input, output, cached) and **estimates** cost
from a price table. Every amount in the app is labelled as an estimate.

- Anthropic prices are built in.
- OpenAI and Gemini prices change often and ship empty. An admin can enter them under
  **Settings → AI → Model prices**. Until then, the app shows "price unknown", and
  budget checks count those calls at a deliberately high fallback rate so a missing
  price can never let spending slip past a limit.

## Limits

Per user, under **Settings → AI → Spending limits**:

- daily and monthly limits in USD, a warning threshold (default 75 %) and a pause
  threshold (default 100 %),
- maximum deep analyses and photo checks per day, analyses per search run,
- automatic pause when the monthly limit is reached.

Limits are checked **before** every call with a conservative reservation for that
call's size, so a limit isn't exceeded silently. When analysis is paused, searches
keep collecting listings; they're scored once you raise the limit or the month resets.

## Keeping costs down

- Free pre-filtering (excluded words, "wanted" ads, far over budget, wrong condition).
- Assessments are cached by listing content (not price): a price drop rescores for free.
- Photos only for promising listings.
- Stable system prompts are marked for prompt caching (Anthropic).
- The digest summarises existing results.

## Capabilities

The model catalogue records whether a model accepts images. Photo checks are skipped
for models without vision. Unknown custom models are treated as text-only.
