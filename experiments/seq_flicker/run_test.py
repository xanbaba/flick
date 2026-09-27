"""Sequential-flicker feasibility test (ARCHITECTURE.md §7.3 seq_flicker, §7.6).

Three tiles in a row. One tile flickers at a time at 15 Hz, then the next,
in the same order in every run. In run N the user looks only at tile N.
Band power from the Emotiv EPOC X is recorded, and analyze.py checks
whether the tile being looked at can be picked out from the data.

    python run_test.py                      # real headset
    python run_test.py --synthetic          # on-screen dry run, fake signal
    python run_test.py --synthetic --headless   # no window, seconds (tests the pipeline)

Keys: SPACE / click = continue, ESC = abort (data so far is kept).
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import platform
import statistics
import sys
import threading
import time
from pathlib import Path

from protocol import Config, build_protocol, total_duration_s
from recorder import Recorder

HERE = Path(__file__).resolve().parent
STREAMS = ["pow", "fac", "dev", "eq"]
MEASURE_FRAMES = 300  # enough for a stable median at any refresh rate
MEASURE_MAX_S = 5.0  # never wait longer than this for the frames
MIN_FPS = 60  # below this a 15 Hz sinusoid cannot be drawn smoothly


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- utilities


def load_env(path: Path) -> None:
    """Read KEY=VALUE lines from the repo's .env without a dependency."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--synthetic", action="store_true", help="fake signal, no headset")
    p.add_argument("--headless", action="store_true", help="no window (needs --synthetic)")
    p.add_argument(
        "--effect",
        type=float,
        default=1.0,
        help="synthetic effect size in noise SDs (0 = no effect)",
    )
    p.add_argument("--subject", default="pilot")
    p.add_argument("--cycles", type=int, default=Config.cycles_per_run)
    p.add_argument("--slot-s", type=float, default=Config.slot_s)
    p.add_argument("--gap-s", type=float, default=Config.gap_s)
    p.add_argument("--flicker-hz", type=float, default=Config.flicker_hz)
    p.add_argument("--contrast", type=float, default=Config.contrast)
    p.add_argument("--order", choices=["shuffled", "fixed"], default=Config.order)
    p.add_argument("--no-idle", action="store_true", help="skip the look-at-the-cross run")
    p.add_argument("--no-sanity", action="store_true", help="skip the signal check")
    p.add_argument("--screen", type=int, default=0, help="monitor index for the stimulus")
    p.add_argument(
        "--windowed",
        action="store_true",
        help="1600x900 window instead of fullscreen (debugging only)",
    )
    p.add_argument(
        "--no-vsync",
        action="store_true",
        help="don't wait for vsync (use if check_display.py shows vsync is slow)",
    )
    p.add_argument("--headset", default=None, help="Cortex headset id (default: first)")
    p.add_argument("--out", default=str(HERE / "sessions"))
    a = p.parse_args()
    if a.headless and not a.synthetic:
        p.error("--headless only works with --synthetic")
    return a


def make_config(a: argparse.Namespace) -> Config:
    return Config(
        flicker_hz=a.flicker_hz,
        contrast=a.contrast,
        slot_s=a.slot_s,
        gap_s=a.gap_s,
        cycles_per_run=a.cycles,
        order=a.order,
        idle_run=not a.no_idle,
        sanity_reps=0 if a.no_sanity else 3,
    )


def session_folder(a: argparse.Namespace) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    tag = "synthetic" if a.synthetic else "emotiv"
    return Path(a.out) / f"{stamp}_{a.subject}_{tag}"


# ----------------------------------------------------------- headless path


def run_headless(a: argparse.Namespace, cfg: Config) -> Path:
    from synthetic import POW_HZ, SyntheticStreams

    syn = SyntheticStreams(effect_sd=a.effect)
    folder = session_folder(a)
    rec = Recorder(folder, syn.cols, base_meta(a, cfg, source="synthetic-headless"))
    rec.meta.update(measured_refresh_hz=165.0, frames_per_cycle=165.0 / cfg.flicker_hz, exact=True)
    t = time.time()
    t_start = t
    for block in build_protocol(cfg):
        t += cfg.countdown_s
        for seg in block.segments:
            syn.add_segment(t, t + seg.duration_s, seg)
            rec.event(
                t_wall=t,
                block=seg.block,
                phase=seg.phase,
                target=seg.target,
                active_tile=seg.active_tile,
                flicker_all=int(seg.flicker_all),
                cycle=seg.cycle,
                slot_pos=seg.slot_pos,
                planned_s=seg.duration_s,
                actual_s=seg.duration_s,
                frames=round(seg.duration_s * 165),
                dropped_frames=0,
            )
            t += seg.duration_s
    # Stream samples over the whole timeline, as Cortex would have.
    step = 1.0 / POW_HZ
    ts = t_start
    k = 0
    while ts < t + 1.0:
        rec.on_data(syn.pow_sample(ts))
        if k % 2 == 0:
            rec.on_data(syn.fac_sample(ts))
        if k % 4 == 0:
            rec.on_data(syn.dev_sample(ts))
        ts += step
        k += 1
    rec.meta["completed"] = True
    rec.close()
    return folder


def base_meta(a: argparse.Namespace, cfg: Config, source: str) -> dict:
    return {
        "test": "seq_flicker_feasibility",
        "source": source,
        "synthetic_effect_sd": a.effect if a.synthetic else None,
        "subject": a.subject,
        "started": dt.datetime.now().isoformat(timespec="seconds"),
        "config": cfg.to_dict(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "completed": False,
    }


# ---------------------------------------------------------------- GUI path


class Runner:
    """Frame-locked stimulus. One draw + one vsync'd flip per loop."""

    def __init__(self, a: argparse.Namespace, cfg: Config) -> None:
        import pyglet

        self.pyglet = pyglet
        self.a, self.cfg = a, cfg
        self.blocks = build_protocol(cfg)
        self.folder = session_folder(a)
        self.quit = False
        self.aborted = False

        # Signal source first: connecting to Cortex can block for a minute or more
        # (app approval, headset scan). Doing it before the window exists keeps the
        # window from sitting frozen, and keeps Launcher pop-ups from stealing focus
        # from a fullscreen window.
        self.syn = None
        if a.synthetic:
            from synthetic import SyntheticStreams

            self.syn = SyntheticStreams(effect_sd=a.effect)
            cols = self.syn.cols
            self.rec = Recorder(self.folder, cols, base_meta(a, cfg, "synthetic"))
            threading.Thread(target=self._synthetic_pump, daemon=True).start()
            self.client = None
        else:
            from cortex_client import CortexClient

            cid, secret = os.environ.get("EMOTIV_CLIENT_ID"), os.environ.get("EMOTIV_CLIENT_SECRET")
            if not cid or not secret:
                sys.exit("Set EMOTIV_CLIENT_ID and EMOTIV_CLIENT_SECRET in the repo's .env")
            self.rec = None
            self._buffer: list[dict] = []
            log("Connecting to the EMOTIV Launcher (Cortex)...")
            self.client = CortexClient(cid, secret, on_data=self._on_cortex, log=log)
            self.client.connect()
            cols = self.client.start(STREAMS, headset_id=a.headset)
            self.rec = Recorder(self.folder, cols, base_meta(a, cfg, "emotiv"))
            self.rec.meta["headset_id"] = self.client.headset_id
            self.rec.write_meta()

        disp_mod = getattr(pyglet, "display", None) or pyglet.canvas
        screens = disp_mod.get_display().get_screens()
        screen = screens[min(a.screen, len(screens) - 1)]
        log(f"Opening the stimulus window on screen {a.screen} ({len(screens)} found)...")
        self.win = pyglet.window.Window(
            fullscreen=not a.windowed,
            width=None if not a.windowed else 1600,
            height=None if not a.windowed else 900,
            vsync=not a.no_vsync,
            screen=screen,
            caption="Flick — sequential flicker test",
        )
        self.win.set_mouse_visible(True)
        self.win.push_handlers(
            on_key_press=self.on_key, on_mouse_press=self.on_mouse, on_close=self.on_close
        )
        self.batch = pyglet.graphics.Batch()
        self._build_scene()

        # State machine
        self.state = "measure"
        self.frame_times: list[float] = []
        self.refresh_hz = 60.0
        self.block_i = -1
        self.seg_i = 0
        self.seg_start: float | None = None
        self.seg_onset_wall = 0.0
        self.seg_frames = 0
        self.seg_drops = 0
        self.countdown_end = 0.0
        self.last_flip: float | None = None
        self.measure_started: float | None = None
        self._next_ui = 0.0
        self.title.text = "Measuring display refresh..."
        self._show_button(None)
        self._set_marker(None, show=False)
        log("Measuring display refresh (about 3 s)...")

    # --- scene ------------------------------------------------------------

    def _build_scene(self) -> None:
        pg, cfg, w, h = self.pyglet, self.cfg, self.win.width, self.win.height
        shapes, text = pg.shapes, pg.text
        n, px, gap = cfg.n_tiles, cfg.tile_px, cfg.tile_gap_px
        row_w = n * px + (n - 1) * gap
        x0, y0 = (w - row_w) // 2, (h - px) // 2 - 40
        self.tiles, self.tile_centres, self.numbers = [], [], []
        for i in range(n):
            x = x0 + i * (px + gap)
            self.tiles.append(
                shapes.Rectangle(x, y0, px, px, color=(128, 128, 128), batch=self.batch)
            )
            self.tile_centres.append((x + px // 2, y0 + px // 2))
            self.numbers.append(
                text.Label(
                    str(i + 1),
                    font_size=28,
                    x=x + px // 2,
                    y=y0 - 40,
                    anchor_x="center",
                    anchor_y="center",
                    color=(170, 170, 170, 255),
                    batch=self.batch,
                )
            )
        self.dot = shapes.Circle(0, 0, 9, color=(220, 30, 30), batch=self.batch)
        cx, cy = w // 2, y0 + px + 130
        self.cross = [
            shapes.Rectangle(cx - 22, cy - 3, 44, 6, color=(230, 230, 230), batch=self.batch),
            shapes.Rectangle(cx - 3, cy - 22, 6, 44, color=(230, 230, 230), batch=self.batch),
        ]
        self.title = text.Label(
            "",
            font_size=30,
            x=w // 2,
            y=h - 90,
            anchor_x="center",
            anchor_y="center",
            color=(255, 255, 255, 255),
            batch=self.batch,
        )
        self.body = text.Label(
            "",
            font_size=17,
            x=w // 2,
            y=h - 150,
            width=int(w * 0.7),
            multiline=True,
            anchor_x="center",
            anchor_y="top",
            align="center",
            color=(210, 210, 210, 255),
            batch=self.batch,
        )
        bw, bh = 280, 80
        self.btn_box = (w // 2 - bw // 2, 70, bw, bh)
        self.btn = shapes.Rectangle(*self.btn_box, color=(30, 140, 70), batch=self.batch)
        self.btn_label = text.Label(
            "START",
            font_size=26,
            x=w // 2,
            y=70 + bh // 2,
            anchor_x="center",
            anchor_y="center",
            color=(255, 255, 255, 255),
            batch=self.batch,
        )
        self.footer = text.Label(
            "", font_size=12, x=20, y=20, color=(90, 90, 90, 255), batch=self.batch
        )

    def _show_button(self, label: str | None) -> None:
        self.btn.visible = label is not None
        self.btn_label.text = label or ""

    def _set_marker(self, target: int | None, show: bool = True) -> None:
        self.dot.visible = show and target is not None
        for c in self.cross:
            c.visible = show and target is None
        if target is not None:
            self.dot.x, self.dot.y = self.tile_centres[target]

    # --- input ------------------------------------------------------------

    def on_key(self, symbol, modifiers):
        key = self.pyglet.window.key
        if symbol == key.ESCAPE:
            self.aborted = self.state not in ("done",)
            self.quit = True
            return True
        if symbol in (key.SPACE, key.ENTER):
            self._advance()
        return True

    def on_mouse(self, x, y, button, modifiers):
        bx, by, bw, bh = self.btn_box
        if self.btn.visible and bx <= x <= bx + bw and by <= y <= by + bh:
            self._advance()

    def on_close(self):
        self.aborted = self.state != "done"
        self.quit = True
        return True

    def _advance(self) -> None:
        if self.state == "start":
            self._next_block()
        elif self.state == "intro":
            self.state = "countdown"
            self.countdown_end = time.perf_counter() + self.cfg.countdown_s
        elif self.state == "done":
            self.quit = True

    # --- signal -----------------------------------------------------------

    def _on_cortex(self, data: dict) -> None:
        if self.rec:
            self.rec.on_data(data)

    def _synthetic_pump(self) -> None:
        from synthetic import POW_HZ

        k = 0
        while not self.quit:
            t = time.time()
            self.rec.on_data(self.syn.pow_sample(t))
            if k % 2 == 0:
                self.rec.on_data(self.syn.fac_sample(t))
            if k % 4 == 0:
                self.rec.on_data(self.syn.dev_sample(t))
            k += 1
            time.sleep(1.0 / POW_HZ)

    def _contact_text(self) -> str:
        dev = self.rec.latest.get("dev") if self.rec else None
        if not dev:
            return "Headset contact: waiting for data..."
        cols = (self.client.cols if self.client else self.syn.cols).get("dev", [])
        names = next((c for c in cols if isinstance(c, list)), [])
        values = next((v for v in dev["dev"] if isinstance(v, list)), [])
        q = dict(zip(names, values, strict=False))
        o1, o2 = q.get("O1"), q.get("O2")
        ok = all(isinstance(v, (int, float)) and v >= 3 for v in (o1, o2))
        batt = dev["dev"][-1]
        verdict = "OK" if ok else "FIX CONTACT FIRST (rehydrate / reseat O1, O2)"
        return f"Contact O1={o1}  O2={o2}  (need 3-4)  battery {batt}%  -> {verdict}"

    # --- flow -------------------------------------------------------------

    def _next_block(self) -> None:
        self.block_i += 1
        if self.block_i >= len(self.blocks):
            self._finish()
            return
        b = self.blocks[self.block_i]
        log(f"Block {b.name}: waiting for SPACE")
        self.state = "intro"
        self.title.text = b.title
        self.body.text = (
            b.instruction + f"\n\nAbout {b.duration_s / 60:.1f} min. "
            "Press SPACE or click CONTINUE when ready."
        )
        self._show_button("CONTINUE")
        self._set_marker(b.target)
        self._tiles_static()

    def _start_segments(self) -> None:
        self.state = "running"
        self.title.text = ""
        self.body.text = ""
        self._show_button(None)
        self.seg_i = 0
        self._begin_segment()

    def _begin_segment(self) -> None:
        self.seg_start = None  # set on the first flip of this segment
        self.seg_frames = 0
        self.seg_drops = 0

    def _end_segment(self, now: float) -> None:
        b = self.blocks[self.block_i]
        seg = b.segments[self.seg_i]
        self.rec.event(
            t_wall=self.seg_onset_wall,
            block=seg.block,
            phase=seg.phase,
            target=seg.target,
            active_tile=seg.active_tile,
            flicker_all=int(seg.flicker_all),
            cycle=seg.cycle,
            slot_pos=seg.slot_pos,
            planned_s=seg.duration_s,
            actual_s=round(now - self.seg_start, 4),
            frames=self.seg_frames,
            dropped_frames=self.seg_drops,
        )
        self.seg_i += 1
        if self.seg_i >= len(b.segments):
            self._next_block()
        else:
            self._begin_segment()

    def _finish(self) -> None:
        self.state = "done"
        log("All blocks finished.")
        self.rec.meta["completed"] = True
        self.title.text = "Done — thank you"
        self.body.text = "Data saved. Press SPACE to close and see the analysis."
        self._show_button("CLOSE")
        self._set_marker(None, show=False)
        self._tiles_static()

    def _tiles_static(self) -> None:
        for t in self.tiles:
            t.color = (128, 128, 128)

    def _lum(self, t: float) -> int:
        """Luminance at t seconds into the segment. Time-based rather than
        frame-counted, so the flicker stays at flicker_hz even if a frame is
        dropped. At a steady 165 Hz the two are identical."""
        c, f = self.cfg.contrast, self.cfg.flicker_hz
        v = 0.5 * (1 + c * math.sin(2 * math.pi * f * t))
        return max(0, min(255, round(255 * v)))

    # --- per frame --------------------------------------------------------

    def update(self, now: float) -> None:
        if self.state == "measure":
            nf = len(self.frame_times)
            if self.measure_started is None and nf:
                self.measure_started = now
            elapsed = now - self.measure_started if self.measure_started else 0.0
            if now >= self._next_ui:
                self.body.text = f"{nf} frames in {elapsed:.1f} s"
                self._next_ui = now + 0.25
            done = nf >= MEASURE_FRAMES or (elapsed >= MEASURE_MAX_S and nf >= 40)
            if elapsed >= MEASURE_MAX_S and nf < 40:
                log(
                    f"Only {nf} frames in {elapsed:.0f} s: the window is not being drawn. "
                    "See README troubleshooting."
                )
                self.measure_started = now  # keep trying, report again
            if done:
                ft = self.frame_times[min(60, nf // 5) :]
                iv = [b - a for a, b in zip(ft[:-1], ft[1:], strict=True)]
                self.refresh_hz = 1.0 / statistics.median(iv)
                fpc = self.refresh_hz / self.cfg.flicker_hz
                exact = abs(fpc - round(fpc)) < 0.01 * fpc
                self.rec.meta.update(
                    measured_refresh_hz=round(self.refresh_hz, 2),
                    frames_per_cycle=round(fpc, 3),
                    exact=exact,
                )
                self.rec.write_meta()
                log(
                    f"Display: {self.refresh_hz:.1f} Hz from {nf} frames, "
                    f"{fpc:.2f} frames per flicker cycle (exact={exact})"
                )
                self.state = "start"
                self.title.text = "Flick — sequential flicker test"
                warn = (
                    ""
                    if exact
                    else (
                        f"\nWARNING: {fpc:.2f} frames per cycle is not a whole number. "
                        "Set the display to 165 Hz and restart."
                    )
                )
                self.start_head = (
                    "PHOTOSENSITIVITY WARNING: this test shows flickering lights at "
                    f"{self.cfg.flicker_hz:g} Hz. Do not take part if you or your family have a "
                    "history of seizures or epilepsy. Stop at any time with ESC.\n\n"
                    f"Display: {self.refresh_hz:.1f} Hz  ->  {fpc:.2f} frames per flicker "
                    f"cycle{warn}\n"
                    f"Total time about {total_duration_s(self.cfg) / 60:.0f} min plus breaks.\n\n"
                )
                self._next_contact = now + 0.5
                if self.refresh_hz < MIN_FPS:
                    self.state = "blocked"
                    self.title.text = "This window is drawing too slowly for the test"
                    self.body.text = (
                        f"Measured {self.refresh_hz:.1f} frames per second; a smooth "
                        f"{self.cfg.flicker_hz:g} Hz flicker needs at least {MIN_FPS}.\n\n"
                        "Close this window (ESC) and run:  python check_display.py\n"
                        "It tries four settings and tells you which one to use."
                    )
                    self._show_button(None)
                    log(
                        f"Blocked: {self.refresh_hz:.1f} fps is below {MIN_FPS}. "
                        "Run python check_display.py"
                    )
                    return
                self.body.text = self.start_head + self._contact_text()
                self._show_button("START")
            return
        if self.state == "start" and now >= self._next_contact:
            self.body.text = self.start_head + self._contact_text()
            self._next_contact = now + 0.5
        if self.state == "countdown":
            left = self.countdown_end - now
            self.title.text = f"{max(0, math.ceil(left))}"
            self.body.text = ""
            self._show_button(None)
            if left <= 0:
                self._start_segments()
            return
        if self.state == "running":
            b = self.blocks[self.block_i]
            seg = b.segments[self.seg_i]
            if (
                self.seg_start is not None
                and (now - self.seg_start) + 0.5 / self.refresh_hz >= seg.duration_s
            ):
                self._end_segment(now)
                if self.state != "running":
                    return
                seg = b.segments[self.seg_i]
            # Time of the frame being drawn: one frame after the last flip.
            t_seg = 0.0 if self.seg_start is None else now - self.seg_start + 1.0 / self.refresh_hz
            for i, tile in enumerate(self.tiles):
                on = (seg.phase == "sanity_on") or (seg.phase == "slot" and i == seg.active_tile)
                v = self._lum(t_seg) if on else 128
                tile.color = (v, v, v)
            self.footer.text = (
                f"{b.name}  cycle {seg.cycle + 1}" if seg.cycle is not None else b.name
            )

    def after_flip(self, t: float) -> None:
        if (
            self.last_flip is not None
            and self.state == "running"
            and t - self.last_flip > 1.5 / self.refresh_hz
        ):
            self.seg_drops += 1
        self.last_flip = t
        if self.state == "measure":
            self.frame_times.append(t)
        if self.state == "running":
            if self.seg_start is None:
                self.seg_start = t
                self.seg_onset_wall = time.time()
                b = self.blocks[self.block_i]
                seg = b.segments[self.seg_i]
                if self.syn:
                    self.syn.add_segment(
                        self.seg_onset_wall, self.seg_onset_wall + seg.duration_s, seg
                    )
            self.seg_frames += 1

    def loop(self) -> Path:
        try:
            while not self.quit:
                self.win.dispatch_events()
                self.update(time.perf_counter())
                self.win.clear()
                self.batch.draw()
                self.win.flip()
                self.after_flip(time.perf_counter())
        finally:
            self.rec.meta["aborted"] = self.aborted
            self.rec.close()
            if self.client:
                self.client.close()
            self.win.close()
        return self.folder


# -------------------------------------------------------------------- main


def main() -> None:
    a = parse_args()
    load_env(HERE.parent.parent / ".env")
    cfg = make_config(a)
    folder = run_headless(a, cfg) if a.headless else Runner(a, cfg).loop()
    print(f"\nSession saved to {folder}")
    from analyze import analyze

    try:
        print(analyze(folder))
    except (SystemExit, Exception) as e:  # an early close leaves too little data
        print(f"Analysis skipped: {e}")


if __name__ == "__main__":
    main()
