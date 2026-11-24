"""Provider abstraction. Each provider turns a ``Prompt`` into a validated
Pydantic object (or text) plus normalized token usage.

Only official SDKs are used. Nothing here knows about users, budgets or the
database; see ``gateway.py`` for that.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


@dataclass
class ImageInput:
    data: bytes
    media_type: str  # image/jpeg | image/png | image/webp | image/gif


@dataclass
class Prompt:
    system: str
    user: str
    images: list[ImageInput] = field(default_factory=list)
    # Optional prior turns for chat: [{"role": "user"|"assistant", "content": str}]
    history: list[dict] = field(default_factory=list)
    max_tokens: int = 4000
    effort: str = "low"  # low | medium | high — maps to provider knobs where supported


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class Completion:
    text: str
    parsed: Any
    usage: Usage
    model: str
    stop_reason: str | None = None
    # Claude Code bridge: what the tokens would have cost on the API (covered by the plan).
    api_equivalent_usd: float | None = None


class ProviderError(Exception):
    """Safe-to-display error. Never contains the API key."""

    def __init__(self, message: str, *, retryable: bool = False, auth: bool = False):
        super().__init__(message)
        self.retryable = retryable
        self.auth = auth


class Provider:
    name: str

    def __init__(self, api_key: str, base_url: str | None = None):
        self._api_key = api_key
        self._base_url = base_url

    def __repr__(self) -> str:  # never leak the key through logs
        return f"<{type(self).__name__}>"

    async def complete(self, model: str, prompt: Prompt, schema: type[T] | None = None) -> Completion:
        raise NotImplementedError

    async def list_models(self) -> list[str]:
        raise NotImplementedError


def _validate(schema: type[T] | None, text: str) -> Any:
    if schema is None:
        return None
    try:
        return schema.model_validate_json(_strip_fences(text))
    except ValidationError as e:
        raise ProviderError(
            f"The model returned data that does not match the expected format ({e.error_count()} errors)."
        ) from e


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    return t


# ------------------------------------------------------------------ Anthropic
class AnthropicProvider(Provider):
    name = "anthropic"

    def _client(self):
        import anthropic

        return anthropic.AsyncAnthropic(
            api_key=self._api_key, base_url=self._base_url, max_retries=2, timeout=120
        )

    async def complete(self, model: str, prompt: Prompt, schema: type[T] | None = None) -> Completion:
        import anthropic

        content: list[dict] = []
        for img in prompt.images:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img.media_type,
                        "data": base64.b64encode(img.data).decode(),
                    },
                }
            )
        content.append({"type": "text", "text": prompt.user})
        messages = [*({"role": m["role"], "content": m["content"]} for m in prompt.history)]
        messages.append({"role": "user", "content": content})
        # Stable system prompt first and cached: the per-request content goes last.
        system = [{"type": "text", "text": prompt.system, "cache_control": {"type": "ephemeral"}}]
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": prompt.max_tokens,
            "system": system,
            "messages": messages,
            "output_config": {"effort": prompt.effort},
        }
        client = self._client()
        try:
            if schema is not None:
                resp = await client.messages.parse(output_format=schema, **kwargs)
            else:
                resp = await client.messages.create(**kwargs)
        except anthropic.AuthenticationError as e:
            raise ProviderError("Anthropic rejected the API key.", auth=True) from e
        except anthropic.PermissionDeniedError as e:
            raise ProviderError("This API key has no access to the selected model.", auth=True) from e
        except anthropic.NotFoundError as e:
            raise ProviderError(f"Model '{model}' was not found.") from e
        except anthropic.RateLimitError as e:
            raise ProviderError("Anthropic rate limit reached; will retry later.", retryable=True) from e
        except anthropic.BadRequestError as e:
            raise ProviderError(f"Anthropic rejected the request: {_short(e)}") from e
        except anthropic.APIStatusError as e:
            raise ProviderError(f"Anthropic error {e.status_code}.", retryable=e.status_code >= 500) from e
        except anthropic.APIConnectionError as e:
            raise ProviderError("Could not reach Anthropic.", retryable=True) from e
        except ValidationError as e:
            raise ProviderError("The model returned data that does not match the expected format.") from e
        finally:
            await client.close()

        u = resp.usage
        usage = Usage(
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        )
        if resp.stop_reason == "refusal":
            raise ProviderError("The model declined to answer this request.")
        if resp.stop_reason == "max_tokens":
            raise ProviderError("The answer was cut off (max tokens).", retryable=False)
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        parsed = getattr(resp, "parsed_output", None) if schema is not None else None
        if schema is not None and parsed is None:
            parsed = _validate(schema, text)
        return Completion(
            text=text, parsed=parsed, usage=usage, model=resp.model, stop_reason=resp.stop_reason
        )

    async def list_models(self) -> list[str]:
        import anthropic

        client = self._client()
        try:
            return [m.id async for m in client.models.list(limit=100)]
        except anthropic.AuthenticationError as e:
            raise ProviderError("Anthropic rejected the API key.", auth=True) from e
        except anthropic.APIError as e:
            raise ProviderError(f"Anthropic error: {_short(e)}") from e
        finally:
            await client.close()


# --------------------------------------------------------------------- OpenAI
class OpenAIProvider(Provider):
    name = "openai"

    def _client(self):
        import openai

        return openai.AsyncOpenAI(api_key=self._api_key, base_url=self._base_url, max_retries=2, timeout=120)

    async def complete(self, model: str, prompt: Prompt, schema: type[T] | None = None) -> Completion:
        import openai

        content: list[dict] = [{"type": "input_text", "text": prompt.user}]
        for img in prompt.images:
            b64 = base64.b64encode(img.data).decode()
            content.append({"type": "input_image", "image_url": f"data:{img.media_type};base64,{b64}"})
        inputs: list[dict] = [{"role": m["role"], "content": m["content"]} for m in prompt.history]
        inputs.append({"role": "user", "content": content})
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": prompt.system,
            "input": inputs,
            "max_output_tokens": prompt.max_tokens,
        }
        client = self._client()
        try:
            if schema is not None:
                resp = await client.responses.parse(text_format=schema, **kwargs)
            else:
                resp = await client.responses.create(**kwargs)
        except openai.AuthenticationError as e:
            raise ProviderError("OpenAI rejected the API key.", auth=True) from e
        except openai.PermissionDeniedError as e:
            raise ProviderError("This API key has no access to the selected model.", auth=True) from e
        except openai.NotFoundError as e:
            raise ProviderError(f"Model '{model}' was not found.") from e
        except openai.RateLimitError as e:
            raise ProviderError("OpenAI rate limit or quota reached.", retryable=True) from e
        except openai.BadRequestError as e:
            raise ProviderError(f"OpenAI rejected the request: {_short(e)}") from e
        except openai.APIStatusError as e:
            raise ProviderError(f"OpenAI error {e.status_code}.", retryable=e.status_code >= 500) from e
        except openai.APIConnectionError as e:
            raise ProviderError("Could not reach OpenAI.", retryable=True) from e
        except ValidationError as e:
            raise ProviderError("The model returned data that does not match the expected format.") from e
        finally:
            await client.close()

        u = resp.usage
        cached = 0
        if u is not None and getattr(u, "input_tokens_details", None) is not None:
            cached = getattr(u.input_tokens_details, "cached_tokens", 0) or 0
        usage = Usage(
            input_tokens=(u.input_tokens - cached) if u else 0,
            output_tokens=u.output_tokens if u else 0,
            cache_read_tokens=cached,
        )
        text = resp.output_text or ""
        parsed = getattr(resp, "output_parsed", None) if schema is not None else None
        if schema is not None and parsed is None:
            parsed = _validate(schema, text)
        return Completion(text=text, parsed=parsed, usage=usage, model=resp.model, stop_reason=resp.status)

    async def list_models(self) -> list[str]:
        import openai

        client = self._client()
        try:
            return sorted([m.id async for m in client.models.list()])
        except openai.AuthenticationError as e:
            raise ProviderError("OpenAI rejected the API key.", auth=True) from e
        except openai.APIError as e:
            raise ProviderError(f"OpenAI error: {_short(e)}") from e
        finally:
            await client.close()


# --------------------------------------------------------------------- Gemini
class GeminiProvider(Provider):
    name = "gemini"

    def _client(self):
        from google import genai

        return genai.Client(api_key=self._api_key)

    async def complete(self, model: str, prompt: Prompt, schema: type[T] | None = None) -> Completion:
        from google.genai import errors, types

        parts: list[Any] = [types.Part.from_bytes(data=i.data, mime_type=i.media_type) for i in prompt.images]
        parts.append(types.Part.from_text(text=prompt.user))
        contents: list[Any] = [
            types.Content(
                role="model" if m["role"] == "assistant" else "user",
                parts=[types.Part.from_text(text=m["content"])],
            )
            for m in prompt.history
        ]
        contents.append(types.Content(role="user", parts=parts))
        config = types.GenerateContentConfig(
            system_instruction=prompt.system,
            max_output_tokens=prompt.max_tokens,
            response_mime_type="application/json" if schema is not None else None,
            response_schema=schema if schema is not None else None,
        )
        client = self._client()
        try:
            resp = await client.aio.models.generate_content(model=model, contents=contents, config=config)
        except errors.ClientError as e:
            code = getattr(e, "code", 400)
            if code in (401, 403):
                raise ProviderError("Google rejected the API key.", auth=True) from e
            if code == 404:
                raise ProviderError(f"Model '{model}' was not found.") from e
            if code == 429:
                raise ProviderError("Gemini rate limit or quota reached.", retryable=True) from e
            raise ProviderError(f"Gemini rejected the request ({code}).") from e
        except errors.ServerError as e:
            raise ProviderError("Gemini server error.", retryable=True) from e

        meta = resp.usage_metadata
        cached = (getattr(meta, "cached_content_token_count", 0) or 0) if meta else 0
        usage = Usage(
            input_tokens=((meta.prompt_token_count or 0) - cached) if meta else 0,
            output_tokens=(
                (meta.candidates_token_count or 0) + (getattr(meta, "thoughts_token_count", 0) or 0)
            )
            if meta
            else 0,
            cache_read_tokens=cached,
        )
        text = resp.text or ""
        parsed = _validate(schema, text) if schema is not None else None
        return Completion(text=text, parsed=parsed, usage=usage, model=model)

    async def list_models(self) -> list[str]:
        from google.genai import errors

        client = self._client()
        try:
            out = []
            async for m in await client.aio.models.list():
                name = (m.name or "").removeprefix("models/")
                if "generateContent" in (m.supported_actions or []):
                    out.append(name)
            return sorted(out)
        except errors.ClientError as e:
            raise ProviderError("Google rejected the API key.", auth=True) from e


# ------------------------------------------------------- Claude Code (own server)
class ClaudeCodeProvider(Provider):
    """Talks to bridge/claude_code_bridge.py, which runs the unmodified `claude -p`
    on the administrator's own machine with their own Claude login. ``api_key`` is
    the bridge secret, ``base_url`` the bridge address."""

    name = "claude_code"
    MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-2"]

    def _url(self, path: str) -> str:
        if not self._base_url:
            raise ProviderError("The Claude Code bridge address is missing.")
        return self._base_url.rstrip("/") + path

    async def complete(self, model: str, prompt: Prompt, schema: type[T] | None = None) -> Completion:
        import httpx

        body: dict[str, Any] = {
            "system": prompt.system,
            "prompt": prompt.user,
            "history": prompt.history,
            "effort": prompt.effort,
            "images": [
                {"data": base64.b64encode(i.data).decode(), "media_type": i.media_type} for i in prompt.images
            ],
        }
        if model and model != "default":
            body["model"] = model
        if schema is not None:
            body["schema"] = schema.model_json_schema()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=8)) as client:
                resp = await client.post(
                    self._url("/v1/complete"), json=body, headers={"Authorization": f"Bearer {self._api_key}"}
                )
        except httpx.HTTPError as e:
            raise ProviderError("The Claude Code bridge can't be reached.", retryable=True) from e
        try:
            data = resp.json()
        except ValueError as e:
            raise ProviderError(f"The Claude Code bridge answered with HTTP {resp.status_code}.") from e
        if resp.status_code == 401 or data.get("error") == "auth_bridge":
            raise ProviderError("The bridge rejected the secret.", auth=True)
        if resp.status_code == 403:
            raise ProviderError("The bridge doesn't accept requests from this server's address.", auth=True)
        if "error" in data:
            kind = data.get("error")
            raise ProviderError(
                str(data.get("message") or "Claude Code failed.")[:200],
                retryable=kind in ("rate_limit", "overloaded", "busy", "timeout"),
                auth=kind == "auth",
            )
        u = data.get("usage") or {}
        usage = Usage(
            input_tokens=int(u.get("input_tokens") or 0),
            output_tokens=int(u.get("output_tokens") or 0),
            cache_read_tokens=int(u.get("cache_read_tokens") or 0),
            cache_write_tokens=int(u.get("cache_write_tokens") or 0),
        )
        output = data.get("output")
        parsed = None
        text = output if isinstance(output, str) else json.dumps(output)
        if schema is not None:
            try:
                parsed = (
                    schema.model_validate(output) if isinstance(output, dict) else _validate(schema, text)
                )
            except ValidationError as e:
                raise ProviderError(
                    "Claude Code returned data that does not match the expected format."
                ) from e
        return Completion(
            text=text,
            parsed=parsed,
            usage=usage,
            model=data.get("model") or model or "claude-code",
            api_equivalent_usd=data.get("api_equivalent_usd"),
        )

    async def list_models(self) -> list[str]:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(
                    self._url("/health"), headers={"Authorization": f"Bearer {self._api_key}"}
                )
        except httpx.HTTPError as e:
            raise ProviderError("The Claude Code bridge can't be reached.") from e
        if resp.status_code in (401, 403):
            raise ProviderError("The bridge rejected the secret or this server's address.", auth=True)
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if not data.get("ok"):
            raise ProviderError("Claude Code is not available on the bridge machine.")
        return list(self.MODELS)


PROVIDER_CLASSES: dict[str, type[Provider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "claude_code": ClaudeCodeProvider,
}


def make_provider(name: str, api_key: str, base_url: str | None = None) -> Provider:
    try:
        cls = PROVIDER_CLASSES[name]
    except KeyError as e:
        raise ProviderError(f"Unknown provider {name!r}") from e
    return cls(api_key, base_url)


def _short(e: Exception) -> str:
    msg = getattr(e, "message", None) or str(e)
    try:
        body = getattr(e, "body", None)
        if isinstance(body, dict):
            msg = body.get("error", {}).get("message", msg) if isinstance(body.get("error"), dict) else msg
    except Exception:  # noqa: S110
        pass
    return json.dumps(msg)[1:-1][:200]
