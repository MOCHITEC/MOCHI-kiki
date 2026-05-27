import io
import struct
import wave
import pytest

from src.transcript.audio_sink import _compute_rms, _pcm_to_wav, _FRAME_BYTES


def _make_pcm(amplitude: int, n_samples: int = 320) -> bytes:
    """Create S16LE mono PCM where every sample equals amplitude."""
    return struct.pack(f"<{n_samples}h", *([amplitude] * n_samples))


def test_compute_rms_silence():
    pcm = _make_pcm(0)
    assert _compute_rms(pcm) == pytest.approx(0.0)


def test_compute_rms_constant_amplitude():
    pcm = _make_pcm(1000)
    assert _compute_rms(pcm) == pytest.approx(1000.0, rel=1e-3)


def test_compute_rms_empty():
    assert _compute_rms(b"") == pytest.approx(0.0)


def test_pcm_to_wav_riff_header():
    pcm = _make_pcm(500)
    wav = _pcm_to_wav(pcm)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"


def test_pcm_to_wav_round_trip():
    pcm = _make_pcm(200, n_samples=160)  # 10ms
    wav = _pcm_to_wav(pcm)
    buf = io.BytesIO(wav)
    with wave.open(buf) as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16_000
        frames = wf.readframes(wf.getnframes())
    assert frames == pcm


import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def _make_sink(
    silence_threshold=300,
    silence_ms=600,
    min_secs=0.1,
    max_secs=30.0,
):
    """Return a WhisperAudioSink wired to a mock on_utterance and mock Whisper client."""
    from src.transcript.audio_sink import WhisperAudioSink
    mock_client = MagicMock()
    mock_client.audio = MagicMock()
    mock_client.audio.transcriptions = MagicMock()
    mock_client.audio.transcriptions.create = AsyncMock(
        return_value=MagicMock(text="テスト発話")
    )
    mock_utterance_cb = AsyncMock()
    sink = WhisperAudioSink(
        openai_client=mock_client,
        whisper_deployment="whisper",
        on_utterance=mock_utterance_cb,
        silence_rms_threshold=silence_threshold,
        silence_duration_ms=silence_ms,
        min_segment_secs=min_secs,
        max_segment_secs=max_secs,
    )
    sink._mock_client = mock_client
    sink._mock_cb = mock_utterance_cb
    return sink


def _run(coro):
    return asyncio.run(coro)


def test_silence_triggers_flush():
    """Speech frames followed by enough silence should call on_utterance."""
    sink = _make_sink(silence_threshold=300, silence_ms=40, min_secs=0.0)
    _run(sink.on_open(meeting_id="m1", bot_id="b1", sample_rate=16000))

    # 200ms of speech (amplitude 2000 >> threshold 300)
    speech = _make_pcm(2000, n_samples=320) * 10  # 10 × 20ms = 200ms
    _run(sink.push(meeting_id="m1", pcm_bytes=speech, absolute_ts="", relative_ts=0.0))

    # 60ms silence (3 frames, silence_ms=40 → 2 frames needed)
    silence = _make_pcm(0, n_samples=320) * 3
    _run(sink.push(meeting_id="m1", pcm_bytes=silence, absolute_ts="", relative_ts=0.2))

    sink._mock_client.audio.transcriptions.create.assert_awaited_once()
    sink._mock_cb.assert_awaited_once()


def test_min_segment_too_short_skips_flush():
    """Segment shorter than min_secs must NOT trigger on_utterance."""
    sink = _make_sink(silence_threshold=300, silence_ms=40, min_secs=10.0)
    _run(sink.on_open(meeting_id="m1", bot_id="b1", sample_rate=16000))

    speech = _make_pcm(2000, n_samples=320) * 5  # 100ms — less than 10s min
    _run(sink.push(meeting_id="m1", pcm_bytes=speech, absolute_ts="", relative_ts=0.0))
    silence = _make_pcm(0, n_samples=320) * 3
    _run(sink.push(meeting_id="m1", pcm_bytes=silence, absolute_ts="", relative_ts=0.1))

    sink._mock_cb.assert_not_awaited()


def test_max_segment_hard_flush():
    """Buffer exceeding max_secs must flush even without silence."""
    sink = _make_sink(silence_threshold=300, silence_ms=600, min_secs=0.0, max_secs=0.1)
    _run(sink.on_open(meeting_id="m1", bot_id="b1", sample_rate=16000))

    # 200ms of continuous speech — exceeds max_secs=0.1s
    speech = _make_pcm(2000, n_samples=320) * 10
    _run(sink.push(meeting_id="m1", pcm_bytes=speech, absolute_ts="", relative_ts=0.0))

    sink._mock_client.audio.transcriptions.create.assert_awaited()


def test_on_close_flushes_remaining():
    """on_close with buffered speech must flush the remaining segment."""
    sink = _make_sink(silence_threshold=300, silence_ms=60000, min_secs=0.0)
    _run(sink.on_open(meeting_id="m1", bot_id="b1", sample_rate=16000))

    speech = _make_pcm(2000, n_samples=320) * 5
    _run(sink.push(meeting_id="m1", pcm_bytes=speech, absolute_ts="", relative_ts=0.0))
    _run(sink.on_close(meeting_id="m1", reason="done"))

    sink._mock_client.audio.transcriptions.create.assert_awaited_once()
