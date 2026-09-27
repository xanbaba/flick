"""Onboarding seed (ARCHITECTURE.md section 14).

Two LLM passes build a graph from a biography: the first asks for a
balanced 40-60 nodes, the second enriches every Person and Activity.
Malformed entries are dropped by ``GraphService.seed_from_json``. When
the provider is the offline static fallback (or both passes fail), the
committed Marcus fixture is loaded instead, so a seed still completes.

After insert, nodes are streamed as bloom batches of about 10, with
``interval_s`` between batches (150 ms in production) so a dashboard
can show the graph growing. This service yields the batches; the
WebSocket broadcast lives in the orchestrator, which is out of scope
here.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from backend.app.services.graph import GraphService
from backend.app.services.persona import DEMO_BIO, DEMO_NAME
from backend.app.services.worker import MemoryWorker, run_memory
from backend.providers.base import LLMProvider
from backend.providers.registry import get_llm_provider
from shared.config import GenerationConfig, get_settings
from shared.logging import get_logger
from shared.schemas import GraphEdge, GraphNode

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
FIXTURE_PATH = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "persona_marcus.json"

logger = get_logger(__name__)


class SeedUnavailableError(RuntimeError):
    """No grounded biography could be generated; onboarding can be retried."""


BLOOM_BATCH = 10
BLOOM_INTERVAL_S = 0.15

_GENERIC_SYSTEM_PROMPT = (
    "You are the onboarding stage of Flick, a speech device for someone who "
    "cannot speak. Follow the instructions in the user message exactly. "
    "Respond with nothing but the JSON object it asks for -- no prose, no "
    "markdown fences, no commentary before or after."
)

_FIRST_PASS = (
    "This is the first pass. Produce 40 to 60 nodes with a balanced spread "
    "of Person, Place, Thing, Activity, Need and Memory. Include the people, "
    "places, objects, routines and needs the biography actually states."
)

_SECOND_PASS = (
    "This is the expansion pass. You already drafted a first graph, included "
    "below. Enrich every Person and every Activity with the related Things, "
    "Places and Memories the biography supports. The combined graph should "
    "land between 150 and 300 nodes. Do not repeat nodes that are already "
    "in the first graph. Return only the new nodes and the new edges.\n\n"
    "FIRST GRAPH:\n{first_graph}"
)


class BloomBatch(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


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


def load_fixture(path: Path = FIXTURE_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class OnboardingService:
    """ARCHITECTURE.md section 14."""

    def __init__(
        self,
        graph: GraphService,
        llm: LLMProvider | None = None,
        fixture_path: Path = FIXTURE_PATH,
        interval_s: float = BLOOM_INTERVAL_S,
        worker: MemoryWorker | None = None,
        config: GenerationConfig | None = None,
    ) -> None:
        self._graph = graph
        self._worker = worker
        self._config = config or get_settings().config.generation
        self._llm = llm or get_llm_provider()
        self._fixture_path = fixture_path
        self._interval_s = interval_s
        self._template = (PROMPTS_DIR / "onboarding_seed.txt").read_text(encoding="utf-8")

    async def seed(self, bio: str, name: str) -> AsyncIterator[BloomBatch]:
        payload = await self._payload_from_llm(bio, name)
        usable = [
            n
            for n in payload.get("nodes", [])
            if isinstance(n, dict)
            and n.get("kind") in {"Person", "Place", "Thing", "Activity", "Need", "Memory"}
            and isinstance(n.get("text") or n.get("name"), str)
            and (n.get("text") or n.get("name")).strip()
        ]
        if not usable:

            def normalize(value: str) -> str:
                return " ".join(value.split())

            if normalize(name) != normalize(DEMO_NAME) or normalize(bio) != normalize(DEMO_BIO):
                raise SeedUnavailableError(
                    "Biography generation is unavailable. Your biography was not replaced "
                    "or saved. Please try again."
                )
            payload = await run_memory(self._worker, load_fixture, self._fixture_path)
        else:
            user = next((n for n in usable if n.get("id") == "user"), {})
            payload["nodes"] = [
                {
                    "notes": user.get("notes", "")
                    if isinstance(user.get("notes", ""), str)
                    else "",
                    "id": "user",
                    "kind": "Person",
                    "name": name.strip(),
                    "relationship": "self",
                },
                *[n for n in usable if n.get("id") != "user"],
            ]
        seeded = await run_memory(self._worker, self._graph.seed_from_json, payload)
        nodes, edges = await run_memory(self._worker, self._graph.snapshot)
        by_id = {node.id: node for node in nodes}
        ordered = [by_id[node_id] for node_id in seeded.node_ids if node_id in by_id]
        emitted: set[str] = set()
        for start in range(0, len(ordered), BLOOM_BATCH):
            batch_nodes = ordered[start : start + BLOOM_BATCH]
            batch_ids = {node.id for node in batch_nodes}
            emitted.update(batch_ids)
            batch_edges = [
                edge
                for edge in edges
                if edge.source in emitted
                and edge.target in emitted
                and (edge.source in batch_ids or edge.target in batch_ids)
            ]
            yield BloomBatch(nodes=batch_nodes, edges=batch_edges)
            if start + BLOOM_BATCH < len(ordered) and self._interval_s > 0:
                await asyncio.sleep(self._interval_s)

    async def _payload_from_llm(self, bio: str, name: str) -> dict[str, Any]:
        text = f"{name}\n\n{bio}".strip()
        first_prompt = _fill(self._template, pass_instructions=_FIRST_PASS, bio=text)
        first = await self._pass(first_prompt)
        if not first or not first.get("nodes"):
            return {"nodes": [], "edges": []}
        expansion = _SECOND_PASS.replace("{first_graph}", json.dumps(first))
        second_prompt = _fill(self._template, pass_instructions=expansion, bio=text)
        second = await self._pass(second_prompt)
        return _merge(first, second or {"nodes": [], "edges": []})

    async def _pass(self, prompt: str) -> dict[str, Any] | None:
        try:
            async with asyncio.timeout(self._config.timeout_s):
                raw = await self._complete(prompt)
                parsed = self._parse(raw)
                if parsed is None:
                    parsed = self._parse(await self._complete(self._repair_prompt(prompt, raw)))
                return parsed
        except Exception as exc:
            logger.warning("onboarding.generation_failed", error_type=type(exc).__name__)
            return None

    async def _complete(self, user_prompt: str) -> str:
        return await self._llm.complete(
            _GENERIC_SYSTEM_PROMPT,
            user_prompt,
            json_mode=True,
            max_tokens=4000,
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
    def _parse(raw: str) -> dict[str, Any] | None:
        try:
            data = json.loads(_extract_json_object(raw))
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        nodes = data.get("nodes")
        edges = data.get("edges", [])
        if not isinstance(nodes, list) or not isinstance(edges, list):
            return None
        return {
            "nodes": [n for n in nodes if isinstance(n, dict)],
            "edges": [e for e in edges if isinstance(e, dict)],
        }


def _merge(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    seen = {node.get("id") for node in first.get("nodes", []) if node.get("id")}
    nodes = list(first.get("nodes", []))
    for node in second.get("nodes", []):
        node_id = node.get("id")
        if node_id and node_id in seen:
            continue
        nodes.append(node)
        if node_id:
            seen.add(node_id)
    edges = list(first.get("edges", [])) + list(second.get("edges", []))
    return {"nodes": nodes, "edges": edges}
