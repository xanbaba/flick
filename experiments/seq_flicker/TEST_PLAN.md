# Test plan — sequential flicker (Option 2)

**Question:** with an Emotiv EPOC X on the free Cortex tier (band power only), can we tell which of three tiles a person is looking at, when the tiles flicker one at a time?

**Decides:** whether `seq_flicker` (ARCHITECTURE.md §7.3) goes into the demo. This is the `seq_flicker` half of the feasibility gate (§7.6).

**Tool:** `experiments/seq_flicker/` — `run_test.py` shows the stimulus and records, `analyze.py` scores the session and prints a verdict.

---

## 1. Base design (Zahid's proposal)

- Three tiles in a row. One tile flickers at a time at **15 Hz**; the others stay still.
- The tiles flicker one after another, in the same order in every run.
- **Run 1:** the user looks only at tile 1 the whole time. **Run 2:** only tile 2. **Run 3:** only tile 3.
- Record the headset data and check how often the tile being looked at can be picked out.

## 2. Changes to the base design, and why

| # | Change | Why |
|---|---|---|
| 1 | **Each tile flickers for 4 s, with a 1 s still gap after it** | Cortex computes every band-power sample from the **last 2 seconds** of EEG. Only samples at least 2 s after a slot starts reflect that slot alone. A 4 s slot leaves 2 s (16 samples) of clean data per slot. A shorter slot leaves almost none. |
| 2 | **10 cycles per run** (every tile flickers 10 times per run) | 30 decisions in total. With chance at 33%, **15 of 30 correct** is needed to be statistically above chance (p < 0.05). If the true accuracy is 60%, 30 decisions detect it about 90% of the time; 24 would only do so about 79% of the time. |
| 3 | **The order is shuffled within each cycle, but identical in every run** | Keeps your "same order in every run", so the runs differ only in where the user looks. Shuffling within the cycle stops "tile 3 always comes last" from leaking into the result (e.g. attention drifting late in each cycle). |
| 4 | **30 s baseline first**: look at a cross, nothing flickers | Band power has no fixed scale. The analysis measures every value relative to the user's own resting level (a z-score). |
| 5 | **Signal check before the runs**: all tiles flicker together for 8 s, then stop, three times | If low-beta power doesn't rise even when everything flickers, the headset can't see the flicker at all. That points to sensor contact, not the idea, and saves you from misreading the main result. |
| 6 | **A 4th control run**: look at a cross above the tiles, not at any tile | Measures false selections when the user isn't choosing anything. The idle state must be real (UX-4). It also shows whether one tile "wins" just because of its position. |
| 7 | **Red fixation dot on the target tile** | Keeps the user's eyes on one spot. The dot never flickers. |
| 8 | **Still tiles are mid-grey; the flicker swings around mid-grey** | The screen's average brightness never changes, so the response comes from the flicker itself, not from a brightness jump. |
| 9 | **Photosensitivity warning and ESC to stop** | 15 Hz is inside the range that can trigger photosensitive seizures. Ask every participant first. |

## 3. Procedure

**Before (10 min)**

1. Display at **165 Hz** (Windows → Display → Advanced display). Plugged in, high-performance power mode. Close other GPU-heavy apps.
2. EMOTIV Launcher running and logged in. EPOC X on, saline sensors wet, **O1 and O2 contact green (3–4)**. The start screen shows the live contact values.
3. `EMOTIV_CLIENT_ID` and `EMOTIV_CLIENT_SECRET` in the repo's `.env` (Cortex app from the Emotiv developer site). On the first run, approve the app in the Launcher.
4. Seat the participant about 60 cm from the screen, eyes level with the tiles. Dim, steady room lighting.

**Run (about 12 min plus breaks)**

| Block | What the user does | Time |
|---|---|---|
| Baseline | Look at the cross, relax | 30 s |
| Signal check | Look at the dot on tile 2; everything flickers on and off | ~50 s |
| Run 1 | Look only at tile 1 | 2.5 min |
| Run 2 | Look only at tile 2 | 2.5 min |
| Run 3 | Look only at tile 3 | 2.5 min |
| Control | Look only at the cross | 2.5 min |

Each block starts with an instruction screen and waits for SPACE, so the user can rest between runs. Instructions to repeat every run: keep your eyes on the dot, even when another tile flickers; blink normally; keep your jaw and face relaxed.

**After**

The analysis runs automatically when the window closes and writes `report.md` into the session folder. To re-run it: `python analyze.py`.

## 4. Analysis (fixed in advance)

- **Feature:** low-beta (12–16 Hz) band power on O1 and O2, log-transformed, z-scored against the baseline, averaged over seconds 2.15–4.15 of each slot.
- **Prediction:** in each cycle, the tile with the highest score.
- **Main number:** accuracy over the 30 cycles of runs 1–3, one-sided binomial test against 33%.
- **Also reported:** signal-check result; confusion matrix; the idle rule's selections in the control run; accuracy when two cycles are averaged; accuracy excluding blinks; a time course of the response; and an exploratory table of other bands, sensors and lags.

**Exploratory numbers are not the result.** Picking the best of about 30 exploratory combinations will look good by chance. If one of them beats the primary feature, make it the new primary and test it in a **new** session.

## 5. Decision

| Outcome | Meaning | Next step |
|---|---|---|
| Signal check fails | The headset doesn't see the flicker at all | Fix O1/O2 contact and repeat. Don't judge the idea yet. |
| **≥ 60% and p < 0.05** | **GO** | Repeat once more (another day, or runs in reverse order 3→2→1). If it holds, build `seq_flicker` into the demo. |
| Above chance (p < 0.05) but < 60% | Promising, not demo-ready | Try two-cycle averaging, 5 s slots, or the best exploratory feature, in a new session. |
| p ≥ 0.05 | **NO-GO** | Use `scan_switch` (§7.3) as the selection method. Mention in the pitch that this was tested. |

The control run should produce 0–1 false selections out of 10. More than that means the idle state isn't reliable, even if accuracy passes.

## 6. Limitations to state honestly

- **Blocked runs.** The user looks at the same tile for a whole run, so "which tile" and "which run" can't be fully separated (fatigue, sensors drying out). The shuffled order and the control run reduce this, and the repeat in reverse order checks it.
- **One person, one session.** That shows feasibility, not general accuracy.
- **Cortex band power is a black box** (2 s windows, 8 Hz, fixed bands). A negative result means "not with free-tier band power", not "SSVEP doesn't work". With raw EEG, the same design would be scored with canonical correlation at 15 Hz (§8.7).

## 7. Dry run without the headset

```bash
python run_test.py --synthetic --headless            # pipeline check in seconds
python run_test.py --synthetic --headless --effect 0 # should come out near chance
python run_test.py --synthetic                       # full on-screen run, fake signal
```

Synthetic sessions are labelled as synthetic in `meta.json` and on the first line of the report. They test the code, not the idea.
