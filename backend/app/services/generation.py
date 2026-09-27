"""Generation (ARCHITECTURE.md section 12: intent labels and candidates).

Every call goes through ``LLMProvider.complete(system, user, json_mode=...)``
(section 12's opening line) with a timeout and one retry on malformed
JSON using a repair prompt; a second failure falls to a locally-built,
correctly-shaped placeholder rather than raising (SW-13). The prompt
text for 12.1 and 12.2 is copied verbatim from the architecture doc
into backend/prompts/intent_labels.txt and candidates.txt; the JSON
examples in those files use literal ``{...}`` braces, so substitution
here is plain ``str.replace`` per placeholder rather than
``str.format`` (which would choke on the literal braces).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from backend.providers.base import LLMProvider
from backend.providers.registry import get_llm_provider
from backend.providers.resilience import stage_for
from shared.config import GenerationConfig, get_settings

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

_GENERIC_SYSTEM_PROMPT = (
    "You are the generation stage of Flick, a speech device for someone who "
    "cannot speak. Follow the instructions in the user message exactly. "
    "Respond with nothing but the JSON object it asks for -- no prose, no "
    "markdown fences, no commentary before or after."
)

# Fallback intent labels satisfy section 12.1's own range rule (one
# affirmative, one negative/deflecting, one that asks something back)
# while the dashboard explicitly marks them as fallback choices.
_FALLBACK_INTENTS: tuple[str, str, str, str] = ("Yes", "Not now", "Tell me more", "Ask me")


class IntentResult(BaseModel):
    labels: list[str]
    source: Literal["generated", "fallback"] = "generated"
    fallback_reason: str | None = None


class CandidateResult(BaseModel):
    """Section 12.2. Not part of shared/schemas.py -- this is what the

    orchestrator (out of scope here) would fold into a ``conv.candidates``
    WS payload alongside a ``trial_id`` it owns.
    """

    candidates: list[str]
    grounding: list[str]
    source: Literal["generated", "fallback"] = "generated"
    fallback_reason: str | None = None


def _load_prompt(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8")


def _fill(template: str, **values: str) -> str:
    text = template
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def _extract_json_object(raw: str) -> str:
    """Best-effort strip of markdown fences a provider ignored the system

    prompt and added anyway. Cheap and safe: if there is no fence, this
    is a no-op.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        newline = text.find("\n")
        if newline != -1 and not text[:newline].strip().startswith("{"):
            text = text[newline + 1 :]
    return text.strip()


class GenerationService:
    """ARCHITECTURE.md section 12."""

    def __init__(
        self,
        llm: LLMProvider | None = None,
        config: GenerationConfig | None = None,
        prompts_dir: Path = PROMPTS_DIR,
    ) -> None:
        self._llm = llm or get_llm_provider()
        self._config = config or get_settings().config.generation
        self._intent_template = (prompts_dir / "intent_labels.txt").read_text(encoding="utf-8")
        self._candidates_template = (prompts_dir / "candidates.txt").read_text(encoding="utf-8")

    # ---------------------------------------------------------------- #
    # 12.1 Intent labels
    # ---------------------------------------------------------------- #

    async def generate_intents(
        self,
        context: str,
        partner_name: str,
        partner_relationship: str,
        utterance: str,
    ) -> list[str]:
        result = await self.generate_intent_result(
            context, partner_name, partner_relationship, utterance
        )
        return result.labels

    async def generate_intent_result(
        self, context: str, partner_name: str, partner_relationship: str, utterance: str
    ) -> IntentResult:
        prompt = _fill(
            self._intent_template,
            context=context,
            partner_name=partner_name,
            partner_relationship=partner_relationship,
            utterance=utterance,
        )
        result = await stage_for(self._llm, self._config, "intents").generate(
            _GENERIC_SYSTEM_PROMPT,
            prompt,
            self._parse_intents,
            self._repair_prompt,
            max_tokens=self._config.max_tokens,
        )
        if result.value is not None:
            return IntentResult(labels=result.value)
        return IntentResult(
            labels=list(_FALLBACK_INTENTS[: self._config.n_intents]),
            source="fallback",
            fallback_reason=result.fallback_reason,
        )

    def _parse_intents(self, raw: str) -> list[str] | None:
        try:
            data = json.loads(_extract_json_object(raw))
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        labels = data.get("labels")
        if not isinstance(labels, list) or len(labels) != self._config.n_intents:
            return None
        cleaned: list[str] = []
        for label in labels:
            if not isinstance(label, str):
                return None
            text = label.strip()
            if not text or len(text.split()) > 3:
                return None
            cleaned.append(text)
        return cleaned

    # ---------------------------------------------------------------- #
    # 12.2 Candidate sentences
    # ---------------------------------------------------------------- #

    async def generate_candidates(
        self,
        user_name: str,
        context: str,
        context_node_ids: list[str],
        partner_name: str,
        partner_relationship: str,
        utterance: str,
        intent: str,
    ) -> CandidateResult:
        facts = [
            line.strip()[2:].strip()
            for line in context.splitlines()
            if line.strip().startswith("- ") and line.strip()[2:].strip()
        ]
        identified_context = "\n".join(
            f"- [{node_id}] {fact}" for node_id, fact in zip(context_node_ids, facts, strict=False)
        )
        prompt = _fill(
            self._candidates_template,
            user_name=user_name,
            context=identified_context or context,
            partner_name=partner_name,
            partner_relationship=partner_relationship,
            utterance=utterance,
            intent=intent,
        )
        valid_ids = set(context_node_ids)

        result = await stage_for(self._llm, self._config, "candidates").generate(
            _GENERIC_SYSTEM_PROMPT,
            prompt,
            lambda raw: self._parse_candidates(raw, valid_ids),
            self._repair_prompt,
            max_tokens=self._config.max_tokens,
        )
        if result.value is not None:
            return result.value
        return CandidateResult(
            candidates=[intent],
            grounding=[],
            source="fallback",
            fallback_reason=result.fallback_reason,
        )

    def _parse_candidates(self, raw: str, valid_ids: set[str]) -> CandidateResult | None:
        try:
            data = json.loads(_extract_json_object(raw))
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or len(candidates) != self._config.n_candidates:
            return None
        cleaned: list[str] = []
        for candidate in candidates:
            if not isinstance(candidate, str) or not candidate.strip():
                return None
            cleaned.append(candidate.strip())

        raw_grounding = data.get("grounding", [])
        if not isinstance(raw_grounding, list):
            raw_grounding = []
        # "Ids not present in the supplied facts are dropped silently
        # rather than failing the turn" (section 12.2).
        grounding = [g for g in raw_grounding if isinstance(g, str) and g in valid_ids]

        return CandidateResult(candidates=cleaned, grounding=grounding)

    # ---------------------------------------------------------------- #
    # Shared plumbing
    # ---------------------------------------------------------------- #

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
