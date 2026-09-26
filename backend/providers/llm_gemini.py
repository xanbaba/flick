"""Gemini LLM provider (ARCHITECTURE.md section 17, SW-6).

Calls the Gemini REST API directly via httpx rather than pulling in
the full google-generativeai SDK -- one extra dependency avoided for
a single POST request. Raises on any failure (timeout, HTTP error,
missing candidate) so registry.FallbackChain's circuit breaker can
detect it and move to the next link; see base.LLMProvider's docstring.
"""

from __future__ import annotations

import httpx

from backend.app.services.cost import outbound
from backend.providers.base import LLMProvider

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


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
        if json_mode:
            generation_config["responseMimeType"] = "application/json"

        body = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": generation_config,
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, params={"key": self._api_key}, json=body)
        response.raise_for_status()
        payload = response.json()
        candidates = payload.get("candidates") or []
        if not candidates:
            raise RuntimeError("gemini returned no candidates")
        parts = candidates[0].get("content", {}).get("parts") or []
        if not parts:
            raise RuntimeError("gemini candidate has no content parts")
        return "".join(part.get("text", "") for part in parts)
