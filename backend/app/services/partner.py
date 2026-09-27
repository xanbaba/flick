"""Partner identification (ARCHITECTURE.md section 12.3).

The transcript plus known Person nodes go to the LLM, which returns
``{"partner_id", "confidence", "reason"}``. Below 0.6 the previous
partner is kept. A manual override always wins and persists until it
is changed.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from pydantic import BaseModel

from backend.app.services.graph import GraphService
from backend.app.services.worker import MemoryWorker, run_memory
from backend.providers.base import LLMProvider
from backend.providers.registry import get_llm_provider
from shared.config import GenerationConfig, get_settings
from shared.logging import get_logger

logger = get_logger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

# Section 12.3 states this threshold in prose. It is not a config.yaml
# key, and that file is frozen for this pass.
CONFIDENCE_FLOOR = 0.6

_GENERIC_SYSTEM_PROMPT = (
    "You are the partner-identification stage of Flick, a speech device for "
    "someone who cannot speak. Follow the instructions in the user message "
    "exactly. Respond with nothing but the JSON object it asks for -- no "
    "prose, no markdown fences, no commentary before or after."
)


class PartnerIdentification(BaseModel):
    partner_id: str | None
    confidence: float
    reason: str
    overridden: bool = False


def _fill(template: str, **values: str) -> str:
    text = template
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def _extract_json_object(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        newline = text.find("\n")
        if newline != -1 and not text[:newline].strip().startswith("{"):
            text = text[newline + 1 :]
    return text.strip()


class PartnerService:
    """ARCHITECTURE.md section 12.3."""

    def __init__(
        self,
        graph: GraphService,
        llm: LLMProvider | None = None,
        *,
        worker: MemoryWorker | None = None,
        config: GenerationConfig | None = None,
    ) -> None:
        self._graph = graph
        self._worker = worker
        self._config = config or get_settings().config.generation
        self._llm = llm or get_llm_provider()
        self._template = (PROMPTS_DIR / "partner_id.txt").read_text(encoding="utf-8")
        self._current: PartnerIdentification | None = None
        self._override_id: str | None = None

    @property
    def current(self) -> PartnerIdentification | None:
        return self._current

    def set_override(self, partner_id: str | None) -> PartnerIdentification:
        """Manual override always wins until changed (section 12.3).

        ``None`` clears the override and leaves the last identified
        partner in place.
        """
        if partner_id is not None and partner_id not in {
            person.id for person in self._graph.people() if person.id != "user"
        }:
            raise ValueError("Partner must be a known person other than the user")
        self._override_id = partner_id
        if partner_id is None:
            if self._current is not None and self._current.overridden:
                self._current = None
            return self._current or PartnerIdentification(
                partner_id=None, confidence=0.0, reason="no partner identified", overridden=False
            )
        identified = PartnerIdentification(
            partner_id=partner_id,
            confidence=1.0,
            reason="manual override",
            overridden=True,
        )
        self._current = identified
        return identified

    async def identify(self, transcript: str) -> PartnerIdentification:
        if self._override_id is not None:
            assert self._current is not None
            return self._current

        people = await run_memory(self._worker, self._people_block)
        prompt = _fill(self._template, people=people, transcript=transcript)
        try:
            async with asyncio.timeout(self._config.timeout_s):
                raw = await self._complete(prompt)
                parsed = self._parse(raw)
                if parsed is None:
                    parsed = self._parse(await self._complete(self._repair_prompt(prompt, raw)))
        except Exception as exc:
            logger.warning("partner.identification_failed", error_type=type(exc).__name__)
            return self._keep_previous("partner identification unavailable")
        if parsed is None:
            return self._keep_previous("partner identification unavailable")

        if parsed.confidence < CONFIDENCE_FLOOR or parsed.partner_id in {None, "", "unknown"}:
            return self._keep_previous(parsed.reason or "confidence below 0.6")

        known = {
            person.id
            for person in await run_memory(self._worker, self._graph.people)
            if person.id != "user"
        }
        if parsed.partner_id not in known:
            return self._keep_previous("proposed partner is not a known person")

        self._current = parsed
        return parsed

    def _keep_previous(self, reason: str) -> PartnerIdentification:
        if self._current is not None:
            return self._current
        return PartnerIdentification(
            partner_id=None, confidence=0.0, reason=reason, overridden=False
        )

    def _people_block(self) -> str:
        people = self._graph.people()
        if not people:
            return "(nobody recorded yet)"
        lines = []
        for person in people:
            if person.id == "user":
                continue
            terms = ", ".join(person.address_terms) if person.address_terms else "none"
            lines.append(
                f"- {person.id}: {person.name}, {person.relationship}, address terms: {terms}"
            )
        return "\n".join(lines) if lines else "(nobody recorded yet)"

    async def _complete(self, user_prompt: str) -> str:
        return await self._llm.complete(
            _GENERIC_SYSTEM_PROMPT,
            user_prompt,
            json_mode=True,
            max_tokens=self._config.max_tokens,
            timeout=self._config.timeout_s,
        )

    @staticmethod
    def _repair_prompt(original_prompt: str, bad_response: str) -> str:
        return (
            "Your previous response was not valid JSON in the exact shape "
            "requested. Here is what you returned:\n\n"
            f"{bad_response}\n\n"
            "Re-read the instructions below and respond again with ONLY the "
            "JSON object, nothing else.\n\n"
            f"{original_prompt}"
        )

    @staticmethod
    def _parse(raw: str) -> PartnerIdentification | None:
        try:
            data = json.loads(_extract_json_object(raw))
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        partner_id = data.get("partner_id")
        confidence = data.get("confidence")
        reason = data.get("reason", "")
        if partner_id is not None and not isinstance(partner_id, str):
            return None
        if not isinstance(confidence, int | float):
            return None
        if not isinstance(reason, str):
            return None
        return PartnerIdentification(
            partner_id=partner_id or None,
            confidence=float(confidence),
            reason=reason,
            overridden=False,
        )
