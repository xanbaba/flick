"""Kuzu-backed knowledge graph service (ARCHITECTURE.md section 10).

Schema (10.1): six node tables (Person, Place, Thing, Activity, Need,
Memory) sharing ``id``, ``embedding DOUBLE[384]``, ``weight``,
``created_at``, ``last_accessed``; eight rel tables, several of them
"relationship groups" spanning more than one FROM/TO pair.

Operations (10.2): ``vector_search`` reads every ``(id, kind, embedding)``
into a cached numpy matrix on first call, invalidated on any write.
At 150-300 nodes this is a sub-millisecond dot product; a vector index
would be pure overhead, per the task brief and section 10.2's own
note. ``expand`` is breadth-first Cypher over an untyped, undirected,
variable-length path.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import kuzu
import numpy as np
from pydantic import BaseModel

from backend.providers.base import EmbeddingProvider
from backend.providers.registry import get_embedding_provider
from shared.config import get_settings
from shared.schemas import GraphEdge, GraphNode

# --------------------------------------------------------------------------
# Schema tables (section 10.1)
# --------------------------------------------------------------------------

NODE_KINDS: tuple[str, ...] = ("Person", "Place", "Thing", "Activity", "Need", "Memory")

# Column name -> Kuzu type, per node table, excluding the shared
# id/embedding/weight/created_at/last_accessed columns every table has.
NODE_COLUMN_TYPES: dict[str, dict[str, str]] = {
    "Person": {
        "name": "STRING",
        "relationship": "STRING",
        "address_terms": "STRING[]",
        "notes": "STRING",
    },
    "Place": {"name": "STRING", "notes": "STRING"},
    "Thing": {"name": "STRING", "category": "STRING", "notes": "STRING"},
    "Activity": {"name": "STRING", "time_of_day": "STRING", "notes": "STRING"},
    "Need": {"name": "STRING", "urgency": "STRING", "notes": "STRING"},
    "Memory": {"text": "STRING", "occurred_on": "STRING", "source": "STRING"},
}

# The column that holds the node's display text -- everything except
# Memory uses "name"; Memory uses "text" (section 6.7's label rule).
NODE_TEXT_COLUMN: dict[str, str] = {
    kind: ("text" if kind == "Memory" else "name") for kind in NODE_KINDS
}

REL_KINDS: tuple[str, ...] = (
    "KNOWS",
    "LIKES",
    "DISLIKES",
    "NEEDS",
    "LOCATED_AT",
    "DOES",
    "INVOLVES",
    "RELATES_TO",
)

# Each rel table may be a "relationship group" spanning several
# FROM/TO node-table pairs.
REL_PAIRS: dict[str, tuple[tuple[str, str], ...]] = {
    "KNOWS": (("Person", "Person"),),
    "LIKES": (
        ("Person", "Thing"),
        ("Person", "Activity"),
        ("Person", "Place"),
        ("Person", "Person"),
    ),
    "DISLIKES": (("Person", "Thing"), ("Person", "Activity"), ("Person", "Place")),
    "NEEDS": (("Person", "Need"), ("Person", "Thing")),
    "LOCATED_AT": (("Thing", "Place"), ("Activity", "Place"), ("Person", "Place")),
    "DOES": (("Person", "Activity"),),
    "INVOLVES": (
        ("Memory", "Person"),
        ("Memory", "Place"),
        ("Memory", "Thing"),
        ("Memory", "Activity"),
    ),
    "RELATES_TO": (
        ("Thing", "Thing"),
        ("Activity", "Activity"),
        ("Thing", "Activity"),
        ("Need", "Thing"),
    ),
}

# LIKES and DISLIKES additionally carry a "strength" column (0..1);
# every rel table has weight, count, last_reinforced.
REL_HAS_STRENGTH: frozenset[str] = frozenset({"LIKES", "DISLIKES"})


def _node_labels() -> tuple[str, ...]:
    return NODE_KINDS


# --------------------------------------------------------------------------
# Local service types. These are not part of the frozen wire contract
# (shared/schemas.py section 6); they never cross a process boundary
# on their own, so defining them here does not require the section 4
# contract-change process.
# --------------------------------------------------------------------------


class NodeRef(BaseModel):
    id: str
    kind: str
    name: str
    weight: float
    embedding: list[float] | None = None
    fact: str = ""  # the natural-language sentence retrieval.py renders as context


class EdgeRef(BaseModel):
    id: str
    kind: str
    source: str
    target: str
    weight: float


class SeedResult(BaseModel):
    node_count: int
    edge_count: int
    node_ids: list[str]
    dropped: int  # malformed entries dropped rather than failing the seed


class Person(BaseModel):
    id: str
    name: str
    relationship: str
    address_terms: list[str]
    notes: str
    weight: float


def _label_for(props: dict[str, Any]) -> str:
    """section 6.7's label derivation rule."""
    name = props.get("name")
    if name:
        return str(name)
    text = props.get("text") or ""
    return str(text)[:60]


def _fact_for(kind: str, props: dict[str, Any]) -> str:
    """The full-length fact retrieval.py renders one-per-line as context.

    Memory nodes carry their fact in ``text`` (untruncated, unlike the
    60-char display label); every other kind carries it in ``notes``
    when present, falling back to the display name.
    """
    if kind == "Memory":
        return str(props.get("text") or "")
    notes = str(props.get("notes") or "")
    if kind == "Person":
        relationship = props.get("relationship")
        terms = props.get("address_terms") or []
        if relationship and relationship != "self":
            notes += f" {props.get('name', '')} is your {relationship}."
        if terms:
            notes += f" You call {props.get('name', '')} {', '.join(terms)}."
    if notes.strip():
        return notes.strip()
    return str(props.get("name") or "")


class GraphService:
    """ARCHITECTURE.md section 10.2."""

    def __init__(
        self,
        db_path: str | Path,
        embedding_dim: int = 384,
        embedder: EmbeddingProvider | None = None,
    ) -> None:
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = kuzu.Database(self._db_path)
        self._conn = kuzu.Connection(self._db)
        self._embedding_dim = embedding_dim
        self._embedder = embedder or get_embedding_provider()
        self._vector_cache: dict[str, Any] | None = None
        self.ensure_schema()

    # ---------------------------------------------------------------- #
    # Schema
    # ---------------------------------------------------------------- #

    def ensure_schema(self) -> None:
        """Idempotent: safe to call on every process start."""
        for kind in NODE_KINDS:
            col_defs = ", ".join(
                f"{col} {sql_type}" for col, sql_type in NODE_COLUMN_TYPES[kind].items()
            )
            ddl = (
                f"CREATE NODE TABLE {kind}("
                f"id STRING, {col_defs}, "
                f"embedding DOUBLE[{self._embedding_dim}], weight DOUBLE, "
                f"created_at TIMESTAMP, last_accessed TIMESTAMP, "
                f"PRIMARY KEY (id))"
            )
            self._create_if_absent(ddl)

        for kind in REL_KINDS:
            pair_defs = ", ".join(f"FROM {a} TO {b}" for a, b in REL_PAIRS[kind])
            strength_col = ", strength DOUBLE" if kind in REL_HAS_STRENGTH else ""
            ddl = (
                f"CREATE REL TABLE {kind}("
                f"{pair_defs}, weight DOUBLE, count INT64{strength_col}, "
                f"last_reinforced TIMESTAMP)"
            )
            self._create_if_absent(ddl)

    def _create_if_absent(self, ddl: str) -> None:
        try:
            self._conn.execute(ddl)
        except RuntimeError as exc:
            if "already exists" not in str(exc):
                raise

    # ---------------------------------------------------------------- #
    # Writes
    # ---------------------------------------------------------------- #

    def _embed_one(self, text: str) -> np.ndarray:
        if not text:
            return np.zeros(self._embedding_dim, dtype=np.float64)
        return self._embedder.embed([text])[0]

    def upsert_node(self, kind: str, props: dict[str, Any]) -> str:
        if kind not in NODE_COLUMN_TYPES:
            raise ValueError(f"unknown node kind: {kind!r}")

        node_id = str(props.get("id") or f"{kind.lower()}_{uuid.uuid4().hex[:12]}")
        text_column = NODE_TEXT_COLUMN[kind]
        text_source = str(props.get(text_column) or props.get("name") or "")
        embedding = self._embed_one(text_source)
        weight = float(props.get("weight", 1.0))
        now = datetime.now(UTC)

        params: dict[str, Any] = {
            "id": node_id,
            "embedding": embedding.tolist(),
            "weight": weight,
            "now": now,
            "last_accessed": props.get("last_accessed", now),
        }
        create_set = ["n.created_at = $now"]
        match_set: list[str] = []
        for col, sql_type in NODE_COLUMN_TYPES[kind].items():
            default: Any = [] if sql_type == "STRING[]" else ""
            params[col] = props.get(col, default)
            create_set.append(f"n.{col} = ${col}")
            match_set.append(f"n.{col} = ${col}")
        create_set += [
            "n.embedding = $embedding",
            "n.weight = $weight",
            "n.last_accessed = $last_accessed",
        ]
        match_set += [
            "n.embedding = $embedding",
            "n.weight = $weight",
            "n.last_accessed = $last_accessed",
        ]

        query = (
            f"MERGE (n:{kind} {{id: $id}}) "
            f"ON CREATE SET {', '.join(create_set)} "
            f"ON MATCH SET {', '.join(match_set)}"
        )
        self._conn.execute(query, params)
        self._vector_cache = None
        return node_id

    def upsert_edge(self, kind: str, src: str, dst: str, props: dict[str, Any]) -> str:
        if kind not in REL_PAIRS:
            raise ValueError(f"unknown edge kind: {kind!r}")

        src_kind = self._label_of(src)
        dst_kind = self._label_of(dst)
        if src_kind is None or dst_kind is None:
            raise ValueError(f"upsert_edge: unknown node id(s) {src!r} -> {dst!r}")
        if (src_kind, dst_kind) not in REL_PAIRS[kind]:
            raise ValueError(f"{kind} does not connect {src_kind} -> {dst_kind}")

        now = datetime.now(UTC)
        weight = float(props.get("weight", 1.0))
        count_increment = int(props.get("count", 1))
        params: dict[str, Any] = {
            "src": src,
            "dst": dst,
            "weight": weight,
            "count": count_increment,
            "now": now,
        }
        extra_create = ""
        extra_match = ""
        if kind in REL_HAS_STRENGTH:
            params["strength"] = float(props.get("strength", 0.5))
            extra_create = ", r.strength = $strength"
            extra_match = ", r.strength = $strength"

        query = (
            f"MATCH (a:{src_kind} {{id: $src}}), (b:{dst_kind} {{id: $dst}}) "
            f"MERGE (a)-[r:{kind}]->(b) "
            f"ON CREATE SET r.weight = $weight, r.count = $count, "
            f"r.last_reinforced = $now{extra_create} "
            f"ON MATCH SET r.weight = $weight, r.count = r.count + $count, "
            f"r.last_reinforced = $now{extra_match}"
        )
        self._conn.execute(query, params)
        return f"{kind}:{src}->{dst}"

    def reinforce(
        self,
        node_ids: list[str],
        edge_ids: list[str],
        *,
        node_increment: float | None = None,
        edge_increment: float | None = None,
        max_weight: float | None = None,
    ) -> None:
        """ARCHITECTURE.md section 10.2 / ``reinforcement`` config block.

        Bumps node and edge weight on use, capped at ``max_weight``.
        Increments default to ``config.yaml``'s ``reinforcement`` block
        (AGENTS.md non-negotiable 7: no hardcoded constants outside
        config); callers may override for testing.
        """
        if node_increment is None or edge_increment is None or max_weight is None:
            reinforcement = get_settings().config.reinforcement
            node_increment = (
                node_increment if node_increment is not None else reinforcement.node_increment
            )
            edge_increment = (
                edge_increment if edge_increment is not None else reinforcement.edge_increment
            )
            max_weight = max_weight if max_weight is not None else reinforcement.max_weight

        now = datetime.now(UTC)
        for node_id in node_ids:
            kind = self._label_of(node_id)
            if kind is None:
                continue
            self._conn.execute(
                f"MATCH (n:{kind} {{id: $id}}) "
                "SET n.weight = CASE WHEN n.weight + $inc > $cap THEN $cap "
                "ELSE n.weight + $inc END, n.last_accessed = $now",
                {"id": node_id, "inc": node_increment, "cap": max_weight, "now": now},
            )
        for edge_id in edge_ids:
            parsed = self._parse_edge_id(edge_id)
            if parsed is None:
                continue
            kind, src, dst = parsed
            src_kind = self._label_of(src)
            dst_kind = self._label_of(dst)
            if src_kind is None or dst_kind is None:
                continue
            self._conn.execute(
                f"MATCH (a:{src_kind} {{id: $src}})-[r:{kind}]->(b:{dst_kind} {{id: $dst}}) "
                "SET r.weight = CASE WHEN r.weight + $inc > $cap THEN $cap "
                "ELSE r.weight + $inc END, r.last_reinforced = $now",
                {"src": src, "dst": dst, "inc": edge_increment, "cap": max_weight, "now": now},
            )
        self._vector_cache = None

    @staticmethod
    def _parse_edge_id(edge_id: str) -> tuple[str, str, str] | None:
        if ":" not in edge_id or "->" not in edge_id:
            return None
        kind, rest = edge_id.split(":", 1)
        src, dst = rest.split("->", 1)
        if kind not in REL_PAIRS:
            return None
        return kind, src, dst

    # ---------------------------------------------------------------- #
    # Reads
    # ---------------------------------------------------------------- #

    def _label_of(self, node_id: str) -> str | None:
        res = self._conn.execute("MATCH (n) WHERE n.id = $id RETURN label(n)", {"id": node_id})
        if not res.has_next():
            return None
        return res.get_next()[0]

    def node_count(self) -> int:
        total = 0
        for kind in NODE_KINDS:
            res = self._conn.execute(f"MATCH (n:{kind}) RETURN COUNT(*)")
            total += res.get_next()[0]
        return total

    def people(self) -> list[Person]:
        res = self._conn.execute(
            "MATCH (p:Person) RETURN p.id, p.name, p.relationship, p.address_terms, "
            "p.notes, p.weight"
        )
        out: list[Person] = []
        while res.has_next():
            row = res.get_next()
            out.append(
                Person(
                    id=row[0],
                    name=row[1],
                    relationship=row[2],
                    address_terms=row[3] or [],
                    notes=row[4] or "",
                    weight=row[5],
                )
            )
        return out

    def snapshot(self) -> tuple[list[GraphNode], list[GraphEdge]]:
        nodes: list[GraphNode] = []
        for kind in NODE_KINDS:
            res = self._conn.execute(f"MATCH (n:{kind}) RETURN n")
            while res.has_next():
                props = res.get_next()[0]
                nodes.append(
                    GraphNode(
                        id=props["id"],
                        label=_label_for(props),
                        kind=kind,
                        weight=props["weight"],
                        last_accessed=props["last_accessed"].timestamp(),
                    )
                )

        edges: list[GraphEdge] = []
        for kind in REL_KINDS:
            res = self._conn.execute(f"MATCH (a)-[r:{kind}]->(b) RETURN a.id, b.id, r.weight")
            while res.has_next():
                src, dst, weight = res.get_next()
                edges.append(
                    GraphEdge(
                        id=f"{kind}:{src}->{dst}",
                        source=src,
                        target=dst,
                        kind=kind,
                        weight=weight,
                    )
                )
        return nodes, edges

    def _ensure_vector_cache(self) -> None:
        if self._vector_cache is not None:
            return
        ids: list[str] = []
        kinds: list[str] = []
        names: list[str] = []
        facts: list[str] = []
        weights: list[float] = []
        vectors: list[list[float]] = []
        for kind in NODE_KINDS:
            res = self._conn.execute(f"MATCH (n:{kind}) RETURN n")
            while res.has_next():
                props = res.get_next()[0]
                ids.append(props["id"])
                kinds.append(kind)
                names.append(_label_for(props))
                facts.append(_fact_for(kind, props))
                weights.append(props["weight"])
                vectors.append(props["embedding"])
        matrix = (
            np.array(vectors, dtype=np.float64)
            if vectors
            else np.zeros((0, self._embedding_dim), dtype=np.float64)
        )
        self._vector_cache = {
            "ids": ids,
            "kinds": kinds,
            "names": names,
            "facts": facts,
            "weights": weights,
            "matrix": matrix,
        }

    @property
    def embedding_dim(self) -> int:
        return self._embedding_dim

    def get_node(self, node_id: str) -> NodeRef | None:
        """Fetch one node by id. Not part of section 10.2's required list,

        but a small, boring helper retrieval.py needs for the partner
        boost (section 11 stage 3) without duplicating query logic.
        """
        kind = self._label_of(node_id)
        if kind is None:
            return None
        res = self._conn.execute(f"MATCH (n:{kind} {{id: $id}}) RETURN n", {"id": node_id})
        if not res.has_next():
            return None
        props = res.get_next()[0]
        return NodeRef(
            id=node_id,
            kind=kind,
            name=_label_for(props),
            weight=props["weight"],
            embedding=props["embedding"],
            fact=_fact_for(kind, props),
        )

    def edges_among(self, node_ids: list[str]) -> list[EdgeRef]:
        """Edges with both endpoints in ``node_ids``.

        Not part of section 10.2's required list; retrieval.py's final
        rendering step (section 11) needs this without paying for a
        full ``snapshot()`` scan of every rel table on every turn. One
        untyped query across every rel table beats one query per rel
        kind -- each round trip has a fixed cost that dominates at
        this result size (measured ~5 ms/query, ~40 ms for 8 kinds).
        """
        if len(node_ids) < 2:
            return []
        res = self._conn.execute(
            "MATCH (a)-[r]->(b) WHERE a.id IN $ids AND b.id IN $ids "
            "RETURN a.id, b.id, label(r), r.weight",
            {"ids": node_ids},
        )
        out: list[EdgeRef] = []
        while res.has_next():
            src, dst, kind, weight = res.get_next()
            out.append(
                EdgeRef(id=f"{kind}:{src}->{dst}", kind=kind, source=src, target=dst, weight=weight)
            )
        return out

    def get_embeddings(self, node_ids: list[str]) -> dict[str, np.ndarray]:
        """Reuse the vector_search cache instead of a fresh query per id."""
        self._ensure_vector_cache()
        cache = self._vector_cache
        assert cache is not None
        index = {node_id: row for row, node_id in enumerate(cache["ids"])}
        return {nid: cache["matrix"][index[nid]] for nid in node_ids if nid in index}

    def vector_search(self, q: np.ndarray, k: int) -> list[NodeRef]:
        """Section 10.2: cached numpy matrix, brute-force cosine.

        Invalidated on any write (upsert_node/upsert_edge/reinforce
        clear the cache); rebuilt here on first use after that.
        """
        self._ensure_vector_cache()
        cache = self._vector_cache
        assert cache is not None
        matrix: np.ndarray = cache["matrix"]
        if matrix.shape[0] == 0 or k <= 0:
            return []

        q = np.asarray(q, dtype=np.float64)
        q_norm = np.linalg.norm(q)
        if q_norm == 0:
            return []
        row_norms = np.linalg.norm(matrix, axis=1)
        row_norms = np.where(row_norms == 0, 1e-12, row_norms)
        sims = (matrix @ q) / (row_norms * q_norm)

        k = min(k, matrix.shape[0])
        top_idx = np.argpartition(-sims, k - 1)[:k]
        top_idx = top_idx[np.argsort(-sims[top_idx])]

        return [
            NodeRef(
                id=cache["ids"][i],
                kind=cache["kinds"][i],
                name=cache["names"][i],
                weight=cache["weights"][i],
                embedding=cache["matrix"][i].tolist(),
                fact=cache["facts"][i],
            )
            for i in top_idx
        ]

    def expand(self, seeds: list[NodeRef], hops: int, cap: int) -> list[NodeRef]:
        """Section 10.2: breadth-first, union with seeds, cap by weight.

        Walked one hop at a time with plain (untyped, undirected)
        1-hop matches rather than a single ``[*1..hops]`` variable-length
        pattern. Kuzu's variable-length match enumerates every simple
        path up to length ``hops`` before deduplicating, which blows up
        combinatorially on a hub-heavy graph (e.g. many nodes attached
        directly to the user); layer-by-layer BFS visits each node at
        most once per hop instead. Measured ~130-200 ms -> ~15-30 ms at
        300 nodes with a single hub of degree ~300.

        Only ``(id, label, weight)`` come back from Cypher -- the
        384-double embedding for each row is looked up in the
        already-in-memory vector cache instead of being marshalled
        through the Python bindings on every call.
        """
        if not seeds:
            return []
        self._ensure_vector_cache()
        cache = self._vector_cache
        assert cache is not None
        row_by_id = {node_id: row for row, node_id in enumerate(cache["ids"])}

        def to_node_ref(node_id: str, kind: str, weight: float) -> NodeRef:
            row = row_by_id.get(node_id)
            return NodeRef(
                id=node_id,
                kind=kind,
                name=cache["names"][row] if row is not None else "",
                weight=weight,
                embedding=cache["matrix"][row].tolist() if row is not None else None,
                fact=cache["facts"][row] if row is not None else "",
            )

        visited: dict[str, NodeRef] = {s.id: s for s in seeds}
        frontier = [s.id for s in seeds]
        for _ in range(max(0, hops)):
            if not frontier:
                break
            res = self._conn.execute(
                "MATCH (s)-[]-(n) WHERE s.id IN $ids RETURN DISTINCT n.id, label(n), n.weight",
                {"ids": frontier},
            )
            next_frontier: list[str] = []
            while res.has_next():
                node_id, kind, weight = res.get_next()
                if node_id in visited:
                    continue
                visited[node_id] = to_node_ref(node_id, kind, weight)
                next_frontier.append(node_id)
            frontier = next_frontier

        ordered = sorted(visited.values(), key=lambda n: n.weight, reverse=True)
        return ordered[:cap]

    # ---------------------------------------------------------------- #
    # Seeding (section 14)
    # ---------------------------------------------------------------- #

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Keep memory writes atomic, including cache invalidation on rollback."""
        self._conn.execute("BEGIN TRANSACTION")
        try:
            yield
            self._conn.execute("COMMIT")
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        finally:
            self._vector_cache = None

    def seed_from_json(self, payload: dict[str, Any]) -> SeedResult:
        """Validate proposals before atomically inserting them.

        Malformed proposals are dropped. Storage errors are allowed to escape
        and roll back the entire transaction instead of becoming partial seeds.
        """
        nodes: list[tuple[str, dict[str, Any]]] = []
        kinds: dict[str, str] = {}
        aliases: dict[str, str] = {}
        dropped = 0
        for raw in payload.get("nodes", []):
            if not isinstance(raw, dict) or raw.get("kind") not in NODE_COLUMN_TYPES:
                dropped += 1
                continue
            kind = raw["kind"]
            props = dict(raw)
            text_col = NODE_TEXT_COLUMN[kind]
            text = props.get(text_col) or props.get("name")
            if not isinstance(text, str) or not text.strip():
                dropped += 1
                continue
            props[text_col] = text.strip()
            node_id = props.get("id") or f"{kind.lower()}_{uuid.uuid4().hex[:12]}"
            valid = isinstance(node_id, str) and node_id not in kinds
            for col, sql_type in NODE_COLUMN_TYPES[kind].items():
                value = props.get(col, [] if sql_type == "STRING[]" else "")
                valid = valid and (
                    isinstance(value, list) and all(isinstance(v, str) for v in value)
                    if sql_type == "STRING[]"
                    else isinstance(value, str)
                )
            weight = props.get("weight", 1.0)
            valid = valid and isinstance(weight, int | float) and math.isfinite(weight)
            if not valid:
                dropped += 1
                continue
            props["id"] = node_id
            # External JSON never supplies database timestamp objects.
            props.pop("last_accessed", None)
            kinds[node_id] = kind
            aliases[str(raw.get("id") or text)] = node_id
            nodes.append((kind, props))

        edges: list[tuple[str, str, str, dict[str, Any]]] = []
        for raw in payload.get("edges", []):
            if not isinstance(raw, dict) or raw.get("kind") not in REL_PAIRS:
                dropped += 1
                continue
            kind = raw["kind"]
            src = aliases.get(str(raw.get("source")), str(raw.get("source")))
            dst = aliases.get(str(raw.get("target")), str(raw.get("target")))
            valid = (kinds.get(src), kinds.get(dst)) in REL_PAIRS[kind]
            for col in ("weight", "strength"):
                value = raw.get(col, 1.0)
                valid = valid and isinstance(value, int | float) and math.isfinite(value)
            valid = valid and isinstance(raw.get("count", 1), int)
            if not valid:
                dropped += 1
                continue
            edges.append((kind, src, dst, raw))

        with self.transaction():
            for kind, props in nodes:
                self.upsert_node(kind, props)
            for kind, src, dst, props in edges:
                self.upsert_edge(kind, src, dst, props)
        return SeedResult(
            node_count=len(nodes),
            edge_count=len(edges),
            node_ids=list(kinds),
            dropped=dropped,
        )

    def close(self) -> None:
        """Release handles explicitly so restart can reopen the same database."""
        self._conn.close()
        self._db.close()
