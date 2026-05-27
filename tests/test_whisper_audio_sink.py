import io
import math
import struct
import wave
import pytest

# helpers imported after they are implemented
from src.transcript.audio_sink import _compute_rms, _pcm_to_wav

_FRAME_BYTES = 640  # 20ms at 16kHz S16LE


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
