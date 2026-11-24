from __future__ import annotations

import logging
import re

import structlog

from app.core.config import get_settings

_SECRETS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"bot\d{6,}:[A-Za-z0-9_-]{20,}"), "bot[redacted]"),  # Telegram bot tokens in URLs
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}"), "[redacted]"),
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "[redacted]"),
    (re.compile(r"AIza[0-9A-Za-z_-]{20,}"), "[redacted]"),
    (
        re.compile(
            r"(?i)\b(authorization|x-api-key|api[_-]?key|password|token)(['\"]?\s*[:=]\s*['\"]?)[^\s'\",}]+"
        ),
        r"\1\2[redacted]",
    ),
]


def redact(text: str) -> str:
    for pattern, repl in _SECRETS:
        text = pattern.sub(repl, text)
    return text


def _redact_processor(_logger, _name, event_dict):
    for k, v in list(event_dict.items()):
        if isinstance(v, str):
            event_dict[k] = redact(v)
    return event_dict


class _RedactFilter(logging.Filter):
    """Redacts the fully formatted message, so %-style arguments keep their types."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except (TypeError, ValueError):
            return True
        record.msg, record.args = redact(message), None
        return True


def setup_logging() -> None:
    level = getattr(logging, get_settings().log_level.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(message)s")
    root = logging.getLogger()
    for h in root.handlers:
        h.addFilter(_RedactFilter())
    # httpx logs full request URLs at INFO; Telegram URLs contain the bot token.
    for noisy in ("httpx", "httpcore", "anthropic", "openai", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # arq installs its own handler; don't print every job line twice.
    logging.getLogger("arq").propagate = False
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
    )
