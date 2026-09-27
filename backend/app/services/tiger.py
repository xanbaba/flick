"""Authoritative async PostgreSQL/pgvector memory (ARCHITECTURE.md section 8).

Kuzu remains an import source, never a fallback. All embedding work precedes
transactions. SQL parameters carry data; labels never become SQL identifiers.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import ssl
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import asyncpg
import numpy as np

from backend.app.services.conversation import ConversationTurn
from backend.app.services.graph import (
    NODE_COLUMN_TYPES,
    NODE_TEXT_COLUMN,
    REL_HAS_STRENGTH,
    REL_PAIRS,
    EdgeRef,
    NodeRef,
    Person,
    SeedResult,
    _fact_for,
    _label_for,
)
from backend.providers.base import EmbeddingProvider
from shared.config import DatabaseConfig, ReinforcementConfig
from shared.schemas import GraphEdge, GraphNode

NODE_SELECT = "SELECT *, embedding::text AS vector FROM flick.nodes"


class MemoryUnavailableError(RuntimeError):
    """Safe to expose; never includes credentials or SQL parameter values."""


def connection_options(dsn: str) -> dict[str, Any]:
    """Direct PostgreSQL TLS requires ALPN, which asyncpg does not set itself."""
    query = parse_qs(urlsplit(dsn).query)
    if query.get("sslnegotiation") != ["direct"]:
        return {}
    cafile = query.get("sslrootcert", [None])[-1]
    context = ssl.create_default_context(cafile=cafile)
    context.set_alpn_protocols(["postgresql"])
    return {"ssl": context, "direct_tls": True}


@asynccontextmanager
async def database_lease(pool: Any, *, transaction: bool = False) -> AsyncIterator[Any]:
    """Discard timed-out connections before pool cleanup can wait on cancellation."""
    async with pool.acquire() as conn:
        tx = conn.transaction() if transaction else None
        try:
            if tx is not None:
                await tx.start()
            yield conn
            if tx is not None:
                await tx.commit()
        except (TimeoutError, asyncio.CancelledError):
            conn.terminate()
            raise
        except BaseException:
            if tx is not None:
                try:
                    await tx.rollback()
                except BaseException:
                    conn.terminate()
                    raise
            raise


def vector_literal(vector: Any, dim: int = 384) -> str:
    values = np.asarray(vector, dtype=np.float64)
    if values.shape != (dim,) or not np.isfinite(values).all():
        raise ValueError("Embedding must have 384 finite dimensions")
    if not np.any(values):
        raise ValueError("Zero embeddings cannot establish similarity")
    return json.dumps(values.tolist(), allow_nan=False)


def prepare_node(kind: str, props: dict[str, Any], vector: Any) -> dict[str, Any]:
    if kind not in NODE_COLUMN_TYPES:
        raise ValueError("Unknown node kind")
    content = props.get(NODE_TEXT_COLUMN[kind])
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Node content must not be blank")
    for key, sql_type in NODE_COLUMN_TYPES[kind].items():
        value = props.get(key)
        if value is None:
            continue
        if sql_type == "STRING[]":
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ValueError("Invalid node attribute")
        elif not isinstance(value, str):
            raise ValueError("Invalid node attribute")
    weight = float(props.get("weight", 1.0))
    if not math.isfinite(weight):
        raise ValueError("Node weight must be finite")
    node_id = props.get("id") or f"{kind.lower()}_{uuid.uuid4().hex}"
    if not isinstance(node_id, str) or not node_id.strip():
        raise ValueError("Invalid node ID")
    attributes = {
        k: v
        for k, v in props.items()
        if k not in {"id", "kind", "weight", "embedding", "created_at", "last_accessed"}
    }
    return {
        "id": node_id,
        "kind": kind,
        "content": content.strip(),
        "attributes": json.dumps(attributes, allow_nan=False),
        "vector": vector_literal(vector),
        "weight": weight,
        "created_at": _timestamp(props.get("created_at")),
        "last_accessed": _timestamp(props.get("last_accessed")),
    }


def _timestamp(value: datetime | None) -> datetime | None:
    if value is not None and not isinstance(value, datetime):
        raise ValueError("Invalid timestamp")
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


class TigerGraphService:
    embedding_dim = 384

    def __init__(
        self,
        dsn: str,
        profile_id: str,
        embedder: EmbeddingProvider,
        database: DatabaseConfig,
        reinforcement: ReinforcementConfig,
        *,
        destination: str = "tiger",
    ) -> None:
        self._dsn = dsn
        self.profile_id = profile_id
        self._embedder = embedder
        self.database = database
        self.reinforcement = reinforcement
        self.destination = destination
        self.available = False
        self.error: str | None = "Memory storage has not connected"
        self._pool: asyncpg.Pool | None = None
        self._connection: ContextVar[Any] = ContextVar(
            f"memory_connection_{id(self)}", default=None
        )
        self._space: tuple[str, str, int] | None = None
        self._uncertain = False

    async def open(self) -> None:
        if not self._dsn:
            self.error = "Configure TIGER_DSN (or explicit development LOCAL_PG_DSN)"
            raise MemoryUnavailableError(self.error)
        try:
            self._pool = await asyncpg.create_pool(
                self._dsn,
                min_size=1,
                max_size=self.database.memory_pool_max,
                timeout=self.database.connect_timeout_s,
                command_timeout=self.database.query_timeout_s,
                **await asyncio.to_thread(connection_options, self._dsn),
            )
            await self.ensure_schema()
            # Resolves the provider once, outside SQL and the event loop.
            await asyncio.to_thread(self._embedder.embed, ["embedding space initialization"])
            backend = getattr(self._embedder, "backend_name", self._embedder.name)
            model = getattr(self._embedder, "model_name", self._embedder.name)
            self._space = (backend, model, self._embedder.dim)
            if self._embedder.dim != self.embedding_dim:
                raise ValueError("Memory requires 384-dimensional embeddings")
            profile = await self.profile()
            if profile is not None:
                self._check_space(profile)
            self.available, self.error = True, None
        except Exception as exc:
            self.available = False
            self.error = (
                str(exc)
                if isinstance(exc, MemoryUnavailableError)
                else "Memory connection or embedding space unavailable"
            )
            await self.close()
            raise MemoryUnavailableError(self.error) from exc

    def _check_space(self, profile: Any) -> None:
        actual = (
            profile["embedding_backend"],
            profile["embedding_model"],
            profile["embedding_dim"],
        )
        if actual != self._space:
            raise MemoryUnavailableError(
                "Stored embedding space differs; explicit re-import required"
            )

    async def ensure_schema(self) -> None:
        assert self._pool is not None
        path = Path(__file__).resolve().parents[3] / "migrations" / "002_memory.sql"
        sql = await asyncio.to_thread(path.read_text, encoding="utf-8")
        checksum = hashlib.sha256(sql.encode()).hexdigest()
        async with asyncio.timeout(self.database.migration_timeout_s):
            async with database_lease(self._pool, transaction=True) as conn:
                # One migration runner at a time across backend processes.
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtext('flick.memory.migrations'))",
                    timeout=self.database.migration_timeout_s,
                )
                await conn.execute(
                    "CREATE SCHEMA IF NOT EXISTS flick; CREATE TABLE IF NOT EXISTS "
                    "flick.schema_migrations (version text PRIMARY KEY, checksum text NOT NULL)",
                    timeout=self.database.migration_timeout_s,
                )
                old = await conn.fetchval(
                    "SELECT checksum FROM flick.schema_migrations WHERE version='002_memory'"
                )
                if old is not None and old != checksum:
                    raise ValueError("Applied migration checksum changed")
                if old is None:
                    await conn.execute(sql, timeout=self.database.migration_timeout_s)
                    await conn.execute(
                        "INSERT INTO flick.schema_migrations VALUES ('002_memory', $1)", checksum
                    )
                if self.destination == "tiger":
                    present = await conn.fetchval(
                        "SELECT EXISTS (SELECT 1 FROM pg_available_extensions "
                        "WHERE name='timescaledb')"
                    )
                    if not present:
                        raise ValueError("Tiger destination must provide TimescaleDB")

    async def _fetch(self, sql: str, *args: Any) -> list[Any]:
        if self._pool is None:
            raise MemoryUnavailableError(self.error or "Memory unavailable")
        try:
            conn = self._connection.get()
            if conn is not None:
                return await conn.fetch(sql, *args)
            async with asyncio.timeout(self.database.query_timeout_s):
                async with database_lease(self._pool) as conn:
                    rows = await conn.fetch(sql, *args)
            if not self._uncertain:
                self.available, self.error = True, None
            return rows
        except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, TimeoutError) as exc:
            self.available, self.error = False, "Memory read unavailable"
            raise MemoryUnavailableError(self.error) from exc

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        if self._connection.get() is not None:
            raise RuntimeError("Nested memory transactions are not supported")
        if self._pool is None or self._uncertain:
            raise MemoryUnavailableError(self.error or "Reconcile memory before writing")
        try:
            async with asyncio.timeout(self.database.write_timeout_s):
                async with database_lease(self._pool, transaction=True) as conn:
                    token = self._connection.set(conn)
                    try:
                        await conn.execute(
                            "SELECT pg_advisory_xact_lock(hashtext($1))", "flick:" + self.profile_id
                        )
                        yield
                    finally:
                        self._connection.reset(token)
            self.available, self.error = True, None
        except (
            OSError,
            TimeoutError,
            asyncpg.PostgresConnectionError,
            asyncpg.InterfaceError,
            asyncio.CancelledError,
        ):
            self._uncertain = True
            self.available, self.error = False, "Memory commit uncertain; reconciliation required"
            raise

    async def reconcile(self) -> None:
        """Wait for any old writer, then read canonical state before allowing writes."""
        if self._pool is None:
            raise MemoryUnavailableError(self.error or "Memory unavailable")
        async with asyncio.timeout(self.database.write_timeout_s):
            async with database_lease(self._pool, transaction=True) as conn:
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtext($1))", "flick:" + self.profile_id
                )
                await conn.fetch("SELECT id FROM flick.nodes WHERE profile_id=$1", self.profile_id)
                await conn.fetch(
                    "SELECT id FROM flick.conversation_turns WHERE profile_id=$1 "
                    "ORDER BY completed_at DESC, id DESC LIMIT 1",
                    self.profile_id,
                )
        self._uncertain = False
        self.available, self.error = True, None

    async def profile(self) -> Any | None:
        rows = await self._fetch("SELECT * FROM flick.profiles WHERE id=$1", self.profile_id)
        return rows[0] if rows else None

    async def embed(self, texts: list[str]) -> np.ndarray:
        result = await asyncio.to_thread(self._embedder.embed, texts)
        for row in result:
            vector_literal(row)
        return result

    async def prepare_nodes(
        self, payload: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], int]:
        accepted, dropped = [], 0
        seen: set[str] = set()
        for props in payload:
            try:
                kind = props.get("kind")
                content = props.get(NODE_TEXT_COLUMN.get(kind, ""))
                # Validate attributes before invoking the embedding provider.
                prepare_node(kind, props, np.ones(self.embedding_dim))
                vector = (await self.embed([content]))[0]
                node = prepare_node(kind, props, vector)
                if node["id"] in seen:
                    dropped += 1
                    continue
                seen.add(node["id"])
                accepted.append(node)
            except (ValueError, TypeError, AttributeError):
                dropped += 1
        return accepted, dropped

    async def _put_node(self, node: dict[str, Any]) -> str:
        await self._put_nodes([node])
        return node["id"]

    async def _put_nodes(self, nodes: list[dict[str, Any]]) -> None:
        conn = self._connection.get()
        if conn is None:
            raise RuntimeError("Node writes require a transaction")
        if not nodes:
            return
        rows = await conn.fetch(
            "SELECT id,kind FROM flick.nodes WHERE profile_id=$1 AND id=ANY($2::text[]) FOR UPDATE",
            self.profile_id,
            [n["id"] for n in nodes],
        )
        old_kinds = {r["id"]: r["kind"] for r in rows}
        for node in nodes:
            if node["id"] in old_kinds and old_kinds[node["id"]] != node["kind"]:
                raise ValueError("A stable node ID cannot change kind")
            if node["id"] == "user":
                profile = await conn.fetchrow(
                    "SELECT display_name FROM flick.profiles WHERE id=$1", self.profile_id
                )
                if (
                    node["kind"] != "Person"
                    or profile is None
                    or node["content"] != profile["display_name"]
                    or json.loads(node["attributes"]).get("relationship") != "self"
                ):
                    raise ValueError("Self Person must agree with the profile")
        await conn.executemany(
            "INSERT INTO flick.nodes(profile_id,id,kind,content,attributes,embedding,weight,"
            "created_at,last_accessed) VALUES ($1,$2,$3,$4,$5::jsonb,$6::text::vector,$7,"
            "COALESCE($8,now()),COALESCE($9,now())) ON CONFLICT(profile_id,id) DO UPDATE SET "
            "content=EXCLUDED.content,attributes=EXCLUDED.attributes,embedding=EXCLUDED.embedding,"
            "weight=EXCLUDED.weight,last_accessed=EXCLUDED.last_accessed "
            "WHERE flick.nodes.kind=EXCLUDED.kind",
            [
                (
                    self.profile_id,
                    n["id"],
                    n["kind"],
                    n["content"],
                    n["attributes"],
                    n["vector"],
                    n["weight"],
                    n["created_at"],
                    n["last_accessed"],
                )
                for n in nodes
            ],
        )

    async def upsert_node(self, kind: str, props: dict[str, Any]) -> str:
        if self._connection.get() is not None:
            raise RuntimeError("Prepare embeddings before the write transaction")
        vector = (await self.embed([props.get(NODE_TEXT_COLUMN.get(kind, ""), "")]))[0]
        node = prepare_node(kind, props, vector)
        async with self.transaction():
            return await self._put_node(node)

    async def upsert_edge(self, kind: str, src: str, dst: str, props: dict[str, Any]) -> str:
        conn = self._connection.get()
        if conn is None:
            async with self.transaction():
                return await self.upsert_edge(kind, src, dst, props)
        ids, _ = await self._put_edges([{**props, "kind": kind, "source": src, "target": dst}])
        return ids[0]

    async def _put_edges(
        self, edges: list[dict[str, Any]], *, skip_invalid: bool = False
    ) -> tuple[list[str], int]:
        conn = self._connection.get()
        if conn is None:
            raise RuntimeError("Edge writes require a transaction")
        if not edges:
            return [], 0
        endpoints = await conn.fetch(
            "SELECT id,kind FROM flick.nodes WHERE profile_id=$1 AND id=ANY($2::text[]) FOR SHARE",
            self.profile_id,
            list(
                {
                    e.get(key)
                    for e in edges
                    if isinstance(e, dict)
                    for key in ("source", "target")
                    if isinstance(e.get(key), str)
                }
            ),
        )
        kinds = {row["id"]: row["kind"] for row in endpoints}
        args, ids, dropped = [], [], 0
        seen: set[tuple[str, str, str]] = set()
        for props in edges:
            try:
                kind, src, dst = props["kind"], props["source"], props["target"]
                if (kinds.get(src), kinds.get(dst)) not in REL_PAIRS.get(kind, ()):
                    raise ValueError("Invalid relationship endpoints")
                weight = float(props.get("weight", 1.0))
                count = props.get("count", 1)
                strength = float(props.get("strength", 0.5)) if kind in REL_HAS_STRENGTH else None
                if (
                    not math.isfinite(weight)
                    or not isinstance(count, int)
                    or isinstance(count, bool)
                    or count < 0
                    or (strength is not None and not 0 <= strength <= 1)
                ):
                    raise ValueError("Invalid relationship attributes")
                key = (kind, src, dst)
                if key in seen:
                    raise ValueError("Duplicate relationship in one update")
                seen.add(key)
                edge_id = props.get("id") or f"{kind}:{src}->{dst}"
                if not isinstance(edge_id, str) or not edge_id.strip():
                    raise ValueError("Invalid edge ID")
                args.append(
                    (
                        self.profile_id,
                        edge_id,
                        kind,
                        src,
                        dst,
                        weight,
                        count,
                        strength,
                        _timestamp(props.get("last_reinforced")),
                    )
                )
                ids.append(edge_id)
            except (ValueError, KeyError, TypeError):
                if not skip_invalid:
                    raise
                dropped += 1
        await conn.executemany(
            "INSERT INTO flick.edges(profile_id,id,kind,source,target,weight,count,strength,"
            "last_reinforced) VALUES($1,$2,$3,$4,$5,$6,$7,$8,COALESCE($9,now())) "
            "ON CONFLICT(profile_id,kind,source,target) DO UPDATE SET weight=EXCLUDED.weight,"
            "count=flick.edges.count+EXCLUDED.count,strength=EXCLUDED.strength,"
            "last_reinforced=EXCLUDED.last_reinforced",
            args,
        )
        return ids, dropped

    async def seed_from_json(self, payload: dict[str, Any]) -> SeedResult:
        user = next((n for n in payload.get("nodes", []) if n.get("id") == "user"), {})
        return await self.seed_profile(payload, user.get("name", ""), "")

    async def seed_profile(
        self, payload: dict[str, Any], name: str, biography: str, *, strict: bool = False
    ) -> SeedResult:
        if not name.strip() or self._space is None:
            raise ValueError("A named profile and initialized embedding space are required")
        nodes, dropped = await self.prepare_nodes(payload.get("nodes", []))
        if strict and dropped:
            raise ValueError("Import contains invalid or duplicate nodes")
        user = next((n for n in nodes if n["id"] == "user"), None)
        if (
            user is None
            or user["kind"] != "Person"
            or user["content"] != name.strip()
            or json.loads(user["attributes"]).get("relationship") != "self"
        ):
            raise ValueError("Profile requires its matching self Person")
        # Resolve unique display-name references emitted by onboarding providers.
        aliases: dict[str, list[str]] = {}
        for node in nodes:
            aliases.setdefault(node["content"], []).append(node["id"])
        ids = {n["id"] for n in nodes}
        edges = []
        for original in payload.get("edges", []):
            if not isinstance(original, dict):
                if strict:
                    raise ValueError("Invalid imported edge")
                dropped += 1
                continue
            edge = dict(original)
            for key in ("source", "target"):
                ref = edge.get(key)
                if isinstance(ref, str) and ref not in ids and len(aliases.get(ref, [])) == 1:
                    edge[key] = aliases[ref][0]
            edges.append(edge)
        async with self.transaction():
            conn = self._connection.get()
            await conn.execute(
                "INSERT INTO flick.profiles(id,display_name,biography,embedding_backend,"
                "embedding_model,embedding_dim) VALUES($1,$2,$3,$4,$5,$6)",
                self.profile_id,
                name.strip(),
                biography,
                *self._space,
            )
            await self._put_nodes(nodes)
            edge_ids, edge_dropped = await self._put_edges(edges, skip_invalid=not strict)
            dropped += edge_dropped
            if strict:
                await self._verify_import(nodes, edges)
        return SeedResult(
            node_count=len(nodes),
            edge_count=len(edge_ids),
            node_ids=[n["id"] for n in nodes],
            dropped=dropped,
        )

    async def _verify_import(
        self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
    ) -> None:
        """Compare identities, facts, attributes, weights/counts before commit."""
        rows = await self._fetch(NODE_SELECT + " WHERE profile_id=$1", self.profile_id)
        stored = {r["id"]: r for r in rows}
        if len(stored) != len(nodes):
            raise ValueError("Imported node count differs")
        for node in nodes:
            row = stored.get(node["id"])
            if row is None or any(row[key] != node[key] for key in ("kind", "content", "weight")):
                raise ValueError("Imported node identity or weight differs")
            if json.loads(row["attributes"]) != json.loads(node["attributes"]):
                raise ValueError("Imported facts or attributes differ")
        rows = await self._fetch("SELECT * FROM flick.edges WHERE profile_id=$1", self.profile_id)
        stored = {r["id"]: r for r in rows}
        if len(stored) != len(edges):
            raise ValueError("Imported edge count differs")
        for edge in edges:
            edge_id = edge.get("id") or f"{edge['kind']}:{edge['source']}->{edge['target']}"
            row = stored.get(edge_id)
            if row is None or any(row[k] != edge[k] for k in ("kind", "source", "target")):
                raise ValueError("Imported relationship identity differs")
            if row["weight"] != edge.get("weight", 1.0) or row["count"] != edge.get("count", 1):
                raise ValueError("Imported relationship weight or count differs")
            if edge["kind"] in REL_HAS_STRENGTH and row["strength"] != edge.get("strength", 0.5):
                raise ValueError("Imported relationship strength differs")

    @staticmethod
    def _node(row: Any) -> NodeRef:
        props = json.loads(row["attributes"])
        return NodeRef(
            id=row["id"],
            kind=row["kind"],
            name=_label_for(props),
            weight=row["weight"],
            embedding=json.loads(row["vector"]),
            fact=_fact_for(row["kind"], props),
            source_subject=props.get("source_subject"),
            source_role=props.get("source_role"),
        )

    async def node_count(self) -> int:
        rows = await self._fetch(
            "SELECT count(*) AS n FROM flick.nodes WHERE profile_id=$1", self.profile_id
        )
        return rows[0]["n"]

    async def people(self) -> list[Person]:
        rows = await self._fetch(
            NODE_SELECT + " WHERE profile_id=$1 AND kind='Person' ORDER BY id", self.profile_id
        )
        result = []
        for row in rows:
            props = json.loads(row["attributes"])
            result.append(
                Person(
                    id=row["id"],
                    name=row["content"],
                    weight=row["weight"],
                    relationship=props.get("relationship") or "",
                    address_terms=props.get("address_terms") or [],
                    notes=props.get("notes") or "",
                )
            )
        return result

    async def snapshot(self) -> tuple[list[GraphNode], list[GraphEdge]]:
        rows = await self._fetch(NODE_SELECT + " WHERE profile_id=$1 ORDER BY id", self.profile_id)
        nodes = [
            GraphNode(
                id=r["id"],
                kind=r["kind"],
                label=_label_for(json.loads(r["attributes"])),
                weight=r["weight"],
                last_accessed=r["last_accessed"].timestamp(),
            )
            for r in rows
        ]
        edges = await self.edges_among([n.id for n in nodes])
        return nodes, [GraphEdge(**e.model_dump()) for e in edges]

    async def get_node(self, node_id: str) -> NodeRef | None:
        rows = await self._fetch(
            NODE_SELECT + " WHERE profile_id=$1 AND id=$2", self.profile_id, node_id
        )
        return self._node(rows[0]) if rows else None

    async def edges_among(self, ids: list[str]) -> list[EdgeRef]:
        rows = await self._fetch(
            "SELECT id,kind,source,target,weight FROM flick.edges WHERE profile_id=$1 "
            "AND source=ANY($2::text[]) AND target=ANY($2::text[]) ORDER BY id",
            self.profile_id,
            ids,
        )
        return [EdgeRef(**dict(r)) for r in rows]

    async def get_embeddings(self, ids: list[str]) -> dict[str, np.ndarray]:
        rows = await self._fetch(
            NODE_SELECT + " WHERE profile_id=$1 AND id=ANY($2::text[])", self.profile_id, ids
        )
        return {r["id"]: np.asarray(json.loads(r["vector"])) for r in rows}

    async def vector_search(self, vector: Any, k: int, *, kind: str | None = None) -> list[NodeRef]:
        if k <= 0:
            return []
        rows = await self._fetch(
            NODE_SELECT + " WHERE profile_id=$1 AND ($4::text IS NULL OR kind=$4) "
            "ORDER BY embedding <=> $2::text::vector, id LIMIT $3",
            self.profile_id,
            vector_literal(vector),
            k,
            kind,
        )
        return [self._node(r) for r in rows]

    async def expand(self, seeds: list[NodeRef], hops: int, cap: int) -> list[NodeRef]:
        if cap <= 0:
            return []
        # Bound every frontier, not only the final result. Stable ties by ID.
        seen = {n.id: n for n in sorted(seeds, key=lambda n: (-n.weight, n.id))[:cap]}
        frontier = list(seen)
        for _ in range(hops):
            if not frontier or len(seen) >= cap:
                break
            rows = await self._fetch(
                NODE_SELECT + " WHERE profile_id=$1 AND NOT(id=ANY($3::text[])) AND id IN ("
                "SELECT CASE WHEN source=ANY($2::text[]) THEN target ELSE source END "
                "FROM flick.edges WHERE profile_id=$1 AND "
                "(source=ANY($2::text[]) OR target=ANY($2::text[]))) "
                "ORDER BY weight DESC,id LIMIT $4",
                self.profile_id,
                frontier,
                list(seen),
                cap - len(seen),
            )
            frontier = [r["id"] for r in rows]
            seen.update({r["id"]: self._node(r) for r in rows})
        return sorted(seen.values(), key=lambda n: (-n.weight, n.id))

    async def reinforce(self, node_ids: list[str], edge_ids: list[str], **overrides: float) -> None:
        conn = self._connection.get()
        if conn is None:
            async with self.transaction():
                await self.reinforce(node_ids, edge_ids, **overrides)
            return
        config = self.reinforcement.model_copy(update=overrides)
        for table, ids, increment, timestamp in (
            ("nodes", node_ids, config.node_increment, "last_accessed"),
            ("edges", edge_ids, config.edge_increment, "last_reinforced"),
        ):
            await conn.execute(
                f"UPDATE flick.{table} SET weight=LEAST(weight+$3,$4),{timestamp}=now() "
                "WHERE profile_id=$1 AND id=ANY($2::text[])",
                self.profile_id,
                list(set(ids)),
                increment,
                config.max_weight,
            )

    async def recent_turns(self, partner_id: str | None, limit: int) -> list[ConversationTurn]:
        rows = await self._fetch(
            "SELECT * FROM flick.conversation_turns WHERE profile_id=$1 "
            "AND partner_id IS NOT DISTINCT FROM $2::text "
            "ORDER BY completed_at DESC,id DESC LIMIT $3",
            self.profile_id,
            partner_id,
            limit,
        )
        return [ConversationTurn.model_validate(dict(r)) for r in reversed(rows)]

    async def commit_learning(
        self,
        turn: ConversationTurn,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        node_ids: list[str],
        edge_ids: list[str],
    ) -> bool:
        """A repeated stable turn ID returns without applying any increments again."""
        async with self.transaction():
            conn = self._connection.get()
            existing = await conn.fetchrow(
                "SELECT * FROM flick.conversation_turns WHERE profile_id=$1 AND id=$2",
                self.profile_id,
                turn.id,
            )
            if existing is not None:
                original = ConversationTurn.model_validate(dict(existing))
                if original.model_dump(exclude={"completed_at"}) != turn.model_dump(
                    exclude={"completed_at"}
                ):
                    raise ValueError("Turn ID reused with different content")
                return False
            await self._put_nodes(nodes)
            await self._put_edges(edges)
            await self.reinforce(node_ids, edge_ids)
            await conn.execute(
                "INSERT INTO flick.conversation_turns(profile_id,id,partner_id,partner_name,"
                "user_name,incoming_utterance,chosen_intent,selected_reply,playback_outcome,"
                "learning_outcome,completed_at) "
                "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
                self.profile_id,
                turn.id,
                turn.partner_id,
                turn.partner_name,
                turn.user_name,
                turn.incoming_utterance,
                turn.chosen_intent,
                turn.selected_reply,
                turn.playback_outcome,
                turn.learning_outcome,
                turn.completed_at,
            )
        return True

    async def close(self) -> None:
        if self._pool is not None:
            try:
                async with asyncio.timeout(self.database.connect_timeout_s):
                    await self._pool.close()
            finally:
                self._pool.terminate()
                self._pool = None
