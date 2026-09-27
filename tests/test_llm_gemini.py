"""Gemini requests must preserve room for the short structured response."""

from __future__ import annotations

import json

import httpx
import pytest

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
    assert await provider.complete("test instructions", "test utterance", json_mode=True) == result


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
