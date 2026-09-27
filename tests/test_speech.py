from unittest.mock import Mock

from backend.app.services.speech import FRAME_SAMPLES, SpeechService


def test_gate_drops_audio_before_vad_and_discards_partial_utterance() -> None:
    speech = SpeechService(lambda transcript: None)
    speech._vad = Mock()
    speech._vad.is_speech.return_value = True
    speech.gate(False)
    for _ in range(5):
        speech.process_frame(b"\x00\x00" * FRAME_SAMPLES)
    assert speech._buffer
    speech.gate(True)
    speech._vad.reset_mock()
    speech.process_frame(b"\x00\x00" * FRAME_SAMPLES)
    speech._vad.is_speech.assert_not_called()
    assert not speech._buffer
    speech.gate(False)
    speech.process_frame(b"\x00\x00" * FRAME_SAMPLES)
    # One fresh voiced frame must not resume the interrupted pre-playback segment.
    assert not speech._in_speech
