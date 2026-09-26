"""The privacy.flow decorator records a successful outbound call."""

from __future__ import annotations

from backend.app.services.cost import clear_flows, flows, outbound


async def test_outbound_records_only_a_successful_call() -> None:
    clear_flows()

    class Provider:
        @outbound("llm", "Gemini (Google)", "intent labels")
        async def complete(self, text: str) -> str:
            return "ok"

    assert await Provider().complete("hello") == "ok"
    assert flows() == [
        {
            "stage": "llm",
            "destination": "Gemini (Google)",
            "bytes": 5,
            "description": "intent labels",
        }
    ]
