"""Piper local TTS fallback (ARCHITECTURE.md section 15.2, 17, SW-9).

Not the cloned voice, but never silent (SW-9: CPU-only, no CUDA).
Piper ships as a standalone per-platform binary with no Python
package whose API is safe to guess at (AGENTS.md non-negotiable #8:
never invent an API). Its command-line interface is the documented,
stable contract instead: read text on stdin, write a WAV file with
``--output_file``. This also means piper-tts is not a Python
dependency at all -- nothing to fail to install on the demo machine
(AGENTS.md section 9) beyond the binary and a voice model, and if
either is missing this provider simply raises and the chain falls
through to the browser link.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from backend.providers.base import TTSProvider


class PiperTTSProvider(TTSProvider):
    name = "piper"

    def __init__(self, model_path: str, binary: str = "piper") -> None:
        if not model_path or not Path(model_path).is_file():
            raise ValueError(f"piper model not found: {model_path!r}")
        if shutil.which(binary) is None:
            raise ValueError(f"piper binary not found on PATH: {binary!r}")
        self._model_path = model_path
        self._binary = binary

    async def synthesize(self, text: str, voice_id: str | None) -> bytes:
        del voice_id  # piper's "voice" is the model file, not a runtime id
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "out.wav"
            process = await asyncio.create_subprocess_exec(
                self._binary,
                "--model",
                self._model_path,
                "--output_file",
                str(output_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await process.communicate(text.encode("utf-8"))
            if process.returncode != 0:
                raise RuntimeError(
                    f"piper exited {process.returncode}: {stderr.decode(errors='replace')}"
                )
            if not output_path.is_file():
                raise RuntimeError("piper did not produce an output file")
            return output_path.read_bytes()
