"""Analysis for the sequential-flicker feasibility test.

    python analyze.py                 # newest session in ./sessions
    python analyze.py sessions/<dir>  # a specific session

PRIMARY analysis (fixed before any data is seen — this is the number that
decides go / no-go): feature = low-beta (betaL, 12-16 Hz) band power on O1
and O2, log10, z-scored against the baseline block, averaged over the part
of each slot where Cortex's 2-second band-power window lies fully inside
the slot. Per cycle, the tile with the highest score is the prediction.

EXPLORATORY analyses (other bands, sensors, lags) are printed separately.
Picking the best of many exploratory numbers overstates accuracy; treat
them as ideas to test in the next session, not as results.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent

PRIMARY_BAND = "betaL"
PRIMARY_SENSORS = ("O1", "O2")
POW_WINDOW_S = 2.0  # Cortex: each pow sample covers the last 2 s of EEG
PRIMARY_LAG_S = 0.15  # allowance for Cortex processing delay
Z_THRESHOLD = 1.0  # decision rule, as ARCHITECTURE.md §8.4
MARGIN_SD = 0.3
PASS_ACCURACY = 0.60  # ARCHITECTURE.md §7.6
ALPHA = 0.05


# ------------------------------------------------------------------ loading


def _read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        header = next(r)
        return header, [row for row in r if row]


def _num(x):
    if x in ("", "None", None):
        return None
    try:
        return float(x)
    except ValueError:
        return x


def load(folder: Path) -> dict:
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    h, rows = _read_csv(folder / "events.csv")
    events = [{k: _num(v) for k, v in zip(h, row, strict=False)} for row in rows]
    ph, prow = _read_csv(folder / "pow.csv")
    arr = np.array([[float(v) for v in row] for row in prow], dtype=float)
    fac = []
    if (folder / "fac.csv").exists():
        fh, frows = _read_csv(folder / "fac.csv")
        fac = [(float(r[0]), r[1]) for r in frows]
    dev = None
    if (folder / "dev.csv").exists():
        dh, drows = _read_csv(folder / "dev.csv")
        dev = (dh, drows)
    return {
        "meta": meta,
        "events": events,
        "pow_cols": ph[1:],
        "t": arr[:, 0],
        "pow": arr[:, 1:],
        "fac": fac,
        "dev": dev,
    }


# ------------------------------------------------------------------ helpers


def binom_p_at_least(k: int, n: int, p: float) -> float:
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))


def min_correct_for(n: int, p0: float) -> int | None:
    return next((k for k in range(n + 1) if binom_p_at_least(k, n, p0) < ALPHA), None)


class Features:
    def __init__(self, d: dict) -> None:
        self.t = d["t"]
        self.cols = d["pow_cols"]
        self.logp = np.log10(np.clip(d["pow"], 1e-12, None))
        base = [e for e in d["events"] if e["phase"] == "baseline"]
        if not base:
            raise SystemExit("No baseline block in this session.")
        b = base[0]
        m = self._mask(b["t_wall"] + POW_WINDOW_S, b["t_wall"] + b["actual_s"])
        self.n_baseline = int(m.sum())
        if self.n_baseline < 20:
            raise SystemExit(f"Only {self.n_baseline} pow samples in the baseline.")
        mu = self.logp[m].mean(axis=0)
        sd = self.logp[m].std(axis=0)
        sd[sd == 0] = 1.0
        self.z = (self.logp - mu) / sd

    def _mask(self, t0: float, t1: float) -> np.ndarray:
        return (self.t >= t0) & (self.t <= t1)

    def idx(self, sensors, band) -> list[int]:
        want = {f"{s}/{band}" for s in sensors}
        return [i for i, c in enumerate(self.cols) if c in want]

    def score(self, t0: float, t1: float, idx: list[int]) -> float:
        m = self._mask(t0, t1)
        if not m.any() or not idx:
            return float("nan")
        return float(self.z[m][:, idx].mean())

    def slot_score(self, ev: dict, idx: list[int], lag: float) -> float:
        on = ev["t_wall"]
        return self.score(on + POW_WINDOW_S + lag, on + ev["actual_s"] + lag, idx)


def trials(events: list[dict], block_prefix: str) -> list[dict]:
    """One trial per (block, cycle): the slot events for each tile."""
    by = defaultdict(dict)
    for e in events:
        if e["phase"] == "slot" and str(e["block"]).startswith(block_prefix):
            by[(e["block"], int(e["cycle"]))][int(e["active_tile"])] = e
    out = []
    for (block, cycle), slots in sorted(by.items()):
        tgt = next(iter(slots.values()))["target"]
        out.append(
            {
                "block": block,
                "cycle": cycle,
                "slots": slots,
                "target": None if tgt is None else int(tgt),
            }
        )
    return out


def predict(scores: dict[int, float]) -> tuple[int | None, float, float]:
    valid = {k: v for k, v in scores.items() if not math.isnan(v)}
    if len(valid) < 2:
        return None, float("nan"), float("nan")
    ranked = sorted(valid.items(), key=lambda kv: kv[1], reverse=True)
    return ranked[0][0], ranked[0][1], ranked[0][1] - ranked[1][1]


def accuracy(F: Features, tr: list[dict], idx: list[int], lag: float) -> tuple[int, int]:
    n = correct = 0
    for t in tr:
        pred, _, _ = predict({k: F.slot_score(e, idx, lag) for k, e in t["slots"].items()})
        if pred is None:
            continue
        n += 1
        correct += int(pred == t["target"])
    return correct, n


# ------------------------------------------------------------------ report


def analyze(folder: Path | str, write: bool = True) -> str:
    folder = Path(folder)
    d = load(folder)
    meta, events = d["meta"], d["events"]
    cfg = meta["config"]
    n_tiles = cfg["n_tiles"]
    chance = 1.0 / n_tiles
    F = Features(d)
    idx = F.idx(PRIMARY_SENSORS, PRIMARY_BAND)
    L: list[str] = []
    out: dict = {"session": folder.name}

    if str(meta.get("source", "")).startswith("synthetic"):
        L.append(
            f"> **SYNTHETIC DATA** (effect {meta.get('synthetic_effect_sd')} SD). "
            "This tests the pipeline only. It is not evidence about the method.\n"
        )
    L.append(f"# Sequential-flicker test — {folder.name}\n")
    L.append(
        f"- Source: {meta.get('source')}, headset {meta.get('headset_id', '-')}, "
        f"subject `{meta.get('subject')}`"
    )
    L.append(
        f"- Display: {meta.get('measured_refresh_hz')} Hz measured, "
        f"{meta.get('frames_per_cycle')} frames per {cfg['flicker_hz']:g} Hz cycle, "
        f"exact={meta.get('exact')}"
    )
    L.append(
        f"- Slots {cfg['slot_s']} s + gap {cfg['gap_s']} s, {cfg['cycles_per_run']} "
        f"cycles per run, order `{cfg['order']}`, contrast {cfg['contrast']}"
    )
    L.append(f"- Completed: {meta.get('completed')}, aborted: {meta.get('aborted', False)}")
    L.append(f"- Baseline pow samples: {F.n_baseline}; total pow samples: {len(F.t)}\n")

    # Data quality
    drops = sum(int(e.get("dropped_frames") or 0) for e in events if e["phase"] == "slot")
    bad_slots = sum(
        1 for e in events if e["phase"] == "slot" and int(e.get("dropped_frames") or 0) > 5
    )
    L.append("## Data quality\n")
    L.append(f"- Dropped frames during slots: {drops} total; slots with >5 drops: {bad_slots}")
    if d["dev"]:
        dh, drows = d["dev"]
        for s in PRIMARY_SENSORS:
            if f"cq_{s}" in dh:
                i = dh.index(f"cq_{s}")
                vals = [float(r[i]) for r in drows if r[i] not in ("", "None")]
                if vals:
                    L.append(
                        f"- Contact quality {s}: mean {np.mean(vals):.1f}, "
                        f"min {min(vals):.0f} (0-4, want >=3)"
                    )
    L.append("")

    # Sanity check
    L.append("## 1. Signal check (all tiles flicker vs none)\n")
    on = [e for e in events if e["phase"] == "sanity_on"]
    off = [e for e in events if e["phase"] == "sanity_off"]
    if on and off:
        diffs = []
        L.append("| rep | flicker z | static z | difference |")
        L.append("|---|---|---|---|")
        for a, b in zip(on, off, strict=False):
            za, zb = F.slot_score(a, idx, PRIMARY_LAG_S), F.slot_score(b, idx, PRIMARY_LAG_S)
            diffs.append(za - zb)
            L.append(f"| {int(a['cycle']) + 1} | {za:+.2f} | {zb:+.2f} | {za - zb:+.2f} |")
        md = float(np.nanmean(diffs))
        ok = md >= 0.5 and all(x > 0 for x in diffs)
        out["sanity_mean_diff"] = md
        out["sanity_pass"] = ok
        L.append(
            f"\nMean difference **{md:+.2f} SD** -> "
            + (
                "**PASS**: the headset's low-beta power responds to the 15 Hz flicker."
                if ok
                else "**FAIL**: no clear response even when everything flickers. "
                "Check O1/O2 contact before trusting anything below."
            )
        )
    else:
        L.append("Skipped.")
    L.append("")

    # Primary
    tr = trials(events, "run")
    L.append("## 2. Primary result: which tile was being looked at?\n")
    conf = np.zeros((n_tiles, n_tiles), dtype=int)
    rows = []
    for t in tr:
        scores = {k: F.slot_score(e, idx, PRIMARY_LAG_S) for k, e in t["slots"].items()}
        pred, top, margin = predict(scores)
        rows.append((t, scores, pred, top, margin))
        if pred is not None:
            conf[t["target"], pred] += 1
    n = int(conf.sum())
    correct = int(np.trace(conf))
    acc = correct / n if n else float("nan")
    p = binom_p_at_least(correct, n, chance) if n else float("nan")
    need = min_correct_for(n, chance) if n else None
    out.update(primary_accuracy=acc, primary_correct=correct, primary_n=n, primary_p=p)
    L.append(
        f"**Accuracy {correct}/{n} = {acc:.0%}** (chance {chance:.0%}); "
        f"one-sided binomial p = {p:.4f}. "
        f"{need} correct needed for p < {ALPHA}.\n"
    )
    L.append("Confusion (rows = tile looked at, columns = tile predicted):\n")
    L.append(
        "| looked at \\ predicted | "
        + " | ".join(f"tile {j + 1}" for j in range(n_tiles))
        + " | accuracy |"
    )
    L.append("|---" * (n_tiles + 2) + "|")
    for i in range(n_tiles):
        r = conf[i]
        L.append(
            f"| tile {i + 1} | " + " | ".join(str(x) for x in r) + f" | {r[i] / r.sum():.0%} |"
            if r.sum()
            else f"| tile {i + 1} | - |"
        )
    L.append("")

    # Decision rule, averaging, blinks
    sel = [
        (t, pr)
        for t, s, pr, top, m in rows
        if pr is not None and top >= Z_THRESHOLD and m >= MARGIN_SD
    ]
    sel_ok = sum(1 for t, pr in sel if pr == t["target"])
    L.append(
        f"- With the idle rule (winner z >= {Z_THRESHOLD}, lead >= {MARGIN_SD} SD): "
        f"selects in {len(sel)}/{n} cycles, correct in {sel_ok}/{len(sel)}"
        + (f" ({sel_ok / len(sel):.0%})" if sel else "")
    )
    pair_ok = pair_n = 0
    by_block = defaultdict(list)
    for t, s, *_ in rows:
        by_block[t["block"]].append((t, s))
    for items in by_block.values():
        for i in range(0, len(items) - 1, 2):
            (t1, s1), (_, s2) = items[i], items[i + 1]
            avg = {k: np.nanmean([s1.get(k, np.nan), s2.get(k, np.nan)]) for k in s1}
            pr, _, _ = predict(avg)
            if pr is not None:
                pair_n += 1
                pair_ok += int(pr == t1["target"])
    if pair_n:
        out["two_cycle_accuracy"] = pair_ok / pair_n
        L.append(
            f"- Averaging two cycles per decision: {pair_ok}/{pair_n} = "
            f"{pair_ok / pair_n:.0%} (twice as slow per selection)"
        )
    blinks = [bt for bt, act in d["fac"] if act == "blink"]
    if blinks:
        clean_ok = clean_n = 0
        for t, _s, pr, *_ in rows:
            e = t["slots"].get(t["target"])
            if pr is None or e is None:
                continue
            if any(e["t_wall"] <= b <= e["t_wall"] + e["actual_s"] for b in blinks):
                continue
            clean_n += 1
            clean_ok += int(pr == t["target"])
        if clean_n:
            L.append(
                f"- Excluding cycles with a blink during the looked-at slot: "
                f"{clean_ok}/{clean_n} = {clean_ok / clean_n:.0%}"
            )
    L.append("")

    # Idle control
    L.append("## 3. Control run: looking at the cross\n")
    idle = trials(events, "idle")
    if idle:
        fp = 0
        picks = defaultdict(int)
        for t in idle:
            s = {k: F.slot_score(e, idx, PRIMARY_LAG_S) for k, e in t["slots"].items()}
            pr, top, m = predict(s)
            if pr is not None:
                picks[pr] += 1
                if top >= Z_THRESHOLD and m >= MARGIN_SD:
                    fp += 1
        out["idle_false_selections"] = fp
        out["idle_cycles"] = len(idle)
        L.append(
            f"- The idle rule would have selected something in {fp}/{len(idle)} cycles "
            "(want 0 or close to it)."
        )
        L.append(
            "- Tile with the highest score when nobody looked at a tile: "
            + ", ".join(f"tile {k + 1}: {v}" for k, v in sorted(picks.items()))
            + " (roughly even = no position or order bias)."
        )
    else:
        L.append("Skipped.")
    L.append("")

    # Time course
    L.append("## 4. Time course (O1/O2 low-beta z, mean over run slots)\n")
    L.append(
        "Seconds from slot onset. The looked-at column should rise ~2 s after onset "
        "(Cortex's window) and fall after the slot ends; the other column should stay "
        "near zero.\n"
    )
    L.append("| t (s) | looked-at tile flickering | other tile flickering |")
    L.append("|---|---|---|")
    slot_evs = [e for e in events if e["phase"] == "slot" and str(e["block"]).startswith("run")]
    dur = cfg["slot_s"] + cfg["gap_s"]
    for b0 in np.arange(-1.0, dur + 2.01, 0.5):
        vals = {True: [], False: []}
        for e in slot_evs:
            is_t = int(e["active_tile"]) == int(e["target"])
            vals[is_t].append(F.score(e["t_wall"] + b0, e["t_wall"] + b0 + 0.5, idx))
        L.append(f"| {b0:+.1f} | {np.nanmean(vals[True]):+.2f} | {np.nanmean(vals[False]):+.2f} |")
    L.append("")

    # Exploratory
    L.append("## 5. Exploratory (not the decision — see note at top of analyze.py)\n")
    sets = {
        "O1+O2": ("O1", "O2"),
        "O1": ("O1",),
        "O2": ("O2",),
        "P7+P8": ("P7", "P8"),
        "O1+O2+P7+P8": ("O1", "O2", "P7", "P8"),
    }
    bands = ["theta", "alpha", "betaL", "betaH", "gamma"]
    L.append("| sensors | " + " | ".join(bands) + " |")
    L.append("|---" * (len(bands) + 1) + "|")
    for name, ss in sets.items():
        cells = []
        for b in bands:
            c, nn = accuracy(F, tr, F.idx(ss, b), PRIMARY_LAG_S)
            cells.append(f"{c / nn:.0%}" if nn else "-")
        L.append(f"| {name} | " + " | ".join(cells) + " |")
    L.append("\nPrimary feature at other lags:\n")
    L.append("| lag (s) | " + " | ".join(f"{x:.2f}" for x in (0, 0.15, 0.3, 0.5)) + " |")
    L.append("|---|---|---|---|---|")
    cells = []
    for lag in (0.0, 0.15, 0.3, 0.5):
        c, nn = accuracy(F, tr, idx, lag)
        cells.append(f"{c / nn:.0%}" if nn else "-")
    L.append("| accuracy | " + " | ".join(cells) + " |")
    L.append("")

    # Verdict
    L.append("## Verdict\n")
    if not n:
        verdict = "NO DATA: no complete run cycles were recorded."
    elif out.get("sanity_pass") is False:
        verdict = (
            "INCONCLUSIVE: the signal check failed, so the headset did not see the "
            "flicker at all. Fix contact on O1/O2 and repeat before judging the idea."
        )
    elif acc >= PASS_ACCURACY and p < ALPHA:
        verdict = (
            f"GO: {acc:.0%} with p = {p:.4f} meets the §7.6 bar "
            f"(>= {PASS_ACCURACY:.0%}, p < {ALPHA}). Repeat once on a different day "
            "(or with runs in reverse order) before building the demo on it."
        )
    elif p < ALPHA:
        verdict = (
            f"PROMISING: above chance (p = {p:.4f}) but {acc:.0%} is under the "
            f"{PASS_ACCURACY:.0%} bar. Try the two-cycle average, a longer slot, "
            "or the best exploratory feature in a NEW session."
        )
    else:
        verdict = (
            f"NO-GO: {acc:.0%} is not distinguishable from chance ({chance:.0%}) "
            f"(p = {p:.4f}). Use scan_switch (§7.3) as the selection method."
        )
    out["verdict"] = verdict
    L.append(verdict)

    report = "\n".join(L) + "\n"
    if write:
        (folder / "report.md").write_text(report, encoding="utf-8")
        (folder / "summary.json").write_text(
            json.dumps(out, indent=2, default=float), encoding="utf-8"
        )
    return report


def main() -> None:
    if len(sys.argv) > 1:
        folder = Path(sys.argv[1])
    else:
        sessions = sorted((HERE / "sessions").glob("*/meta.json"))
        if not sessions:
            sys.exit("No sessions found.")
        folder = sessions[-1].parent
    print(analyze(folder))


if __name__ == "__main__":
    main()
