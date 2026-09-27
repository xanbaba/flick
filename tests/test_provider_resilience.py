"""Real HTTP adapters, deterministic elapsed time, no live requests or backoff sleeps."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest
from structlog.testing import capture_logs

from backend.providers import registry
from backend.providers.base import LLMProvider
from backend.providers.llm_gemini import GeminiLLMProvider
from backend.providers.llm_openai_compat import OpenAICompatLLMProvider
from backend.providers.llm_static import StaticLLMProvider
from backend.providers.registry import CircuitBreaker
from backend.providers.resilience import Completion, LLMStage
from shared.config import EnvSettings, load_config


class Clock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.now += delay


def stage(clock: Clock, links: list[LLMProvider]) -> LLMStage:
    return LLMStage(
        links,
        [CircuitBreaker() for _ in links],
        load_config().generation,
        "test",
        clock=lambda: clock.now,
        sleep=clock.sleep,
        jitter=lambda low, high: high,
    )


def transport(
    monkeypatch: pytest.MonkeyPatch, respond: Callable[[httpx.Request], httpx.Response]
) -> None:
    factory = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: factory(transport=httpx.MockTransport(respond), **kwargs),
    )


def gemini_response(text: str) -> httpx.Response:
    return httpx.Response(
        200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}]}
    )


async def run(stage: LLMStage) -> Completion[str]:
    return await stage.generate(
        "private-system",
        "private-prompt",
        lambda raw: raw if raw == "valid" else None,
        lambda prompt, raw: "private-repair",
        max_tokens=2048,
    )


@pytest.mark.parametrize("hint,expected_delay", [(None, 0.75), ("3", 3.0)])
async def test_transient_failure_retries_once_with_remaining_budget(
    monkeypatch: pytest.MonkeyPatch, hint: str | None, expected_delay: float
) -> None:
    clock = Clock()
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            clock.now += 4
            return httpx.Response(503, headers={"retry-after": hint} if hint else {})
        return gemini_response("valid")

    transport(monkeypatch, respond)
    result = await run(
        stage(clock, [GeminiLLMProvider("private-key", "test"), StaticLLMProvider()])
    )
    assert result.value == "valid"
    assert clock.sleeps == [expected_delay]
    assert requests[0].extensions["timeout"]["read"] == 12
    assert requests[1].extensions["timeout"]["read"] == 8 - expected_delay


@pytest.mark.parametrize("elapsed,hint", [(11.06, None), (1, "60")])
async def test_slow_503_or_long_retry_hint_does_not_start_doomed_retry(
    monkeypatch: pytest.MonkeyPatch, elapsed: float, hint: str | None
) -> None:
    clock = Clock()
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        clock.now += elapsed
        return httpx.Response(503, headers={"retry-after": hint} if hint else {})

    transport(monkeypatch, respond)
    request_stage = stage(clock, [GeminiLLMProvider("key", "test"), StaticLLMProvider()])
    result = await run(request_stage)
    assert result.value is None
    assert result.fallback_reason == "provider_unavailable"
    assert len(requests) == 1
    assert clock.sleeps == []
    assert not request_stage.breakers[0].is_healthy()


async def test_failed_retry_cools_down_gemini_then_uses_alternate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock()
    hosts = []

    def respond(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if request.url.host == "generativelanguage.googleapis.com":
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"message": {"content": "valid"}}]})

    transport(monkeypatch, respond)
    request_stage = stage(
        clock,
        [
            GeminiLLMProvider("key", "test"),
            OpenAICompatLLMProvider("alternate", "https://alternate.test", "model", "key"),
            StaticLLMProvider(),
        ],
    )
    result = await run(request_stage)
    assert hosts == ["generativelanguage.googleapis.com"] * 2 + ["alternate.test"]
    assert result.provider == "alternate"
    assert not request_stage.breakers[0].is_healthy()
    assert len(clock.sleeps) == 1


async def test_repair_stays_on_provider_that_produced_malformed_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock()
    hosts = []
    contents = []

    def respond(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if len(hosts) == 1:
            return httpx.Response(429)
        contents.append(json.loads(request.content)["messages"][1]["content"])
        clock.now += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "bad" if len(contents) == 1 else "valid"}}]},
        )

    transport(monkeypatch, respond)
    result = await run(
        stage(
            clock,
            [
                GeminiLLMProvider("key", "test"),
                OpenAICompatLLMProvider("alternate", "https://alternate.test", "model", ""),
                StaticLLMProvider(),
            ],
        )
    )
    assert result.value == "valid"
    assert hosts == ["generativelanguage.googleapis.com", "alternate.test", "alternate.test"]
    assert contents == ["private-prompt", "private-repair"]
    assert not clock.sleeps


async def test_static_fallback_never_calls_a_provider_or_json_repair() -> None:
    static = StaticLLMProvider()
    request_stage = stage(Clock(), [static])
    with capture_logs() as logs:
        result = await run(request_stage)
    assert result.value is None and result.fallback_reason == "no_provider"
    assert [entry["event"] for entry in logs] == ["llm.stage_fallback"]


async def test_deadline_is_distinct_from_external_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = asyncio.Event()

    async def stall(request: httpx.Request) -> httpx.Response:
        entered.set()
        await asyncio.Future()
        raise AssertionError("unreachable")

    transport(monkeypatch, stall)
    request_stage = stage(Clock(), [GeminiLLMProvider("private-key", "test")])
    with capture_logs() as logs:
        task = asyncio.create_task(run(request_stage))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert any(log.get("reason") == "caller_cancelled" for log in logs)
    assert request_stage.breakers[0].is_healthy()
    assert "private-" not in json.dumps(logs)

    config = load_config().generation.model_copy(update={"timeout_s": 0.01})
    request_stage = LLMStage(
        [GeminiLLMProvider("private-key", "test")], [CircuitBreaker()], config, "deadline"
    )
    with capture_logs() as logs:
        result = await run(request_stage)
    assert result.fallback_reason == "deadline_exceeded"
    assert not any(log.get("reason") == "caller_cancelled" for log in logs)
    assert "private-" not in json.dumps(logs)


@pytest.mark.parametrize("status", [500, 502, 503, 504, None])
async def test_transient_retry_budget_is_shared_across_all_configured_links(
    monkeypatch: pytest.MonkeyPatch, status: int | None
) -> None:
    clock = Clock()
    hosts: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if status is None:
            raise httpx.ConnectError("private transport diagnostic", request=request)
        return httpx.Response(status)

    transport(monkeypatch, respond)
    chain = registry._build_llm_chain(
        EnvSettings(
            _env_file=None,
            gemini_api_key="test",
            openai_compat_base_url="https://alternate.test",
            openai_compat_model="test",
            do_gradient_base_url="https://gradient.test",
            do_gradient_model="test",
        )
    )
    request_stage = stage(clock, chain._links)
    with capture_logs() as logs:
        result = await run(request_stage)
    assert result.value is None
    assert hosts == ["generativelanguage.googleapis.com"] * 2 + ["alternate.test", "gradient.test"]
    assert clock.sleeps == [0.75]
    assert "private" not in json.dumps(logs)
    assert not any(log["event"] == "llm.json_repair" for log in logs)


async def test_transient_cooldown_skips_calls_then_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock()
    calls = []
    monkeypatch.setattr(registry.time, "monotonic", lambda: clock.now)

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503) if len(calls) <= 2 else gemini_response("valid")

    transport(monkeypatch, respond)
    links = [GeminiLLMProvider("key", "test"), StaticLLMProvider()]
    breakers = [CircuitBreaker() for _ in links]

    def request_stage() -> LLMStage:
        return LLMStage(links, breakers, load_config().generation, "recovery", sleep=clock.sleep)

    assert (await run(request_stage())).value is None
    assert len(calls) == 2
    clock.now += 29
    assert (await run(request_stage())).fallback_reason == "provider_cooldown"
    assert len(calls) == 2
    clock.now += 2
    assert (await run(request_stage())).value == "valid"
    assert len(calls) == 3


async def test_malformed_output_has_one_repair_and_remaining_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock()
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        clock.now += 6
        return gemini_response("malformed")

    transport(monkeypatch, respond)
    result = await run(stage(clock, [GeminiLLMProvider("key", "test"), StaticLLMProvider()]))
    assert len(requests) == 2
    assert requests[1].extensions["timeout"]["read"] == 6
    assert result.value is None and result.fallback_reason == "deadline_exceeded"


async def test_expired_async_timeout_is_authoritative_when_clock_has_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reproduce an event-loop timer firing before the monotonic deadline."""
    calls = []

    async def stall(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        await asyncio.Future()
        raise AssertionError("unreachable")

    transport(monkeypatch, stall)
    clock = Clock()
    config = load_config().generation.model_copy(update={"timeout_s": 0.01})
    request_stage = LLMStage(
        [GeminiLLMProvider("key", "test"), StaticLLMProvider()],
        [CircuitBreaker(), CircuitBreaker()],
        config,
        "deadline",
        clock=lambda: clock.now,
        sleep=clock.sleep,
    )
    result = await run(request_stage)
    assert request_stage.remaining() > 0
    assert result.fallback_reason == "deadline_exceeded"
    assert len(calls) == 1 and not clock.sleeps
