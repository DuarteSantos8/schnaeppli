"""Model capability and pricing metadata.

Prices are USD per 1M tokens. None of the supported providers return a monetary
cost in their API responses, so every cost Schnäppli shows is *estimated* from the
reported token usage and this table, and the UI labels it as such. Administrators
can override or extend the table at runtime (app setting ``model_catalog``).

Anthropic prices: platform.claude.com pricing, as of 2026-11. OpenAI and Gemini
entries ship without prices on purpose: their price lists change often and we
won't guess. Until an admin enters a price, costs for those models are shown as
"price unknown" and budget limits count tokens with a conservative fallback rate.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class ModelInfo:
    provider: str
    id: str
    label: str
    vision: bool
    structured: bool
    input_per_m: float | None = None
    output_per_m: float | None = None
    cache_read_per_m: float | None = None
    cache_write_per_m: float | None = None
    notes: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return asdict(self)


# Fallback used for *budget enforcement only* when a model has no price, so that an
# unknown price can never silently bypass a spending limit.
FALLBACK_INPUT_PER_M = 10.0
FALLBACK_OUTPUT_PER_M = 50.0

BUILTIN: list[ModelInfo] = [
    ModelInfo(
        "anthropic", "claude-opus-5-5", "Claude Opus 5.5", True, True, 4.0, 20.0, 0.20, 5.0, tags=("default",)
    ),
    ModelInfo("anthropic", "claude-sonnet-5-5", "Claude Sonnet 5.5", True, True, 2.0, 10.0, 0.10, 2.5),
    ModelInfo(
        "anthropic",
        "claude-haiku-5-5",
        "Claude Haiku 5.5",
        True,
        True,
        0.10,
        0.50,
        0.01,
        0.125,
        notes="Prices apply to prompts up to 100K tokens.",
    ),
    ModelInfo("anthropic", "claude-fable-5-2", "Claude Fable 5.2", True, True, 8.0, 40.0, 0.20, 10.0),
    ModelInfo("openai", "gpt-5", "GPT-5", True, True, notes="Enter current pricing in Settings → AI."),
    ModelInfo(
        "openai", "gpt-5-mini", "GPT-5 mini", True, True, notes="Enter current pricing in Settings → AI."
    ),
    ModelInfo(
        "gemini",
        "gemini-2.5-pro",
        "Gemini 2.5 Pro",
        True,
        True,
        notes="Enter current pricing in Settings → AI.",
    ),
    ModelInfo(
        "gemini",
        "gemini-2.5-flash",
        "Gemini 2.5 Flash",
        True,
        True,
        notes="Enter current pricing in Settings → AI.",
    ),
]

DEFAULT_MODEL = {
    "anthropic": "claude-opus-5-5",
    "openai": "gpt-5",
    "gemini": "gemini-2.5-pro",
    "claude_code": "claude-opus-5-5",
}
PROVIDERS = ("anthropic", "openai", "gemini", "claude_code")
# Providers paid by a subscription instead of per token: no money is counted against
# the user's USD limits (count limits still apply).
PLAN_PROVIDERS = {"claude_code"}


def catalog(overrides: dict | None = None) -> dict[str, ModelInfo]:
    models = {f"{m.provider}:{m.id}": m for m in BUILTIN}
    for m in BUILTIN:
        if m.provider == "anthropic":
            models[f"claude_code:{m.id}"] = ModelInfo(
                "claude_code",
                m.id,
                m.label,
                m.vision,
                True,
                0.0,
                0.0,
                0.0,
                0.0,
                notes="Covered by your Claude plan",
            )
    for key, raw in (overrides or {}).items():
        try:
            base = models.get(key)
            data = (base.as_dict() if base else {}) | raw
            data["tags"] = tuple(data.get("tags") or ())
            models[key] = ModelInfo(**data)
        except TypeError:
            continue
    return models


def lookup(provider: str, model: str, overrides: dict | None = None) -> ModelInfo:
    if provider == "claude_code":  # same models and capabilities as the Anthropic API
        base = catalog(overrides).get(f"anthropic:{model}")
        if base:
            return ModelInfo(
                "claude_code",
                model,
                base.label,
                base.vision,
                True,
                0.0,
                0.0,
                0.0,
                0.0,
                notes="Covered by your Claude plan",
            )
        return ModelInfo("claude_code", model, model, True, True, 0.0, 0.0, 0.0, 0.0)
    found = catalog(overrides).get(f"{provider}:{model}")
    if found:
        return found
    # Unknown custom model: assume no vision, rely on JSON-mode validation.
    return ModelInfo(provider, model, model, vision=False, structured=True, notes="Custom model")


def estimate_cost(
    info: ModelInfo, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0
) -> tuple[float, bool]:
    """Returns (usd, price_known)."""
    if info.input_per_m is None or info.output_per_m is None:
        cost = (input_tokens + cache_read + cache_write) * FALLBACK_INPUT_PER_M / 1e6 + (
            output_tokens * FALLBACK_OUTPUT_PER_M / 1e6
        )
        return cost, False
    cost = input_tokens * info.input_per_m / 1e6 + output_tokens * info.output_per_m / 1e6
    cost += (
        cache_read * (info.cache_read_per_m if info.cache_read_per_m is not None else info.input_per_m) / 1e6
    )
    cost += (
        cache_write
        * (info.cache_write_per_m if info.cache_write_per_m is not None else info.input_per_m)
        / 1e6
    )
    return cost, True
