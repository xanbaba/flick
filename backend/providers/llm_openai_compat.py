"""OpenAI-compatible chat-completions LLM provider (ARCHITECTURE.md section 17).

Serves OpenAI, LM Studio, Ollama, and -- per section 19 -- DigitalOcean's
Gradient AI, which "slots into llm_openai_compat.py with no new code,
only three env vars." registry.py instantiates this class twice, once
per env-var prefix (OPENAI_COMPAT_* and DO_GRADIENT_*), giving each a
distinct ``name`` for health reporting and logging.
"""

from __future__ import annotations

import httpx

from backend.providers.base import LLMProvider


class OpenAICompatLLMProvider(LLMProvider):
    def __init__(self, name: str, base_url: str, model: str, api_key: str) -> None:
        if not base_url or not model:
            raise ValueError(f"{name} requires a base_url and model")
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key

    async def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        max_tokens: int = 400,
        timeout: float = 6.0,
    ) -> str:
        url = f"{self._base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        body: dict[str, object] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=body)
        response.raise_for_status()
        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError(f"{self.name} returned no choices")
        content = choices[0].get("message", {}).get("content")
        if not content:
            raise RuntimeError(f"{self.name} choice has no content")
        return content
