"""Bounded, attributed dialogue; independent of personal graph grounding IDs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from shared.config import ConversationConfig


class ConversationTurn(BaseModel):
    id: str = Field(min_length=1)
    partner_id: str | None
    partner_name: str
    user_name: str
    incoming_utterance: str
    chosen_intent: str
    selected_reply: str
    playback_outcome: Literal["completed", "failed", "unconfirmed"]
    learning_outcome: Literal["committed", "extraction_failed", "not_spoken"] = "committed"
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def render_recent(turns: list[ConversationTurn], config: ConversationConfig) -> str:
    """Newest complete exchanges that fit, oldest first; never lose speaker labels.

    JSON escaping prevents an utterance's newlines from forging speaker headings.
    Oversized exchanges are omitted rather than truncating facts into false claims.
    Failed/unconfirmed replies are never presented as spoken statements.
    """
    blocks: list[str] = []
    size = 0
    for turn in reversed(turns[-config.recent_exchanges :]):
        block = json.dumps(
            {
                "partner": {"id": turn.partner_id, "name": turn.partner_name},
                "partner_said": turn.incoming_utterance,
                "user": {"id": "user", "name": turn.user_name},
                "user_said": turn.selected_reply if turn.playback_outcome == "completed" else None,
                "playback_outcome": turn.playback_outcome,
            },
            ensure_ascii=False,
        )
        if size + len(block) + bool(blocks) > config.context_max_chars:
            break
        blocks.append(block)
        size += len(block) + (len(blocks) > 1)
    return "\n".join(reversed(blocks))
