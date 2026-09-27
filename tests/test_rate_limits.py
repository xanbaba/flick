"""Rate limits must not cause immediate cloud retries during JSON repair."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from backend.app.services.generation import GenerationService
from backend.providers import registry
from backend.providers.llm_gemini import GeminiLLMProvider
from backend.providers.llm_static import StaticLLMProvider
from backend.providers.rate_limits import rate_limit_error
from backend.providers.registry import LLMFallbackChain
from shared.config import load_config


def test_retry_guidance_preserves_longest_delay_and_quota_identifiers() -> None:
    response = httpx.Response(
        429,
        headers={"retry-after": "60"},
        json={
            "error": {
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "55.5s"},
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {"quotaId": "RequestsPerMinute", "description": "private description"}
                        ],
                    },
                ]
            }
        },
    )
    error = rate_limit_error(response)
    assert error.retry_after_s == 60
    assert error.quota_ids == ["RequestsPerMinute"]
    assert "private" not in str(error)


def test_retry_after_http_date() -> None:
    retry_at = datetime.now(UTC) + timedelta(seconds=120)
    error = rate_limit_error(
        httpx.Response(429, headers={"retry-after": format_datetime(retry_at)})
    )
    assert error.retry_after_s is not None
    assert 118 < error.retry_after_s <= 120


@pytest.mark.parametrize("hint", ["invalid", "NaN", "Infinity", "-1"])
def test_invalid_retry_guidance_does_not_hide_rate_limit(hint: str) -> None:
    error = rate_limit_error(
        httpx.Response(429, headers={"retry-after": hint}, content=b"not JSON")
    )
    assert error.retry_after_s is None
    assert error.quota_ids == []


@pytest.mark.parametrize("retry_after", [None, "75"])
async def test_rate_limit_skips_repair_and_recovers_after_cooldown(
    monkeypatch: pytest.MonkeyPatch, retry_after: str | None
) -> None:
    clock = [100.0]
    monkeypatch.setattr(registry.time, "monotonic", lambda: clock[0])
    requests = []
    generated = ["Hello there", "Busy now", "How are you", "Come in"]

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers={"retry-after": retry_after} if retry_after else {})
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": json.dumps({"labels": generated})}]},
                    }
                ]
            },
        )

    factory = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: factory(transport=httpx.MockTransport(respond), **kwargs),
    )
    chain = LLMFallbackChain(
        [GeminiLLMProvider("test-key", "gemini-3.8-flash"), StaticLLMProvider()]
    )
    service = GenerationService(llm=chain, config=load_config().generation)
    await service.generate_intents("", "someone", "unknown", "hey")
    assert len(requests) == 1
    assert chain.health()["gemini"] is False
    assert chain.last_served_by == "static"
    clock[0] += (float(retry_after) if retry_after else registry.COOLDOWN_S) - 1
    await service.generate_intents("", "someone", "unknown", "hey")
    assert len(requests) == 1
    clock[0] += 2
    assert await service.generate_intents("", "someone", "unknown", "hey") == generated
    assert len(requests) == 2
    assert chain.health()["gemini"] is True
    assert chain.last_served_by == "gemini"
