"""Serialize application graph/embedding work away from the asyncio loop."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


class MemoryWorker:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="memory")

    async def run(self, fn: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        future = asyncio.get_running_loop().run_in_executor(
            self._executor, partial(fn, *args, **kwargs)
        )
        # A cancelled request must not leave an unobserved database write running.
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            await future
            raise

    async def close(self) -> None:
        await asyncio.to_thread(self._executor.shutdown, wait=True)


async def run_memory(
    worker: MemoryWorker | None, fn: Callable[P, T], *args: P.args, **kwargs: P.kwargs
) -> T:
    """Standalone service callers remain supported; the app always supplies a worker."""
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    if worker is None:
        return fn(*args, **kwargs)
    return await worker.run(fn, *args, **kwargs)
