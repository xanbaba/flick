"""inputs/base.py — the selection abstraction (ARCHITECTURE.md section 7.1).

This is the abstraction that decouples every other subsystem from the
EEG hardware. Nothing downstream of InputSource knows or cares how a
selection was produced. The orchestrator holds exactly one
InputSource; swapping adapters is a config change or a
POST /api/input, no other code changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from shared.schemas import Selection


class InputSource(ABC):
    name: str  # "keyboard", "ssvep", ...
    badge: str | None  # UI badge text; None for the production path
    n_targets: int
    supports_labels: bool  # can the adapter display text on targets?

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def set_targets(self, trial_id: str, labels: list[str], round: str) -> None:
        """Present n_targets options. For adapters that cannot render labels,
        the orchestrator is responsible for surfacing them elsewhere."""

    @abstractmethod
    def selections(self) -> AsyncIterator[Selection]:
        """Yields at most one Selection per trial_id."""

    def status(self) -> dict:
        """Adapter-specific health, merged into sys.status."""
        return {}

    def close_trial(self, reason: str = "closed") -> None:
        """Disarm the current interaction; legacy adapters may override separately."""
        return None
