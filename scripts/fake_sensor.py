"""scripts/fake_sensor.py — a synthetic EEG publisher for dashboard development.

Standalone process, not part of the sensor package (sensor/ is out of
scope for this build). It publishes bci.eeg (~4 Hz), bci.psd (~4 Hz),
bci.scores (4 Hz), bci.selection (event, on dwell) and bci.status
(1 Hz) on ZMQ 5555, at the rates given in ARCHITECTURE.md section 6.2,
so the judge dashboard's plots can be built and demonstrated before
any OpenBCI hardware exists. Publishing bci.selection closes the loop
for inputs/ssvep.py: it subscribes to stim.show_targets on 5556 (the
same port the real P1 sensor listens on, per the section 3.2 process
table) to learn the current trial_id, so a genuine dwell completion
here produces something inputs/ssvep.py can actually consume end to
end, with no hardware in the loop.

The generated EEG is pink noise plus a slow-modulated 10 Hz alpha
bump, 60 Hz line noise and Poisson blink artifacts, matching the
qualitative shape of the synthetic source described in
ARCHITECTURE.md section 8.4 (that source lives in the out-of-scope
sensor/ package; this script is an independent re-creation of the
same idea for a standalone dev tool). When a target is "attended", a
multi-harmonic sinusoid at that target's frequency is injected and
ramped in over 400 ms, exactly as section 8.4 specifies. The PSD and
correlation scores this script publishes are computed for real from
that generated waveform via Welch's method and a sinusoid-correlation
projection, not invented numbers -- but the waveform itself is
synthetic.

THIS IS A DEVELOPMENT TOOL. It must never be presented as real data
(AGENTS.md non-negotiable #2, ARCHITECTURE.md DEMO-3).

Usage:
    uv run python scripts/fake_sensor.py
    uv run python scripts/fake_sensor.py --profile lo --attended 2

While running, type a digit 0-4 and press Enter to set the attended
target index, or just press Enter (empty line) to clear it back to
idle. Ctrl+C to stop.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

import numpy as np
from scipy.signal import butter, filtfilt, iirnotch, lfilter, sosfiltfilt, welch

# Allow running as `python scripts/fake_sensor.py` from the repo root
# without installing the project as a package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import ValidationError  # noqa: E402

from shared.bus import Publisher, Subscriber  # noqa: E402
from shared.config import AppConfig, StimulusProfileSpec, load_config  # noqa: E402
from shared.logging import configure_logging, get_logger  # noqa: E402
from shared.schemas import (  # noqa: E402
    EegChunk,
    PsdFrame,
    SensorSelection,
    SensorStatus,
    ShowTargets,
    TargetScores,
)

logger = get_logger(__name__)

# --------------------------------------------------------------------------
# Synthetic signal constants, matching ARCHITECTURE.md section 8.4.
# These describe *this dev tool's* signal generator, not a stimulus
# frequency, window length or sub-band edge -- those all come from
# the active config.yaml profile below (AGENTS.md section 7.2).
# --------------------------------------------------------------------------

PINK_NOISE_RMS_UV = 15.0
ALPHA_FREQ_HZ = 10.0
ALPHA_AMPLITUDE_UV = 8.0
LINE_NOISE_FREQ_HZ = 60.0
LINE_NOISE_AMPLITUDE_UV = 20.0
SSVEP_RAMP_S = 0.4
SSVEP_TARGET_AMPLITUDE_UV = 3.0
BLINK_RATE_PER_S = 1.0 / 8.0
BLINK_DURATION_S = 0.3
BLINK_AMPLITUDE_UV = 80.0
N_HARMONICS = 3

# Per-channel gain for injected SSVEP and blink artifacts, in channel
# order [O1, Oz, O2, POz, PO3, PO4, Pz, CPz] (config.eeg.channel_names).
SSVEP_CHANNEL_GAIN = np.array([1.0, 1.0, 1.0, 1.0, 0.7, 0.7, 0.4, 0.4])
BLINK_CHANNEL_GAIN = np.array([0.3, 0.3, 0.3, 0.5, 0.5, 0.5, 0.8, 0.8])

# Pink-noise shaping filter (Kasdin's approximation of a 1/f filter).
_PINK_B = np.array([0.049922035, -0.095993537, 0.050612699, -0.004408786])
_PINK_A = np.array([1.0, -2.494956002, 2.017265875, -0.522189400])


class AttendedTarget:
    """Thread-safe holder for the currently attended target index."""

    def __init__(self, initial: int | None) -> None:
        self._lock = threading.Lock()
        self._value = initial
        self._changed_at = time.monotonic()

    def set(self, value: int | None) -> None:
        with self._lock:
            if value != self._value:
                self._value = value
                self._changed_at = time.monotonic()

    def get(self) -> tuple[int | None, float]:
        """Return (index, seconds_since_last_change)."""
        with self._lock:
            return self._value, time.monotonic() - self._changed_at


def _resolve_profile(config: AppConfig, override: str | None) -> tuple[str, StimulusProfileSpec]:
    name = override or config.stimulus.profile
    if name not in ("hi", "lo"):
        name = "hi"  # "auto" has no real display to measure here; default hi
    return name, getattr(config.stimulus.profiles, name)


class SignalGenerator:
    """Generates one continuous multi-channel synthetic EEG stream."""

    def __init__(self, n_channels: int, fs: int, rng: np.random.Generator) -> None:
        self.n_channels = n_channels
        self.fs = fs
        self._rng = rng
        self._sample_idx = 0
        self._pink_zi = np.zeros((n_channels, max(len(_PINK_A), len(_PINK_B)) - 1))
        self._alpha_walk = np.zeros(n_channels)
        self._next_blink_at_s = self._rng.exponential(1.0 / BLINK_RATE_PER_S)
        self._blink_remaining_samples = 0

    def generate(
        self,
        n_samples: int,
        profile: StimulusProfileSpec,
        attended: int | None,
        attended_age_s: float,
    ) -> np.ndarray:
        """Return an (n_channels, n_samples) microvolt array."""
        t0 = self._sample_idx / self.fs
        t = t0 + np.arange(n_samples) / self.fs

        white = self._rng.normal(0.0, 1.0, size=(self.n_channels, n_samples))
        pink = np.empty_like(white)
        for ch in range(self.n_channels):
            filtered, self._pink_zi[ch] = _lfilter_with_state(
                _PINK_B, _PINK_A, white[ch], self._pink_zi[ch]
            )
            pink[ch] = filtered
        pink *= PINK_NOISE_RMS_UV / (np.std(pink) + 1e-9)

        self._alpha_walk += self._rng.normal(0.0, 0.05, size=self.n_channels)
        self._alpha_walk = np.clip(self._alpha_walk, -0.5, 0.5)
        alpha_gain = (1.0 + self._alpha_walk)[:, None]
        alpha = ALPHA_AMPLITUDE_UV * alpha_gain * np.sin(2 * np.pi * ALPHA_FREQ_HZ * t)[None, :]

        line = LINE_NOISE_AMPLITUDE_UV * np.sin(2 * np.pi * LINE_NOISE_FREQ_HZ * t)[None, :]

        ssvep = np.zeros((self.n_channels, n_samples))
        if attended is not None:
            freq = profile.frequencies[attended]
            phase = profile.phases[attended]
            ramp = min(1.0, attended_age_s / SSVEP_RAMP_S)
            amplitude = SSVEP_TARGET_AMPLITUDE_UV * ramp
            harmonic_sum = np.zeros(n_samples)
            for h in range(1, N_HARMONICS + 1):
                harmonic_sum += (1.0 / h) * np.sin(2 * np.pi * h * freq * t + h * phase)
            ssvep = amplitude * SSVEP_CHANNEL_GAIN[:, None] * harmonic_sum[None, :]

        blink = self._generate_blink(n_samples)

        self._sample_idx += n_samples
        return pink + alpha + line + ssvep + blink

    def _generate_blink(self, n_samples: int) -> np.ndarray:
        out = np.zeros((self.n_channels, n_samples))
        remaining_before_block = self._next_blink_at_s
        block_duration_s = n_samples / self.fs

        if self._blink_remaining_samples > 0:
            n = min(self._blink_remaining_samples, n_samples)
            envelope = np.hanning(2 * int(BLINK_DURATION_S * self.fs))
            start = len(envelope) - self._blink_remaining_samples
            start = max(start, 0)
            out[:, :n] += (
                BLINK_AMPLITUDE_UV * BLINK_CHANNEL_GAIN[:, None] * envelope[start : start + n]
            )
            self._blink_remaining_samples -= n

        if remaining_before_block <= block_duration_s and self._blink_remaining_samples == 0:
            onset_sample = max(0, int(remaining_before_block * self.fs))
            duration_samples = int(BLINK_DURATION_S * self.fs)
            envelope = np.hanning(duration_samples)
            n = min(duration_samples, n_samples - onset_sample)
            if n > 0:
                out[:, onset_sample : onset_sample + n] += (
                    BLINK_AMPLITUDE_UV * BLINK_CHANNEL_GAIN[:, None] * envelope[:n]
                )
            self._blink_remaining_samples = max(0, duration_samples - n)
            self._next_blink_at_s = self._rng.exponential(1.0 / BLINK_RATE_PER_S)
        else:
            self._next_blink_at_s -= block_duration_s

        return out


def _lfilter_with_state(
    b: np.ndarray, a: np.ndarray, x: np.ndarray, zi: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    y, zf = lfilter(b, a, x, zi=zi)
    return y, zf


def _apply_filters(
    buffer: np.ndarray,
    fs: int,
    notch_hz: float,
    notch_q: float,
    low_hz: float,
    high_hz: float,
    order: int,
) -> np.ndarray:
    """Notch then bandpass, zero-phase, matching sensor/dsp.py's real pipeline."""
    b_notch, a_notch = iirnotch(notch_hz, notch_q, fs=fs)
    sos_band = butter(order, [low_hz, high_hz], btype="bandpass", fs=fs, output="sos")
    filtered = filtfilt(b_notch, a_notch, buffer, axis=-1)
    filtered = sosfiltfilt(sos_band, filtered, axis=-1)
    return filtered


def _compute_psd(
    buffer: np.ndarray, fs: int, freq_hi_hz: float = 48.0
) -> tuple[list[float], list[float]]:
    """Welch PSD, occipital mean across channels, in dB, 0.5 Hz bins."""
    mean_signal = buffer.mean(axis=0)
    nperseg = min(len(mean_signal), fs * 2)
    freqs, power = welch(mean_signal, fs=fs, nperseg=nperseg)
    mask = freqs <= freq_hi_hz
    freqs, power = freqs[mask], power[mask]
    target_freqs = np.arange(0.0, freq_hi_hz + 0.5, 0.5)
    power_interp = np.interp(target_freqs, freqs, power)
    power_db = 10 * np.log10(power_interp + 1e-12)
    return target_freqs.tolist(), power_db.tolist()


def _compute_rho(buffer: np.ndarray, fs: int, frequencies: list[float]) -> np.ndarray:
    """Correlation between the signal and a reference sinusoid per target.

    A real (not fabricated) magnitude-normalised projection onto
    sin/cos at each candidate frequency -- a simplified single-band
    stand-in for the real FBCCA classifier, which lives in the
    out-of-scope sensor/ package. The real multi-harmonic, multi-
    subband CCA is far more frequency-selective than this single dot
    product; a fixed narrow notch at the alpha nuisance frequency
    keeps this simplified proxy from reading a false-high correlation
    on whichever *other* target sits nearest to it, so the idle state
    reads below threshold everywhere except possibly the target that
    coincides with alpha itself. The lo profile deliberately parks
    its Cancel tile at 10.0 Hz for exactly this reason (section 9.2):
    "the tile whose false positive is harmless." So the notch is
    skipped for whichever target sits on alpha, rather than muting
    the very frequency a genuine selection would need to raise.
    """
    raw_signal = buffer.mean(axis=0)
    b_alpha, a_alpha = iirnotch(ALPHA_FREQ_HZ, 8.0, fs=fs)
    denoised_signal = filtfilt(b_alpha, a_alpha, raw_signal)
    n = len(raw_signal)
    t = np.arange(n) / fs

    rho = np.zeros(len(frequencies))
    for k, f in enumerate(frequencies):
        on_alpha = abs(f - ALPHA_FREQ_HZ) < 0.3
        signal = raw_signal if on_alpha else denoised_signal
        signal = signal - signal.mean()
        signal_norm = np.linalg.norm(signal) + 1e-9
        ref_sin = np.sin(2 * np.pi * f * t)
        ref_cos = np.cos(2 * np.pi * f * t)
        corr_sin = np.dot(signal, ref_sin) / (signal_norm * np.linalg.norm(ref_sin) + 1e-9)
        corr_cos = np.dot(signal, ref_cos) / (signal_norm * np.linalg.norm(ref_cos) + 1e-9)
        rho[k] = np.clip(np.sqrt(corr_sin**2 + corr_cos**2) / np.sqrt(2), 0.0, 1.0)
    return rho


class DwellTracker:
    """Mirrors the decision state machine's dwell counter (section 8.5).

    Drives bci.scores.dwell_count the way the real classifier's would,
    for dashboard development, and also reports when a dwell actually
    completes (fired=True) so the caller can emit a real bci.selection
    for it -- this is the one place fake_sensor's simulated decision
    state machine "fires" a selection, per section 8.5's
    DWELL(w, dwell_windows) -> emit Selection -> REFRACTORY.
    """

    def __init__(self, rho_threshold: float, margin_ratio: float, dwell_windows: int) -> None:
        self._rho_threshold = rho_threshold
        self._margin_ratio = margin_ratio
        self._dwell_windows = dwell_windows
        self._winner: int | None = None
        self._count = 0

    def update(self, rho: np.ndarray) -> tuple[int, float, bool, int, bool]:
        order = np.argsort(rho)[::-1]
        winner_idx = int(order[0])
        second_best = float(rho[order[1]]) if len(order) > 1 else 0.0
        margin = float(rho[winner_idx]) / (second_best + 1e-9)
        above_threshold = bool(rho[winner_idx] >= self._rho_threshold)
        margin_ok = margin >= self._margin_ratio

        if above_threshold and margin_ok and winner_idx == self._winner:
            self._count += 1
        elif above_threshold and margin_ok:
            self._winner = winner_idx
            self._count = 1
        else:
            self._winner = None
            self._count = 0

        fired = self._count >= self._dwell_windows
        if fired:
            self._count = 0
            self._winner = None

        return winner_idx, margin, above_threshold, self._count, fired


def build_sensor_selection(
    trial_id: str, winner_idx: int, rho: np.ndarray, margin: float, ts: float
) -> SensorSelection:
    """The bci.selection event a real P1 would emit on dwell completion.

    Factored out so both main()'s loop and tests build it the same
    way (section 6.2). algorithm is fixed at "fbcca" here for the
    same reason bci.scores is: fake_sensor has no calibration file to
    make eTRCA a real choice.
    """
    return SensorSelection(
        type="bci.selection",
        ts=ts,
        trial_id=trial_id,
        target_idx=winner_idx,
        rho=float(rho[winner_idx]),
        margin=margin,
        algorithm="fbcca",
    )


class TrialTracker:
    """Learns the current trial_id from stim.show_targets on ZMQ 5556.

    Mirrors how the real P1 sensor subscribes to P3's outbound 5556
    channel (section 3.2) to know what trial is on screen. Cleared
    once a selection has been emitted for it, so a later dwell with
    no fresh show_targets in between has nothing stale to attach to.
    """

    def __init__(self, address: str) -> None:
        self._subscriber = Subscriber(address)
        self._current_trial_id: str | None = None

    def poll(self) -> None:
        while self._subscriber.poll(timeout_ms=0):
            try:
                show_targets = self._subscriber.recv_as(ShowTargets)
            except ValidationError:
                logger.warning("fake_sensor.malformed_show_targets_dropped")
                continue
            self._current_trial_id = show_targets.trial_id

    @property
    def current_trial_id(self) -> str | None:
        return self._current_trial_id

    def clear(self) -> None:
        self._current_trial_id = None

    def close(self) -> None:
        self._subscriber.close()


def _read_keyboard_control(attended: AttendedTarget, n_targets: int) -> None:
    """Background thread: read digits from stdin to set the attended target."""
    print(f"Type 0-{n_targets - 1} + Enter to attend a target, empty line for idle.")
    for line in sys.stdin:
        text = line.strip()
        if text == "":
            attended.set(None)
            print("attended: idle")
            continue
        try:
            idx = int(text)
        except ValueError:
            print(f"ignored: {text!r} is not a digit")
            continue
        if 0 <= idx < n_targets:
            attended.set(idx)
            print(f"attended: target {idx}")
        else:
            print(f"ignored: {idx} out of range 0-{n_targets - 1}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    parser.add_argument("--address", default="tcp://127.0.0.1:5555", help="ZMQ PUB bind address")
    parser.add_argument(
        "--stim-address",
        default="tcp://127.0.0.1:5556",
        help="ZMQ SUB address for stim.show_targets, to learn the current trial_id",
    )
    parser.add_argument(
        "--profile", choices=["hi", "lo"], default=None, help="override stim profile"
    )
    parser.add_argument("--attended", type=int, default=None, help="initial attended target index")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed, for reproducible demos")
    args = parser.parse_args()

    configure_logging()
    config = load_config(args.config)
    profile_name, profile = _resolve_profile(config, args.profile)
    fs = config.eeg.sample_rate
    n_channels = len(config.eeg.channel_names)
    hop_s = config.dsp.hop_s
    n_samples_per_hop = round(fs * hop_s)
    window_samples = round(profile.window_s * fs)

    rng = np.random.default_rng(args.seed)
    generator = SignalGenerator(n_channels, fs, rng)
    dwell = DwellTracker(
        config.decision.rho_threshold,
        config.decision.margin_ratio,
        config.decision.dwell_windows,
    )
    attended = AttendedTarget(args.attended)

    control_thread = threading.Thread(
        target=_read_keyboard_control,
        args=(attended, len(profile.frequencies)),
        daemon=True,
    )
    control_thread.start()

    trial_tracker = TrialTracker(args.stim_address)
    publisher = Publisher(args.address)
    logger.info(
        "fake_sensor.started",
        address=args.address,
        profile=profile_name,
        frequencies=profile.frequencies,
        badge="SYNTHETIC (DEV TOOL)",
    )

    ring_buffer = np.zeros((n_channels, window_samples))
    samples_received = 0
    tick = 0

    try:
        while True:
            tick_start = time.monotonic()
            attended_idx, attended_age_s = attended.get()

            chunk = generator.generate(n_samples_per_hop, profile, attended_idx, attended_age_s)
            ring_buffer = np.roll(ring_buffer, -n_samples_per_hop, axis=1)
            ring_buffer[:, -n_samples_per_hop:] = chunk
            samples_received += n_samples_per_hop

            filtered_buffer = _apply_filters(
                ring_buffer,
                fs,
                config.dsp.notch_hz,
                config.dsp.notch_q,
                profile.bandpass_low_hz,
                config.dsp.bandpass_high_hz,
                config.dsp.bandpass_order,
            )
            filtered_hop = filtered_buffer[:, -n_samples_per_hop:]

            now = time.time()
            publisher.send(
                EegChunk(
                    type="bci.eeg",
                    ts=now,
                    fs=fs,
                    channels=config.eeg.channel_names,
                    data=filtered_hop.tolist(),
                    railed=[False] * n_channels,
                )
            )

            freqs, power_db = _compute_psd(filtered_buffer, fs, config.dsp.bandpass_high_hz)
            peaks = [float(np.interp(f, freqs, power_db)) for f in profile.frequencies]
            publisher.send(
                PsdFrame(type="bci.psd", ts=now, freqs=freqs, power=power_db, peaks=peaks)
            )

            trial_tracker.poll()

            rho = _compute_rho(filtered_buffer, fs, profile.frequencies)
            winner_idx, margin, above_threshold, dwell_count, fired = dwell.update(rho)
            publisher.send(
                TargetScores(
                    type="bci.scores",
                    ts=now,
                    algorithm="fbcca",
                    rho=rho.tolist(),
                    winner_idx=winner_idx,
                    margin=margin,
                    above_threshold=above_threshold,
                    dwell_count=dwell_count,
                )
            )

            if fired and trial_tracker.current_trial_id is not None:
                publisher.send(
                    build_sensor_selection(
                        trial_tracker.current_trial_id, winner_idx, rho, margin, now
                    )
                )
                trial_tracker.clear()

            if tick % 4 == 0:
                publisher.send(
                    SensorStatus(
                        type="bci.status",
                        ts=now,
                        source="synthetic",
                        connected=True,
                        configured=True,
                        samples_received=samples_received,
                        dropped_samples=0,
                        railed_channels=[],
                    )
                )

            tick += 1
            elapsed = time.monotonic() - tick_start
            time.sleep(max(0.0, hop_s - elapsed))
    except KeyboardInterrupt:
        logger.info("fake_sensor.stopped")
    finally:
        publisher.close()
        trial_tracker.close()


if __name__ == "__main__":
    main()
