"""inputs/replay.py — the demo fallback (ARCHITECTURE.md section 7.4).

Identical wiring to inputs/ssvep.py: subscribes to the sensor
process's Selection stream on ZMQ 5555 and publishes
stim.show_targets on ZMQ 5556. What differs is which sensor mode is
on the other end (mode.source: replay drives a recorded session
through the real classifier, per DEMO-2) and the persistent
on-screen badge naming what this is (DEMO-3): "This is the honest
crash-insurance... Every number a judge sees is real."
"""

from __future__ import annotations

from inputs.ssvep import SsvepInput


class ReplayInput(SsvepInput):
    name = "replay"
    badge: str | None = "REPLAY"
