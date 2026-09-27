"""One deadline and retry budget for a complete LLM stage, including JSON repair."""

from __future__ import annotations

import asyncio
import random
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

import httpx

from backend.providers.base import LLMProvider
from backend.providers.rate_limits import RateLimitError, provider_error_code, rate_limit_error
from shared.config import GenerationConfig
from shared.logging import get_logger

logger = get_logger(__name__)
T = TypeVar("T")


class Breaker(Protocol):
    def is_healthy(self) -> bool: ...
    def record_success(self) -> None: ...
    def record_failure(self) -> None: ...
    def record_rate_limit(self, retry_after_s: float | None) -> None: ...


@dataclass(frozen=True)
class Completion(Generic[T]):
    value: T | None
    provider: str | None
    fallback_reason: str | None = None


class LLMStage:
    def __init__(
        self,
        links: list[LLMProvider],
        breakers: list[Breaker],
        config: GenerationConfig,
        stage: str,
        *,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
        served: Callable[[str], None] | None = None,
    ) -> None:
        self.links = links
        self.breakers = breakers
        self.config = config
        self.clock = clock or time.monotonic
        self.sleep = sleep
        self.jitter = jitter
        self.started = self.clock()
        self.deadline = self.started + config.timeout_s
        self.retries = config.transient_retries
        self.reason = "no_provider"
        self.served = served
        self._attempts = 0
        self._json_mode = True
        self.log = logger.bind(stage=stage, stage_id=uuid.uuid4().hex)

    def remaining(self) -> float:
        return max(0.0, self.deadline - self.clock())

    async def generate(
        self,
        system: str,
        prompt: str,
        parse: Callable[[str], T | None],
        repair: Callable[[str, str], str],
        *,
        max_tokens: int,
        json_mode: bool = True,
    ) -> Completion[T]:
        self._json_mode = json_mode
        repaired = False
        for link, breaker in zip(self.links, self.breakers, strict=True):
            if self.reason == "deadline_exceeded":
                break
            if link.name == "static":
                if self.served:
                    self.served(link.name)
                break
            if not breaker.is_healthy():
                if self.reason == "no_provider":
                    self.reason = "provider_cooldown"
                continue
            raw = await self._attempt(link, breaker, system, prompt, max_tokens)
            if raw is None:
                continue
            value = parse(raw)
            if value is None and not repaired:
                repaired = True
                self.log.info("llm.json_repair", provider=link.name, remaining_s=self.remaining())
                raw = await self._attempt(link, breaker, system, repair(prompt, raw), max_tokens)
                value = parse(raw) if raw is not None else None
            if value is not None:
                if self.served:
                    self.served(link.name)
                self.log.info(
                    "llm.stage_completed", provider=link.name, elapsed_s=self.clock() - self.started
                )
                return Completion(value, link.name)
            if raw is not None:
                self.reason = "malformed_response"
        if not self.remaining():
            self.reason = "deadline_exceeded"
        self.log.warning(
            "llm.stage_fallback", reason=self.reason, elapsed_s=self.clock() - self.started
        )
        return Completion(None, None, self.reason)

    async def _attempt(
        self, link: LLMProvider, breaker: Breaker, system: str, prompt: str, max_tokens: int
    ) -> str | None:
        attempt = 0
        while True:
            remaining = self.remaining()
            if not remaining or (self._attempts and remaining < self.config.min_attempt_budget_s):
                self.reason = "insufficient_budget"
                return None
            attempt += 1
            self._attempts += 1
            self.log.info(
                "llm.attempt_started", provider=link.name, attempt=attempt, remaining_s=remaining
            )
            timeout_scope = asyncio.timeout(remaining)
            try:
                async with timeout_scope:
                    raw = await link.complete(
                        system,
                        prompt,
                        json_mode=self._json_mode,
                        max_tokens=max_tokens,
                        timeout=remaining,
                    )
            except asyncio.CancelledError:
                self.log.info(
                    "llm.attempt_cancelled", provider=link.name, reason="caller_cancelled"
                )
                raise
            except Exception as exc:
                response = exc.response if isinstance(exc, httpx.HTTPStatusError) else None
                status = response.status_code if response is not None else None
                hint = rate_limit_error(response).retry_after_s if response is not None else None
                if isinstance(exc, RateLimitError) or status == 429:
                    limited = exc if isinstance(exc, RateLimitError) else rate_limit_error(response)
                    hint = limited.retry_after_s
                    breaker.record_rate_limit(hint)
                    self.reason = (
                        "daily_quota_exhausted" if limited.daily_quota_exhausted else "rate_limited"
                    )
                    self.log.warning(
                        "llm.provider_cooldown",
                        provider=link.name,
                        http_status=429,
                        retry_after_s=hint,
                        quota_ids=limited.quota_ids,
                        reason=self.reason,
                    )
                    return None
                transient = status in {500, 502, 503, 504} or isinstance(
                    exc, (httpx.TransportError, TimeoutError)
                )
                self.reason = "provider_unavailable" if transient else "provider_error"
                if timeout_scope.expired():
                    # Event-loop clock resolution can fire a timer slightly early.
                    # Its expiry is authoritative even if remaining() is positive.
                    self.reason = "deadline_exceeded"
                self.log.warning(
                    "llm.attempt_failed",
                    provider=link.name,
                    attempt=attempt,
                    http_status=status,
                    provider_code=provider_error_code(response),
                    error_type=type(exc).__name__,
                    remaining_s=self.remaining(),
                )
                if transient:
                    delay = max(
                        hint or 0.0,
                        self.config.retry_delay_s + self.jitter(0, self.config.retry_jitter_s),
                    )
                    if (
                        not timeout_scope.expired()
                        and self.retries
                        and self.remaining() - delay >= self.config.min_attempt_budget_s
                    ):
                        self.retries -= 1
                        self.log.info(
                            "llm.retry_scheduled",
                            provider=link.name,
                            delay_s=delay,
                            remaining_s=self.remaining(),
                        )
                        await self.sleep(delay)
                        if self.remaining() >= self.config.min_attempt_budget_s:
                            continue
                    breaker.record_rate_limit(hint)
                    self.log.warning(
                        "llm.provider_cooldown",
                        provider=link.name,
                        http_status=status,
                        retry_after_s=hint,
                    )
                else:
                    breaker.record_failure()
                return None
            breaker.record_success()
            return raw


def stage_for(provider: LLMProvider, config: GenerationConfig, stage: str) -> LLMStage:
    # Import here to keep the registry's provider construction independent of services.
    from backend.providers.registry import CircuitBreaker, LLMFallbackChain

    if isinstance(provider, LLMFallbackChain):
        return provider.new_stage(config, stage)
    return LLMStage([provider], [CircuitBreaker()], config, stage)
