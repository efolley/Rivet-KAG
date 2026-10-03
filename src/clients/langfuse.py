"""Local-only Langfuse tracing. Deliberately never talks to Langfuse Cloud: the Langfuse SDK
defaults to https://cloud.langfuse.com when no host is given, so `LANGFUSE_HOST` is checked
explicitly and tracing is disabled outright unless it's a loopback address -- not just left to a
developer's .env being correct. Best-effort like the other platform clients (Postgres/Redis/
Kafka, see src/clients/kafka.py): tracing must never be the reason a chat request fails, slows
down, or behaves differently, so `traced_span` degrades to a no-op rather than raising.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Literal
from urllib.parse import urlparse

from langfuse import Langfuse

from src.config import get_settings

log = logging.getLogger(__name__)

_LOCAL_HOSTNAMES = {"localhost", "127.0.0.1"}


def _is_local(host: str) -> bool:
    return urlparse(host).hostname in _LOCAL_HOSTNAMES


@lru_cache
def get_langfuse() -> Langfuse | None:
    settings = get_settings()
    if not settings.langfuse_host or not _is_local(settings.langfuse_host):
        log.info(
            "Langfuse tracing disabled: LANGFUSE_HOST (%r) is unset or not a local address",
            settings.langfuse_host,
        )
        return None
    try:
        return Langfuse(
            host=settings.langfuse_host,
            public_key=settings.langfuse_public_key or None,
            secret_key=settings.langfuse_secret_key or None,
        )
    except Exception:
        log.warning("Could not initialize the local Langfuse client; tracing disabled", exc_info=True)
        return None


class _NullSpan:
    """Stand-in for a Langfuse span when tracing is disabled/unreachable, so call sites never
    need an `if tracing_enabled` branch."""

    def update(self, **kwargs: Any) -> None:
        return None


@contextmanager
def traced_span(name: str, as_type: Literal["span", "chain"] = "span", **kwargs: Any) -> Iterator[Any]:
    client = get_langfuse()
    cm = None
    if client is not None:
        try:
            cm = client.start_as_current_observation(name=name, as_type=as_type, **kwargs)
        except Exception:
            log.warning("Could not start Langfuse span %r; continuing without tracing", name, exc_info=True)
    if cm is None:
        yield _NullSpan()
        return
    with cm as span:
        yield span
