"""Bounded read-only Kuzu export, rollback copy, atomic Tiger import and comparison.

Stop the old backend first. The target profile must not exist. No source data is
deleted. Embeddings are regenerated consistently because legacy provenance was
not recorded. Backups contain personal data; keep them outside version control.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
from pathlib import Path
from typing import Any

import kuzu

from backend.app.services.graph import NODE_KINDS, REL_KINDS
from backend.app.services.tiger import TigerGraphService
from backend.providers.registry import get_embedding_provider
from shared.config import EnvSettings, load_config
from shared.logging import get_logger

logger = get_logger(__name__)


def export_kuzu(
    source: Path,
    backup: Path,
    max_nodes: int,
    max_edges: int,
) -> dict[str, Any]:
    source = source.resolve(strict=True)
    backup = backup.resolve()
    if backup.exists() or backup == source or source in backup.parents:
        raise ValueError("Choose a new backup path outside the source database")
    if max_nodes <= 0 or max_edges <= 0:
        raise ValueError("Export bounds must be positive")
    db = kuzu.Database(str(source), read_only=True)
    conn = kuzu.Connection(db)
    nodes, edges = [], []
    try:
        for kind in NODE_KINDS:
            result = conn.execute(f"MATCH (n:{kind}) RETURN n LIMIT {max_nodes + 1}")
            while result.has_next():
                props = result.get_next()[0]
                props = {
                    k: v for k, v in props.items() if not k.startswith("_") and k != "embedding"
                }
                nodes.append({**props, "kind": kind})
                if len(nodes) > max_nodes:
                    raise ValueError("Source exceeds node export bound")
        for kind in REL_KINDS:
            result = conn.execute(
                f"MATCH (a)-[r:{kind}]->(b) RETURN a.id,b.id,r LIMIT {max_edges + 1}"
            )
            while result.has_next():
                src, dst, props = result.get_next()
                props = {k: v for k, v in props.items() if not k.startswith("_")}
                edges.append(
                    {
                        **props,
                        "kind": kind,
                        "source": src,
                        "target": dst,
                        "id": f"{kind}:{src}->{dst}",
                    }
                )
                if len(edges) > max_edges:
                    raise ValueError("Source exceeds edge export bound")
        # Keep the source's read lock while making its rollback copy.
        backup.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, backup)
        else:
            shutil.copy2(source, backup)
    finally:
        conn.close()
        db.close()
    return {"nodes": nodes, "edges": edges}


async def import_memory(args: argparse.Namespace) -> None:
    config = load_config()
    env = EnvSettings(_env_file=args.env_file)
    dsn = env.local_pg_dsn if args.local else env.tiger_dsn
    if not dsn:
        raise ValueError("Requested destination DSN is not configured")
    payload = await asyncio.to_thread(
        export_kuzu, args.source, args.backup, args.max_nodes, args.max_edges
    )
    user = next((n for n in payload["nodes"] if n["id"] == "user"), None)
    if user is None or user["kind"] != "Person" or user.get("relationship") != "self":
        raise ValueError("Legacy graph has no valid self Person; source and backup are unchanged")
    bio = (
        await asyncio.to_thread(args.biography.read_text, encoding="utf-8")
        if args.biography
        else ""
    )
    graph = TigerGraphService(
        dsn,
        args.profile_id or config.graph.profile_id,
        get_embedding_provider(),
        config.database,
        config.reinforcement,
        destination="local_postgres" if args.local else "tiger",
    )
    try:
        await graph.open()
        result = await graph.seed_profile(payload, user["name"], bio, strict=True)
        logger.info(
            "memory.import_verified",
            nodes=result.node_count,
            edges=result.edge_count,
            destination=graph.destination,
            rollback_copy=str(args.backup),
        )
    finally:
        await graph.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--biography", type=Path)
    parser.add_argument("--profile-id")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--max-nodes", type=int, default=5000)
    parser.add_argument("--max-edges", type=int, default=20000)
    asyncio.run(import_memory(parser.parse_args()))


if __name__ == "__main__":
    main()
