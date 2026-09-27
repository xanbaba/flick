# Sequential-flicker feasibility test

A standalone test for ARCHITECTURE.md §7.3 `seq_flicker`. It shows three tiles that flicker one at a time at 15 Hz, records Emotiv EPOC X band power, and scores whether the tile being looked at can be identified. The protocol, the reasoning and the pass/fail rules are in [TEST_PLAN.md](TEST_PLAN.md).

It depends on nothing else in the repo, so it can run before the rest of the sensor code exists.

## Setup (Windows, once)

Any Python 3.11 or newer works. From this folder, in PowerShell:

```powershell
python -m pip install -r requirements.txt
```

Use `python -m pip`, not bare `pip`: on PCs with more than one Python (for example python.org and Microsoft Store installs), bare `pip` can install into a different Python than the one `python` runs.

Add your Cortex app credentials to the repo's `.env` (never commit it):

```
EMOTIV_CLIENT_ID=...
EMOTIV_CLIENT_SECRET=...
```

## Run

```powershell
python run_test.py --subject zahid
```

1. The window opens fullscreen and measures the refresh rate (should read ~165 Hz, 11.00 frames per cycle).
2. Check the contact line: O1 and O2 need 3–4.
3. Click **START**, then follow the on-screen instructions. SPACE continues between blocks; ESC stops (data so far is kept).
4. When it finishes, the analysis prints and is saved as `sessions/<session>/report.md`.

Useful options: `--no-vsync` (if `check_display.py` says so), `--windowed`, `--screen 1` (stimulus on a second monitor), `--no-idle`, `--no-sanity`, `--cycles 10`, `--slot-s 4`, `--order fixed`.

## Troubleshooting

The console prints a timestamped line for each step: connecting to Cortex, opening the window, the measured refresh rate, and each block. If something stalls, the last line shows where.

- **Stuck on "Measuring display refresh", "drawing too slowly", or the whole window flickers.** The window is not being drawn at the display rate. Run `python check_display.py` first: it tries fullscreen/windowed × vsync on/off for 3 s each, prints frames per second and the OpenGL renderer, and says which setting to use (for example `--no-vsync`). Then, if needed:
  1. Windows Settings → System → Display → Graphics → add `python.exe` (the one `python -c "import sys; print(sys.executable)"` prints) → **High performance** (the NVIDIA GPU). Laptops with two GPUs often run Python on the integrated one.
  2. Plug in the charger and set the power mode to Best performance.
  3. `python run_test.py --synthetic --windowed` to check drawing works outside fullscreen.
- **Waiting on "Connecting to the EMOTIV Launcher".** Open the Launcher, log in, and approve the app when asked. The headset must be on and paired.
- **Display is not 165 Hz.** Settings → System → Display → Advanced display → refresh rate 165 Hz, then restart the test.

## Files

| File | What it does |
|---|---|
| `check_display.py` | Measures how fast this PC can draw the test window in four settings, and which GPU is drawing it. |
| `protocol.py` | The schedule: blocks, cycles, slot order. Shared by everything else. |
| `run_test.py` | Fullscreen pyglet stimulus, vsync-locked, frame-drop counting; start button; drives Cortex or the synthetic source. |
| `cortex_client.py` | Cortex JSON-RPC over `wss://localhost:6868`: requestAccess → authorize → headset → session → subscribe `pow`, `fac`, `dev`, `eq`. |
| `recorder.py` | Writes `meta.json`, `events.csv`, `pow.csv`, `fac.csv`, `dev.csv`, `eq.csv`. |
| `analyze.py` | Primary analysis plus controls and exploratory tables → `report.md`, `summary.json`. |
| `synthetic.py` | Fake Cortex-shaped streams for dry runs. |

Recorded sessions stay in `sessions/`, which is git-ignored (AGENTS.md: never commit recorded sessions).
