"""Mini test suite for Langfuse tracing: the local-only host guard, and that a broken/absent
Langfuse client never breaks or changes the result of a traced call. No network access or a
real Langfuse server is used -- get_langfuse/traced_span are exercised directly or monkeypatched.
"""

import pytest

from src.clients.langfuse import _is_local, get_langfuse, traced_span


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("http://localhost:3000", True),
        ("http://127.0.0.1:3000", True),
        ("https://cloud.langfuse.com", False),
        ("https://my-langfuse.example.com", False),
        ("", False),
    ],
)
def test_is_local_rejects_any_non_loopback_host(host: str, expected: bool) -> None:
    assert _is_local(host) == expected


def test_get_langfuse_disabled_for_a_cloud_host(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSettings:
        langfuse_host = "https://cloud.langfuse.com"
        langfuse_public_key = "pk-test"
        langfuse_secret_key = "sk-test"

    get_langfuse.cache_clear()
    monkeypatch.setattr("src.clients.langfuse.get_settings", lambda: FakeSettings())

    assert get_langfuse() is None
    get_langfuse.cache_clear()


def test_traced_span_is_a_no_op_without_a_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.clients.langfuse.get_langfuse", lambda: None)

    with traced_span("test-stage", metadata={"detail": "x"}) as span:
        span.update(output={"ok": True})  # must not raise


def test_traced_span_swallows_a_broken_client_and_still_yields(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenClient:
        def start_as_current_observation(self, **kwargs: object) -> None:
            raise ConnectionError("langfuse unreachable (simulated)")

    monkeypatch.setattr("src.clients.langfuse.get_langfuse", lambda: BrokenClient())

    with traced_span("test-stage") as span:
        span.update(output={"ok": True})  # must not raise
