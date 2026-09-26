"""The last, guaranteed-offline link in the LLM fallback chain.

ARCHITECTURE.md section 5: "The last link in every chain never
touches the network." This provider never imports a network client,
never raises, never blocks longer than a function call. It has no
idea what JSON shape a caller wants -- callers are responsible for
treating a static completion as unusable and building their own
correctly-shaped placeholder locally (section 17, SW-13). That is
what lets the backend boot and serve a complete turn with an empty
``.env``.
"""

from __future__ import annotations

from .base import LLMProvider


class StaticLLMProvider(LLMProvider):
    name = "static"

    async def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        max_tokens: int = 400,
        timeout: float = 6.0,
    ) -> str:
        del system, user, max_tokens, timeout  # unused: this link is content-free
        return "{}" if json_mode else ""
