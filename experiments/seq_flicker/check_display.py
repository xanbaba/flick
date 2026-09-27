"""Display check: how fast can this PC draw the test window?

    python check_display.py

Tries four window settings for 3 seconds each (fullscreen / windowed,
vsync on / off), draws a flickering tile, and prints frames per second.
The sequential-flicker test needs a setting that reaches the panel's
refresh rate (165 on the target laptop) with steady frame times.
"""

from __future__ import annotations

import math
import statistics
import time

import pyglet


def gpu_info() -> str:
    try:
        from pyglet.gl import gl_info

        return f"{gl_info.get_vendor()} | {gl_info.get_renderer()} | GL {gl_info.get_version()}"
    except Exception as e:  # informational only
        return f"unknown ({e})"


def trial(fullscreen: bool, vsync: bool, seconds: float = 3.0) -> dict:
    kw = {"fullscreen": True} if fullscreen else {"width": 1280, "height": 720}
    win = pyglet.window.Window(vsync=vsync, caption="Flick display check", **kw)
    batch = pyglet.graphics.Batch()
    w, h = win.width, win.height
    tile = pyglet.shapes.Rectangle(w // 2 - 150, h // 2 - 150, 300, 300, batch=batch)
    label = pyglet.text.Label(
        f"fullscreen={fullscreen} vsync={vsync}",
        font_size=24,
        x=w // 2,
        y=h - 80,
        anchor_x="center",
        batch=batch,
    )
    del label
    renderer = gpu_info()
    times: list[float] = []
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        win.dispatch_events()
        v = round(127.5 * (1 + math.sin(2 * math.pi * 15.0 * (time.perf_counter() - t0))))
        tile.color = (v, v, v)
        win.clear()
        batch.draw()
        win.flip()
        times.append(time.perf_counter())
    win.close()
    iv = [b - a for a, b in zip(times[:-1], times[1:], strict=True)]
    fps = len(times) / seconds
    med = statistics.median(iv) if iv else float("nan")
    slow = sum(1 for x in iv if x > 1.5 * med) if iv else 0
    return {
        "fps": fps,
        "median_ms": med * 1000,
        "slow": slow,
        "frames": len(times),
        "renderer": renderer,
    }


def main() -> None:
    print("Checking display speed. Four short windows will open; don't touch anything.\n")
    rows = []
    for fs in (True, False):
        for vs in (True, False):
            r = trial(fs, vs)
            rows.append((fs, vs, r))
            print(
                f"fullscreen={fs!s:5}  vsync={vs!s:5}  ->  {r['fps']:7.1f} fps   "
                f"median frame {r['median_ms']:6.2f} ms   slow frames {r['slow']}"
            )
            time.sleep(0.5)
    print(f"\nOpenGL renderer: {rows[0][2]['renderer']}")
    print("\nWhat to look for:")
    print("- A vsync=True row near your refresh rate (165) is ideal: use that setting.")
    print("- If only vsync=False is fast, run the test with --no-vsync.")
    print("- If the renderer says Intel/AMD/Microsoft, set python.exe to High performance")
    print("  (Settings > System > Display > Graphics) and run this check again.")


if __name__ == "__main__":
    main()
