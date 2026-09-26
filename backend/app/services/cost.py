"""Per-turn cost accounting (ARCHITECTURE.md section 20).

"cost.py accumulates tokens, characters and audio seconds per turn,
multiplies by privacy.price_table, emits privacy.cost." A disabled
person's speech device has a running per-sentence cost, and this is
the honest number.

Usage: the orchestrator opens one CostTurn per conversation turn,
records each provider call as it happens (it already knows which
provider answered and with what, via FallbackChain.last_served_by),
and finalizes it once, which returns the privacy.cost payload
(section 6.6: {turn_id, items, turn_usd, session_usd}) and folds the
turn's total into the running session total.
"""

from __future__ import annotations

from pydantic import BaseModel

from shared.config import PriceTable


class CostItem(BaseModel):
    provider: str  # "gemini" | "elevenlabs" | "deepgram" | ...
    kind: str  # "tokens_in" | "tokens_out" | "chars" | "audio_seconds"
    quantity: float
    usd: float


class TurnCost(BaseModel):
    """privacy.cost payload (section 6.6)."""

    turn_id: str
    items: list[CostItem]
    turn_usd: float
    session_usd: float


class CostTracker:
    """Session-level accumulator; hands out one CostTurn per turn."""

    def __init__(self, price_table: PriceTable) -> None:
        self._price_table = price_table
        self.session_usd = 0.0

    def start_turn(self, turn_id: str) -> CostTurn:
        return CostTurn(self, turn_id)

    def _finalize(self, turn_id: str, items: list[CostItem]) -> TurnCost:
        turn_usd = sum(item.usd for item in items)
        self.session_usd += turn_usd
        return TurnCost(
            turn_id=turn_id, items=items, turn_usd=turn_usd, session_usd=self.session_usd
        )


class CostTurn:
    """Accumulates CostItems for a single turn; call finalize() once."""

    def __init__(self, tracker: CostTracker, turn_id: str) -> None:
        self._tracker = tracker
        self._turn_id = turn_id
        self._items: list[CostItem] = []

    def record_llm_call(self, provider: str, tokens_in: int, tokens_out: int) -> None:
        if provider != "gemini":
            # Only Gemini has a priced entry in config.yaml's price_table
            # (section 5); other links -- openai_compat, do_gradient,
            # static -- are either self-hosted/BYO-billed or free.
            return
        pt = self._tracker._price_table
        self._items.append(
            CostItem(
                provider=provider,
                kind="tokens_in",
                quantity=tokens_in,
                usd=(tokens_in / 1000.0) * pt.gemini_in_per_1k,
            )
        )
        self._items.append(
            CostItem(
                provider=provider,
                kind="tokens_out",
                quantity=tokens_out,
                usd=(tokens_out / 1000.0) * pt.gemini_out_per_1k,
            )
        )

    def record_tts_call(self, provider: str, chars: int) -> None:
        if provider != "elevenlabs":
            return  # piper, browser and cache hits are free
        pt = self._tracker._price_table
        self._items.append(
            CostItem(
                provider=provider,
                kind="chars",
                quantity=chars,
                usd=(chars / 1000.0) * pt.elevenlabs_per_1k_chars,
            )
        )

    def record_stt_call(self, provider: str, audio_seconds: float) -> None:
        if provider != "deepgram":
            return  # faster_whisper (local) and manual are free
        pt = self._tracker._price_table
        self._items.append(
            CostItem(
                provider=provider,
                kind="audio_seconds",
                quantity=audio_seconds,
                usd=(audio_seconds / 60.0) * pt.deepgram_per_minute,
            )
        )

    def finalize(self) -> TurnCost:
        return self._tracker._finalize(self._turn_id, self._items)
