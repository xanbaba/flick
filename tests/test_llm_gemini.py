"""Gemini requests must preserve room for the short structured response."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from structlog.testing import capture_logs

from backend.providers.llm_gemini import GeminiLLMProvider


@pytest.mark.parametrize(
    ("model", "thinking"),
    [
        ("gemini-3.8-flash", {"thinkingLevel": "low"}),
        ("gemini-2.5-flash", {"thinkingBudget": 0}),
        ("gemini-2.0-flash", None),
    ],
)
async def test_structured_generation_uses_low_latency_thinking(
    monkeypatch: pytest.MonkeyPatch, model: str, thinking: dict[str, object] | None
) -> None:
    result = '{"labels": ["Walk together", "Stay home", "Which route", "Later today"]}'

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        config = body["generationConfig"]
        assert config.get("thinkingConfig") == thinking
        assert config["maxOutputTokens"] == 400
        assert config["responseMimeType"] == "application/json"
        assert request.headers["x-goog-api-key"] == "test-key"
        assert "key" not in request.url.params
        return httpx.Response(
            200,
            json={
                "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": result}]}}]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = GeminiLLMProvider("test-key", model)
    with capture_logs() as logs:
        assert (
            await provider.complete("test instructions", "test utterance", json_mode=True) == result
        )
    assert logs[-1]["event"] == "gemini.request_completed"
    assert logs[-1]["finish_reason"] == "STOP"
    assert logs[-1]["output_tokens"] is None
    assert logs[-1]["thinking_tokens"] is None
    assert logs[0]["request_id"] == logs[-1]["request_id"]
    assert "Walk together" not in json.dumps(logs)


async def test_truncated_output_is_a_provider_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": '{"labels": ['}]}}
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = GeminiLLMProvider("test-key", "gemini-3.8-flash")
    with pytest.raises(RuntimeError, match="MAX_TOKENS"):
        await provider.complete("test instructions", "test utterance", json_mode=True)


async def test_stage_cancellation_logs_the_inflight_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = asyncio.Event()

    async def stall(request: httpx.Request) -> httpx.Response:
        entered.set()
        await asyncio.Future()
        raise AssertionError("request should have been cancelled")

    client = httpx.AsyncClient(transport=httpx.MockTransport(stall))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = GeminiLLMProvider("private-key", "gemini-3.8-flash")
    with capture_logs() as logs:
        task = asyncio.create_task(provider.complete("private-system", "private-utterance"))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    started, cancelled = logs
    assert started["event"] == "gemini.request_started"
    assert cancelled["event"] == "gemini.request_cancelled"
    assert started["request_id"] == cancelled["request_id"]
    assert cancelled["elapsed_s"] >= 0
    assert "private-" not in json.dumps(logs)


async def test_rate_limit_logs_status_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(429)))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = GeminiLLMProvider("private-key", "gemini-3.8-flash")
    with capture_logs() as logs, pytest.raises(httpx.HTTPStatusError):
        await provider.complete("private-system", "private-utterance")
    failure = logs[-1]
    assert failure["event"] == "gemini.request_failed"
    assert failure["http_status"] == 429
    assert failure["error_type"] == "HTTPStatusError"
    assert "private-" not in json.dumps(logs)
