"""Test protocol for the sequential-flicker feasibility test.

Pure data: no rendering, no I/O. The GUI runner, the headless runner and
the analysis all read the same schedule from here, so what is shown, what
is simulated and what is scored can never drift apart.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field


@dataclass
class Config:
    flicker_hz: float = 15.0  # exact divisor of 165, 120 and 60 Hz
    contrast: float = 1.0  # 0..1, luminance swing around mid-grey
    n_tiles: int = 3
    tile_px: int = 300
    tile_gap_px: int = 150
    slot_s: float = 4.0  # one tile flickering
    gap_s: float = 1.0  # all tiles static between slots
    cycles_per_run: int = 10  # one cycle = every tile flickers once
    baseline_s: float = 30.0  # eyes open on the cross, nothing flickering
    sanity_reps: int = 3  # positive control: all tiles flicker together
    sanity_on_s: float = 8.0
    sanity_off_s: float = 8.0
    idle_run: bool = True  # control run: look at the cross, not a tile
    order: str = "shuffled"  # "shuffled" (same shuffle in every run) | "fixed"
    seed: int = 7
    countdown_s: float = 3.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Segment:
    block: str  # "baseline" | "sanity" | "run1".."runN" | "idle"
    phase: str  # "baseline" | "sanity_on" | "sanity_off" | "slot" | "gap"
    duration_s: float
    target: int | None  # tile the user is told to look at; None = the cross
    active_tile: int | None = None  # tile flickering during a slot
    flicker_all: bool = False  # sanity_on only
    cycle: int | None = None
    slot_pos: int | None = None  # position within the cycle's order


@dataclass
class Block:
    name: str
    title: str
    instruction: str
    target: int | None
    segments: list[Segment] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        return sum(s.duration_s for s in self.segments)


def cycle_orders(cfg: Config) -> list[list[int]]:
    """The slot order for every cycle. Identical for every run, so the runs
    differ only in where the user looks."""
    tiles = list(range(cfg.n_tiles))
    if cfg.order == "fixed":
        return [tiles[:] for _ in range(cfg.cycles_per_run)]
    rng = random.Random(cfg.seed)
    orders = []
    for _ in range(cfg.cycles_per_run):
        o = tiles[:]
        rng.shuffle(o)
        orders.append(o)
    return orders


def _run_segments(cfg: Config, block: str, target: int | None) -> list[Segment]:
    segs: list[Segment] = []
    for c, order in enumerate(cycle_orders(cfg)):
        for pos, tile in enumerate(order):
            segs.append(
                Segment(block, "slot", cfg.slot_s, target, active_tile=tile, cycle=c, slot_pos=pos)
            )
            segs.append(Segment(block, "gap", cfg.gap_s, target, cycle=c, slot_pos=pos))
    return segs


def build_protocol(cfg: Config) -> list[Block]:
    blocks: list[Block] = []
    centre = cfg.n_tiles // 2

    blocks.append(
        Block(
            "baseline",
            "Baseline",
            "Look at the cross above the tiles. Relax your face, blink normally.\n"
            f"Nothing will flicker. {cfg.baseline_s:.0f} seconds.",
            None,
            [Segment("baseline", "baseline", cfg.baseline_s, None)],
        )
    )

    if cfg.sanity_reps > 0:
        segs = []
        for r in range(cfg.sanity_reps):
            segs.append(
                Segment("sanity", "sanity_on", cfg.sanity_on_s, centre, flicker_all=True, cycle=r)
            )
            segs.append(Segment("sanity", "sanity_off", cfg.sanity_off_s, centre, cycle=r))
        blocks.append(
            Block(
                "sanity",
                "Signal check",
                f"Look at the red dot on tile {centre + 1}. All tiles will flicker together, "
                "then stop, a few times.",
                centre,
                segs,
            )
        )

    for t in range(cfg.n_tiles):
        blocks.append(
            Block(
                f"run{t + 1}",
                f"Run {t + 1} of {cfg.n_tiles}",
                f"Look ONLY at tile {t + 1} (red dot) the whole run, even when another tile "
                "flickers. Keep your face relaxed.",
                t,
                _run_segments(cfg, f"run{t + 1}", t),
            )
        )

    if cfg.idle_run:
        blocks.append(
            Block(
                "idle",
                "Control run",
                "Look ONLY at the cross above the tiles the whole run. Do not look at any tile.",
                None,
                _run_segments(cfg, "idle", None),
            )
        )
    return blocks


def total_duration_s(cfg: Config) -> float:
    return sum(b.duration_s + cfg.countdown_s for b in build_protocol(cfg))
