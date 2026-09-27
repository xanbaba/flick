"""Telemetry sink for TimescaleDB (ARCHITECTURE.md section 18.2).

"The database must never be able to stall the pipeline." emit() does
exactly one thing -- queue.put_nowait -- and never awaits, retries or
raises. A background task drains the queue on a timer and writes via
asyncpg. If the database is unreachable, the consumer logs once per
30 s and keeps draining into the void so the queue never backs up.

SW-14: TimescaleDB is never on the critical path. With no
TIMESCALE_DSN configured (for example, with an empty .env), the
consumer drains and discards every batch -- emit() behaves
identically either way, which is what makes this safe to call from
everywhere without an early-boot ordering dependency on the database.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from shared.logging import get_logger

logger = get_logger(__name__)

_UNREACHABLE_LOG_INTERVAL_S = 30.0


class TelemetryService:
    def __init__(
        self,
        *,
        queue_maxsize: int,
        flush_interval_ms: int,
        flush_batch: int,
        dsn: str,
    ) -> None:
        self._queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(
            maxsize=queue_maxsize
        )
        self._flush_interval_s = flush_interval_ms / 1000.0
        self._flush_batch = flush_batch
        self._dsn = dsn
        self._dropped = 0
        self._pool: Any | None = None
        self._pool_init_failed = False
        self._consumer_task: asyncio.Task[None] | None = None
        self._last_unreachable_log = 0.0

    @property
    def dropped_count(self) -> int:
        return self._dropped

    def emit(self, table: str, record: dict[str, Any]) -> None:
        """Synchronous. Never awaits, never retries, never raises."""
        try:
            self._queue.put_nowait((table, record))
        except asyncio.QueueFull:
            self._dropped += 1

    async def start(self) -> None:
        if self._consumer_task is None:
            self._consumer_task = asyncio.create_task(self._consume_loop())

    async def stop(self) -> None:
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            self._consumer_task = None
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def _consume_loop(self) -> None:
        while True:
            await asyncio.sleep(self._flush_interval_s)
            batch = self._drain_batch()
            if batch:
                await self._flush(batch)

    def _drain_batch(self) -> dict[str, list[dict[str, Any]]]:
        batch: dict[str, list[dict[str, Any]]] = {}
        for _ in range(self._flush_batch):
            try:
                table, record = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            batch.setdefault(table, []).append(record)
        return batch

    async def _flush(self, batch: dict[str, list[dict[str, Any]]]) -> None:
        if not self._dsn:
            return  # no DSN configured (for example, empty .env): best-effort, drop
        try:
            pool = await self._get_pool()
        except Exception as exc:
            self._log_unreachable(exc)
            return
        try:
            async with pool.acquire() as conn:
                for table, records in batch.items():
                    columns = list(records[0].keys())
                    values = [[record[c] for c in columns] for record in records]
                    await conn.copy_records_to_table(table, records=values, columns=columns)
        except Exception as exc:
            self._log_unreachable(exc)

    async def _get_pool(self) -> Any:
        if self._pool is not None:
            return self._pool
        import asyncpg

        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=4)
        return self._pool

    def _log_unreachable(self, exc: Exception) -> None:
        now = time.monotonic()
        if now - self._last_unreachable_log >= _UNREACHABLE_LOG_INTERVAL_S:
            logger.warning("telemetry.db_unreachable", error=str(exc))
            self._last_unreachable_log = now
