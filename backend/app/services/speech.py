"""VAD + STT orchestration (ARCHITECTURE.md section 15.1).

Continuous 16 kHz mono capture via sounddevice; VAD via webrtcvad
aggressiveness 2 (speech start after 3 consecutive voiced 30 ms
frames, end after 25 unvoiced frames / 750 ms silence). On speech end
the buffered segment goes to the STT provider chain as a batch call.
Utterances under 400 ms, or transcribing to fewer than two words, or
below confidence 0.5, are discarded as noise.

"The microphone must be hard-gated while the system is speaking. Not
a flag checked later — a gate in the capture callback." gate(True)
makes _on_audio() return before the frame ever reaches the VAD state
machine, so TTS output played over speakers can never loop back in as
a transcribed partner utterance.

No microphone hardware is assumed present (this is a CPU-only dev
box, same as everywhere else in this repo): start() degrades to a
no-op with a warning if sounddevice cannot open an input stream, per
SW-13. process_frame() is exposed separately so tests can drive the
VAD state machine with synthetic frames, with no audio device at all.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import webrtcvad

from backend.providers.base import Transcript
from backend.providers.registry import get_stt_provider
from shared.logging import get_logger

logger = get_logger(__name__)

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 480
VAD_AGGRESSIVENESS = 2
VOICED_START_FRAMES = 3
UNVOICED_END_FRAMES = 25  # 25 * 30ms = 750ms
MIN_UTTERANCE_MS = 400
MIN_WORDS = 2
MIN_CONFIDENCE = 0.5

TranscriptHandler = Callable[[Transcript], Awaitable[None] | None]


class SpeechService:
    def __init__(self, on_transcript: TranscriptHandler) -> None:
        self._on_transcript = on_transcript
        self._vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        self._gated = True  # gated until start(): never armed by default
        self._stream: object | None = None
        self._voiced_run = 0
        self._unvoiced_run = 0
        self._in_speech = False
        self._buffer = bytearray()
        self._loop: asyncio.AbstractEventLoop | None = None

    def gate(self, gated: bool) -> None:
        """Hard mic gate. Set True before TTS playback starts, False
        only after it finishes (orchestrator's SPEAKING state)."""
        self._gated = gated
        if gated:
            self._voiced_run = 0
            self._unvoiced_run = 0
            self._in_speech = False
            self._buffer.clear()

    @property
    def gated(self) -> bool:
        return self._gated

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._gated = False
        try:
            import sounddevice as sd
        except Exception as exc:
            logger.warning("speech.sounddevice_unavailable", error=str(exc))
            return
        try:
            stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                blocksize=FRAME_SAMPLES,
                dtype="int16",
                channels=1,
                callback=self._on_audio,
            )
            stream.start()
            self._stream = stream
        except Exception as exc:
            logger.warning("speech.mic_unavailable", error=str(exc))
            self._stream = None

    async def stop(self) -> None:
        self._gated = True
        if self._stream is not None:
            self._stream.stop()  # type: ignore[attr-defined]
            self._stream.close()  # type: ignore[attr-defined]
            self._stream = None

    def _on_audio(self, indata: object, frames: int, time_info: object, status: object) -> None:
        del frames, time_info, status
        self.process_frame(bytes(indata))  # type: ignore[call-overload]

    def process_frame(self, frame: bytes) -> None:
        """One 30 ms, 16 kHz, 16-bit mono PCM frame through the VAD state machine."""
        if self._gated:
            return  # the hard gate: dropped before VAD ever sees it

        is_speech = self._vad.is_speech(frame, SAMPLE_RATE)
        if is_speech:
            self._voiced_run += 1
            self._unvoiced_run = 0
        else:
            self._unvoiced_run += 1
            self._voiced_run = 0

        if not self._in_speech and self._voiced_run >= VOICED_START_FRAMES:
            self._in_speech = True
            self._buffer = bytearray()

        if not self._in_speech:
            return

        self._buffer.extend(frame)
        if self._unvoiced_run >= UNVOICED_END_FRAMES:
            self._in_speech = False
            segment = bytes(self._buffer)
            self._buffer = bytearray()
            self._schedule_segment(segment)

    def _schedule_segment(self, pcm: bytes) -> None:
        coro = self._handle_segment(pcm)
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        else:
            asyncio.ensure_future(coro)

    async def _handle_segment(self, pcm: bytes) -> None:
        duration_ms = (len(pcm) / 2) / SAMPLE_RATE * 1000
        if duration_ms < MIN_UTTERANCE_MS:
            logger.debug("speech.discarded_too_short", duration_ms=duration_ms)
            return

        stt = get_stt_provider()
        try:
            transcript = await stt.transcribe(pcm, SAMPLE_RATE)
        except Exception as exc:
            logger.warning("speech.transcribe_failed", error=str(exc))
            return

        word_count = len(transcript.text.split())
        if transcript.confidence < MIN_CONFIDENCE or word_count < MIN_WORDS:
            logger.debug(
                "speech.discarded_as_noise",
                confidence=transcript.confidence,
                word_count=word_count,
            )
            return

        result = self._on_transcript(transcript)
        if asyncio.iscoroutine(result):
            await result
