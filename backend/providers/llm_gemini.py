"""Gemini LLM provider (ARCHITECTURE.md section 17, SW-6).

Calls the Gemini REST API directly via httpx rather than pulling in
the full google-generativeai SDK -- one extra dependency avoided for
a single POST request. Raises on any failure (timeout, HTTP error,
missing candidate) so registry.FallbackChain's circuit breaker can
detect it and move to the next link; see base.LLMProvider's docstring.
"""

from __future__ import annotations

import asyncio
import time
import uuid

import httpx

from backend.app.services.cost import outbound
from backend.providers.base import LLMProvider
from backend.providers.rate_limits import rate_limit_error
from shared.logging import get_logger

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
logger = get_logger(__name__)


class GeminiLLMProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise ValueError("gemini requires an API key")
        self._api_key = api_key
        self._model = model or "gemini-2.5-flash"

    @outbound("llm", "Gemini (Google)", "intent labels, sentences, fact extraction")
    async def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        max_tokens: int = 400,
        timeout: float = 6.0,
    ) -> str:
        url = f"{_API_BASE}/{self._model}:generateContent"
        generation_config: dict[str, object] = {"maxOutputTokens": max_tokens}
        # Short, latency-sensitive replies must leave room for visible JSON.
        # Gemini's default thinking consumes the same output-token allowance.
        if self._model.startswith("gemini-3"):
            generation_config["thinkingConfig"] = {"thinkingLevel": "low"}
        elif self._model.startswith("gemini-2.5-flash"):
            generation_config["thinkingConfig"] = {"thinkingBudget": 0}
        if json_mode:
            generation_config["responseMimeType"] = "application/json"

        body = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": generation_config,
        }

        request_id = uuid.uuid4().hex
        started = time.monotonic()
        request_log = logger.bind(request_id=request_id, model=self._model)
        request_log.info("gemini.request_started", max_tokens=max_tokens, timeout_s=timeout)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    url, headers={"x-goog-api-key": self._api_key}, json=body
                )
            response.raise_for_status()
        except asyncio.CancelledError:
            request_log.warning("gemini.request_cancelled", elapsed_s=time.monotonic() - started)
            raise
        except httpx.HTTPError as exc:
            failed_response = getattr(exc, "response", None)
            if failed_response is not None and failed_response.status_code == 429:
                limited = rate_limit_error(failed_response)
                request_log.warning(
                    "gemini.rate_limited",
                    elapsed_s=time.monotonic() - started,
                    http_status=429,
                    retry_after_s=limited.retry_after_s,
                    quota_ids=limited.quota_ids,
                )
                raise limited from exc
            request_log.warning(
                "gemini.request_failed",
                elapsed_s=time.monotonic() - started,
                error_type=type(exc).__name__,
                http_status=failed_response.status_code if failed_response is not None else None,
            )
            raise
        payload = response.json()
        candidates = payload.get("candidates") or []
        usage = payload.get("usageMetadata") or {}
        request_log.info(
            "gemini.request_completed",
            elapsed_s=time.monotonic() - started,
            finish_reason=candidates[0].get("finishReason") if candidates else None,
            output_tokens=usage.get("candidatesTokenCount"),
            thinking_tokens=usage.get("thoughtsTokenCount"),
        )
        if not candidates:
            raise RuntimeError("gemini returned no candidates")
        if candidates[0].get("finishReason") == "MAX_TOKENS":
            raise RuntimeError("gemini response truncated (MAX_TOKENS)")
        parts = candidates[0].get("content", {}).get("parts") or []
        if not parts:
            raise RuntimeError("gemini candidate has no content parts")
        return "".join(part.get("text", "") for part in parts)
