# Recall.ai × Azure OpenAI Whisper × Azure AI Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Recall.ai raw audio through a silence-detecting Whisper transcription sink, populate the Azure AI Search index, and fix a word-parsing bug in the deprecated webhook router.

**Architecture:** `WhisperAudioSink` buffers raw PCM from Recall.ai's WebSocket, detects speech/silence boundaries via per-frame RMS energy, flushes speech segments to Azure OpenAI Whisper, then feeds the resulting text into the existing Orchestrator → RAG pipeline. When Whisper is active, Recall's native `transcript.data` events are suppressed to prevent duplicate utterances.

**Tech Stack:** Python 3.11, aiohttp, openai (AsyncAzureOpenAI), azure-search-documents, wave (stdlib), struct (stdlib)

---

## File Map

| File | Change |
|---|---|
| `src/config.py` | Add 5 Whisper env vars; add `azure_openai_whisper` to `_ALLOWED_AUDIO_SINKS` |
| `src/transcript/audio_sink.py` | Add `_compute_rms`, `_pcm_to_wav` helpers; add `WhisperAudioSink` class with `set_on_utterance`; update `build_audio_sink` docstring |
| `src/transcript/recall_ws_handler.py` | Add `suppress_native_transcript: bool = False` param; early-return in `_handle_transcript` |
| `src/main.py` | Construct `WhisperAudioSink` directly when `azure_openai_whisper`; pass `suppress_native_transcript`; call `audio_sink.set_on_utterance` in step 9 |
| `src/api/recall_router.py` | Fix word parsing: replace broken `isinstance(w, str)` filter with `extract_utterance_from_transcript_data` |
| `scripts/check_search_index.py` | New script: report index existence, doc count, and run one vector search |
| `tests/test_whisper_audio_sink.py` | New: full unit test suite for helpers, silence detection, hard flush, API mock |
| `tests/test_recall_ws_suppress.py` | New: verify `suppress_native_transcript=True` skips `on_utterance` |

---

## Task 1: Config — add Whisper env vars

**Files:**
- Modify: `src/config.py`

- [ ] **Step 1: Add `azure_openai_whisper` to `_ALLOWED_AUDIO_SINKS` and add 5 Whisper attributes**

Open `src/config.py`. Make these two edits:

```python
# line 10 — change the set
_ALLOWED_AUDIO_SINKS = {"noop", "file", "azure_speech", "azure_openai_whisper"}
```

Add these 5 attribute declarations after line 38 (`recall_audio_sink: str`):

```python
    whisper_deployment: str
    whisper_silence_threshold: int
    whisper_silence_ms: int
    whisper_min_secs: float
    whisper_max_secs: float
```

Add these 5 assignments at the end of `__init__`, after `self.recall_audio_sink = sink`:

```python
        self.whisper_deployment = os.environ.get("RECALL_WHISPER_DEPLOYMENT", "whisper").strip() or "whisper"
        self.whisper_silence_threshold = int(os.environ.get("RECALL_WHISPER_SILENCE_THRESHOLD", "300"))
        self.whisper_silence_ms = int(os.environ.get("RECALL_WHISPER_SILENCE_MS", "600"))
        self.whisper_min_secs = float(os.environ.get("RECALL_WHISPER_MIN_SECS", "1.0"))
        self.whisper_max_secs = float(os.environ.get("RECALL_WHISPER_MAX_SECS", "30.0"))
```

- [ ] **Step 2: Verify Config loads without errors**

```powershell
cd C:\Users\hendr\Programming\11_Mochitec\MOCHI-kiki
python -c "
import os; os.environ.update({
    'MICROSOFT_APP_ID':'x','MICROSOFT_APP_PASSWORD':'x',
    'AZURE_COSMOS_ENDPOINT':'https://x.documents.azure.com:443/',
    'AZURE_COSMOS_KEY':'x','GRAPH_TENANT_ID':'x','GRAPH_CLIENT_ID':'x',
    'GRAPH_CLIENT_SECRET':'x',
    'GRAPH_NOTIFICATION_URL':'https://x.example.com/api/notifications',
    'AZURE_OPENAI_ENDPOINT':'https://x.openai.azure.com/',
    'AZURE_OPENAI_KEY':'x','AZURE_SEARCH_ENDPOINT':'https://x.search.windows.net',
    'AZURE_SEARCH_KEY':'x',
    'RECALL_AUDIO_SINK':'azure_openai_whisper',
    'RECALL_WHISPER_DEPLOYMENT':'whisper',
})
from src.config import Config; c = Config()
print(c.whisper_deployment, c.whisper_silence_threshold, c.whisper_silence_ms)
"
```

Expected output: `whisper 300 600`

- [ ] **Step 3: Commit**

```bash
git add src/config.py
git commit -m "feat(config): add Whisper env vars and azure_openai_whisper sink option"
```

---

## Task 2: WhisperAudioSink — helper functions + tests

**Files:**
- Modify: `src/transcript/audio_sink.py`
- Create: `tests/test_whisper_audio_sink.py`

- [ ] **Step 1: Write failing tests for `_compute_rms` and `_pcm_to_wav`**

Create `tests/test_whisper_audio_sink.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect ImportError (functions not yet defined)**

```bash
.venv\Scripts\python -m pytest tests/test_whisper_audio_sink.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name '_compute_rms' from 'src.transcript.audio_sink'`

- [ ] **Step 3: Add imports and helper functions to `src/transcript/audio_sink.py`**

Add these imports at the top of `src/transcript/audio_sink.py` (after existing imports):

```python
import io
import math
import struct
import wave
```

Add these two module-level constants and functions after the logger line:

```python
_SAMPLE_RATE = 16_000
_BYTES_PER_SAMPLE = 2        # S16LE
_FRAME_MS = 20
_FRAME_SAMPLES = _SAMPLE_RATE * _FRAME_MS // 1000   # 320
_FRAME_BYTES = _FRAME_SAMPLES * _BYTES_PER_SAMPLE   # 640


def _compute_rms(frame: bytes) -> float:
    n = len(frame) // _BYTES_PER_SAMPLE
    if n == 0:
        return 0.0
    samples = struct.unpack(f"<{n}h", frame[:n * _BYTES_PER_SAMPLE])
    mean_sq = sum(s * s for s in samples) / n
    return math.sqrt(mean_sq)


def _pcm_to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(_BYTES_PER_SAMPLE)
        wf.setframerate(_SAMPLE_RATE)
        wf.writeframes(pcm)
    return buf.getvalue()
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
.venv\Scripts\python -m pytest tests/test_whisper_audio_sink.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add src/transcript/audio_sink.py tests/test_whisper_audio_sink.py
git commit -m "feat(whisper-sink): add _compute_rms and _pcm_to_wav helpers"
```

---

## Task 3: WhisperAudioSink — silence detection and buffer management

**Files:**
- Modify: `src/transcript/audio_sink.py`
- Modify: `tests/test_whisper_audio_sink.py`

- [ ] **Step 1: Add silence-detection tests to `tests/test_whisper_audio_sink.py`**

Append to the file:

```python
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
    return asyncio.get_event_loop().run_until_complete(coro)


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
```

- [ ] **Step 2: Run tests — expect ImportError (class not yet defined)**

```bash
.venv\Scripts\python -m pytest tests/test_whisper_audio_sink.py::test_silence_triggers_flush -v 2>&1 | head -10
```

Expected: `ImportError: cannot import name 'WhisperAudioSink'`

- [ ] **Step 3: Add `WhisperAudioSink` class (without `_flush` body — stub raises) to `src/transcript/audio_sink.py`**

Add these imports to the top of `audio_sink.py`:

```python
from typing import Awaitable, Callable, Optional
```

Add the class after `FileAudioSink`. The `_flush` method body is a stub for now:

```python
class WhisperAudioSink:
    """
    Silence-detecting AudioSink that transcribes speech segments via
    Azure OpenAI Whisper.  S16LE 16kHz mono PCM only.
    """

    def __init__(
        self,
        openai_client: "object",       # AsyncAzureOpenAI; typed as object to avoid import cycle
        whisper_deployment: str,
        on_utterance: Callable[["object"], Awaitable[None]],
        *,
        silence_rms_threshold: int = 300,
        silence_duration_ms: int = 600,
        min_segment_secs: float = 1.0,
        max_segment_secs: float = 30.0,
    ) -> None:
        self._client = openai_client
        self._deployment = whisper_deployment
        self._on_utterance = on_utterance
        self._silence_threshold = silence_rms_threshold
        self._silence_frames_needed = max(1, silence_duration_ms // _FRAME_MS)
        self._min_segment_bytes = int(min_segment_secs * _SAMPLE_RATE * _BYTES_PER_SAMPLE)
        self._max_segment_bytes = int(max_segment_secs * _SAMPLE_RATE * _BYTES_PER_SAMPLE)
        self._max_buffer_bytes = 2 * 1024 * 1024  # 2 MB ≈ 62 s

        self._meeting_id: Optional[str] = None
        self._buffer = bytearray()
        self._processed = 0
        self._consecutive_silence = 0
        self._speech_end = 0

    def set_on_utterance(self, on_utterance: Callable[["object"], Awaitable[None]]) -> None:
        self._on_utterance = on_utterance

    async def on_open(self, *, meeting_id: str, bot_id: str, sample_rate: int) -> None:
        self._meeting_id = meeting_id
        self._reset()
        logger.info("WhisperAudioSink: opened meeting_id=%s", meeting_id)

    async def push(
        self,
        *,
        meeting_id: str,
        pcm_bytes: bytes,
        absolute_ts: str,
        relative_ts: float,
    ) -> None:
        if self._meeting_id is None:
            return
        # overflow: drop oldest bytes to make room
        available = self._max_buffer_bytes - len(self._buffer)
        if len(pcm_bytes) > available:
            drop = len(pcm_bytes) - available
            self._buffer = self._buffer[drop:]
            self._processed = max(0, self._processed - drop)
            self._speech_end = max(0, self._speech_end - drop)
            logger.warning("WhisperAudioSink: buffer overflow, dropped %d bytes", drop)

        self._buffer.extend(pcm_bytes)
        await self._scan_new_frames()

        if len(self._buffer) >= self._max_segment_bytes:
            await self._flush(bytes(self._buffer))
            self._reset()

    async def on_close(self, *, meeting_id: str, reason: str) -> None:
        if self._meeting_id and len(self._buffer) >= self._min_segment_bytes:
            await self._flush(bytes(self._buffer))
        self._reset()
        self._meeting_id = None
        logger.info("WhisperAudioSink: closed meeting_id=%s reason=%s", meeting_id, reason)

    async def _scan_new_frames(self) -> None:
        while self._processed + _FRAME_BYTES <= len(self._buffer):
            frame = self._buffer[self._processed : self._processed + _FRAME_BYTES]
            rms = _compute_rms(bytes(frame))
            if rms < self._silence_threshold:
                if self._consecutive_silence == 0:
                    self._speech_end = self._processed
                self._consecutive_silence += 1
                if self._consecutive_silence >= self._silence_frames_needed:
                    speech = bytes(self._buffer[: self._speech_end])
                    await self._flush(speech)
                    self._reset()
                    return
            else:
                self._consecutive_silence = 0
            self._processed += _FRAME_BYTES

    def _reset(self) -> None:
        self._buffer = bytearray()
        self._processed = 0
        self._consecutive_silence = 0
        self._speech_end = 0

    async def _flush(self, pcm: bytes) -> None:
        if len(pcm) < self._min_segment_bytes:
            return
        raise NotImplementedError("_flush implemented in Task 4")
```

- [ ] **Step 4: Run silence-detection tests — expect failures only on `_flush NotImplementedError`**

```bash
.venv\Scripts\python -m pytest tests/test_whisper_audio_sink.py -v -k "silence or min_segment or max_segment or on_close"
```

Expected: all 4 tests fail with `NotImplementedError: _flush implemented in Task 4`

- [ ] **Step 5: Commit stub**

```bash
git add src/transcript/audio_sink.py tests/test_whisper_audio_sink.py
git commit -m "feat(whisper-sink): add WhisperAudioSink skeleton with silence detection"
```

---

## Task 4: WhisperAudioSink — Whisper API flush + `build_audio_sink` update

**Files:**
- Modify: `src/transcript/audio_sink.py`
- Modify: `tests/test_whisper_audio_sink.py`

- [ ] **Step 1: Add Whisper API tests to `tests/test_whisper_audio_sink.py`**

Append to the file:

```python
def test_flush_calls_whisper_with_wav(monkeypatch):
    """_flush must POST WAV to the Whisper API with language=ja."""
    sink = _make_sink(silence_threshold=300, silence_ms=40, min_secs=0.0)
    _run(sink.on_open(meeting_id="m1", bot_id="b1", sample_rate=16000))

    speech = _make_pcm(2000, n_samples=320) * 5
    _run(sink.push(meeting_id="m1", pcm_bytes=speech, absolute_ts="", relative_ts=0.0))
    silence = _make_pcm(0, n_samples=320) * 3
    _run(sink.push(meeting_id="m1", pcm_bytes=silence, absolute_ts="", relative_ts=0.1))

    call_kwargs = sink._mock_client.audio.transcriptions.create.call_args
    assert call_kwargs.kwargs["language"] == "ja"
    assert call_kwargs.kwargs["model"] == "whisper"
    filename, wav_bytes, mime = call_kwargs.kwargs["file"]
    assert filename == "segment.wav"
    assert wav_bytes[:4] == b"RIFF"
    assert mime == "audio/wav"


def test_flush_creates_utterance_with_whisper_text():
    """on_utterance must be called with Utterance whose text matches Whisper response."""
    sink = _make_sink(silence_threshold=300, silence_ms=40, min_secs=0.0)
    _run(sink.on_open(meeting_id="m1", bot_id="b1", sample_rate=16000))

    speech = _make_pcm(2000, n_samples=320) * 5
    _run(sink.push(meeting_id="m1", pcm_bytes=speech, absolute_ts="", relative_ts=0.0))
    silence = _make_pcm(0, n_samples=320) * 3
    _run(sink.push(meeting_id="m1", pcm_bytes=silence, absolute_ts="", relative_ts=0.1))

    args = sink._mock_cb.call_args
    utterance = args[0][0]
    assert utterance.text == "テスト発話"
    assert utterance.meeting_id == "m1"
    assert utterance.speaker_id == "whisper"
    assert utterance.speaker_name == "Whisper ASR"


def test_flush_empty_whisper_response_skips_utterance():
    """If Whisper returns empty text, on_utterance must NOT be called."""
    sink = _make_sink(silence_threshold=300, silence_ms=40, min_secs=0.0)
    sink._mock_client.audio.transcriptions.create = AsyncMock(
        return_value=MagicMock(text="   ")
    )
    _run(sink.on_open(meeting_id="m1", bot_id="b1", sample_rate=16000))

    speech = _make_pcm(2000, n_samples=320) * 5
    _run(sink.push(meeting_id="m1", pcm_bytes=speech, absolute_ts="", relative_ts=0.0))
    silence = _make_pcm(0, n_samples=320) * 3
    _run(sink.push(meeting_id="m1", pcm_bytes=silence, absolute_ts="", relative_ts=0.1))

    sink._mock_cb.assert_not_awaited()


def test_flush_api_exception_does_not_propagate():
    """Whisper API failure must be caught — push() must not raise."""
    sink = _make_sink(silence_threshold=300, silence_ms=40, min_secs=0.0)
    sink._mock_client.audio.transcriptions.create = AsyncMock(
        side_effect=Exception("API error")
    )
    _run(sink.on_open(meeting_id="m1", bot_id="b1", sample_rate=16000))

    speech = _make_pcm(2000, n_samples=320) * 5
    silence = _make_pcm(0, n_samples=320) * 3
    # Must not raise
    _run(sink.push(meeting_id="m1", pcm_bytes=speech, absolute_ts="", relative_ts=0.0))
    _run(sink.push(meeting_id="m1", pcm_bytes=silence, absolute_ts="", relative_ts=0.1))
```

- [ ] **Step 2: Run new tests — expect NotImplementedError**

```bash
.venv\Scripts\python -m pytest tests/test_whisper_audio_sink.py -v -k "flush" 2>&1 | head -20
```

Expected: `NotImplementedError: _flush implemented in Task 4`

- [ ] **Step 3: Replace `_flush` stub with real implementation in `src/transcript/audio_sink.py`**

Replace the `_flush` method body (keep the signature):

```python
    async def _flush(self, pcm: bytes) -> None:
        if len(pcm) < self._min_segment_bytes:
            return
        if self._meeting_id is None:
            return
        wav = _pcm_to_wav(pcm)
        try:
            response = await self._client.audio.transcriptions.create(
                model=self._deployment,
                file=("segment.wav", wav, "audio/wav"),
                language="ja",
            )
            text = (response.text or "").strip()
            if not text:
                return
            from src.models import Utterance
            utterance = Utterance.new(
                meeting_id=self._meeting_id,
                speaker_id="whisper",
                speaker_name="Whisper ASR",
                text=text,
            )
            await self._on_utterance(utterance)
        except Exception:
            logger.exception("WhisperAudioSink: Whisper API flush failed")
```

Also update `build_audio_sink` — add a clear error for `azure_openai_whisper` (it must be constructed in `main.py`, not here):

```python
def build_audio_sink(kind: str) -> AudioSink:
    """Factory for non-Whisper sinks. For azure_openai_whisper, construct WhisperAudioSink directly in main.py."""
    if kind == "noop":
        return NoopAudioSink()
    if kind == "file":
        return FileAudioSink(
            output_dir=os.environ.get("RECALL_AUDIO_SINK_DIR", "/tmp/mochi-kiki-audio")
        )
    if kind in ("azure_speech", "azure_openai_whisper"):
        raise NotImplementedError(
            f"{kind} sink must be constructed directly in main.py (requires openai_client + config)."
        )
    raise ValueError(f"未知の audio sink kind: {kind!r}")
```

- [ ] **Step 4: Run all WhisperAudioSink tests**

```bash
.venv\Scripts\python -m pytest tests/test_whisper_audio_sink.py -v
```

Expected: all tests pass (5 helpers + 4 silence + 4 flush = 13 passed)

- [ ] **Step 5: Commit**

```bash
git add src/transcript/audio_sink.py tests/test_whisper_audio_sink.py
git commit -m "feat(whisper-sink): implement _flush with Whisper API call"
```

---

## Task 5: RecallWsHandler — suppress native transcript

**Files:**
- Modify: `src/transcript/recall_ws_handler.py`
- Create: `tests/test_recall_ws_suppress.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_recall_ws_suppress.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_handler(suppress: bool):
    from src.transcript.recall_ws_handler import RecallWsHandler
    cosmos = MagicMock()
    cosmos.find_meeting_id_by_recall_bot_id = AsyncMock(return_value="m1")
    on_utterance = AsyncMock()
    handler = RecallWsHandler(
        cosmos_client=cosmos,
        on_utterance=on_utterance,
        webhook_secret=None,
        suppress_native_transcript=suppress,
    )
    return handler, on_utterance


_TRANSCRIPT_PAYLOAD = {
    "event": "transcript.data",
    "data": {
        "data": {
            "words": [{"text": "テスト"}],
            "participant": {"id": 1, "name": "田中"},
        },
        "bot": {"id": "bot-abc"},
    },
}


def test_native_transcript_suppressed_when_flag_true():
    handler, on_utterance = _make_handler(suppress=True)
    from src.transcript.recall_ws_handler import _ConnectionState
    session = _ConnectionState()
    session.bot_id = "bot-abc"
    session.meeting_id = "m1"

    _run(handler._handle_transcript(session, _TRANSCRIPT_PAYLOAD, partial=False))

    on_utterance.assert_not_awaited()


def test_native_transcript_passes_when_flag_false():
    handler, on_utterance = _make_handler(suppress=False)
    cosmos = handler._cosmos
    cosmos.save_utterance = AsyncMock()
    from src.transcript.recall_ws_handler import _ConnectionState
    session = _ConnectionState()
    session.bot_id = "bot-abc"
    session.meeting_id = "m1"

    _run(handler._handle_transcript(session, _TRANSCRIPT_PAYLOAD, partial=False))

    on_utterance.assert_awaited_once()
```

- [ ] **Step 2: Run test — expect TypeError (unexpected keyword argument)**

```bash
.venv\Scripts\python -m pytest tests/test_recall_ws_suppress.py -v 2>&1 | head -15
```

Expected: `TypeError: __init__() got an unexpected keyword argument 'suppress_native_transcript'`

- [ ] **Step 3: Add `suppress_native_transcript` to `RecallWsHandler`**

In `src/transcript/recall_ws_handler.py`, add the parameter to `__init__`:

```python
    def __init__(
        self,
        cosmos_client: "CosmosClient",
        on_utterance: Callable[[Utterance], Awaitable[None]],
        audio_sink: Optional[AudioSink] = None,
        webhook_secret: Optional[str] = None,
        webhook_handler: Optional["RecallWebhookHandler"] = None,
        clock: Callable[[], float] = time.time,
        heartbeat_seconds: float = _DEFAULT_HEARTBEAT_SECONDS,
        suppress_native_transcript: bool = False,
    ) -> None:
```

Add assignment in `__init__` body (after `self._heartbeat = heartbeat_seconds`):

```python
        self._suppress_native_transcript = suppress_native_transcript
```

Add early return at the very start of `_handle_transcript`:

```python
    async def _handle_transcript(
        self, session: "_ConnectionState", payload: dict, *, partial: bool
    ) -> None:
        if self._suppress_native_transcript:
            return
        # ... rest unchanged
```

- [ ] **Step 4: Run tests**

```bash
.venv\Scripts\python -m pytest tests/test_recall_ws_suppress.py -v
```

Expected: `2 passed`

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
.venv\Scripts\python -m pytest tests/ -v --ignore=tests/test_cosmos_client.py --ignore=tests/test_graph_subscription.py 2>&1 | tail -20
```

Expected: all tests pass (ignore Cosmos/Graph tests that require live credentials)

- [ ] **Step 6: Commit**

```bash
git add src/transcript/recall_ws_handler.py tests/test_recall_ws_suppress.py
git commit -m "feat(ws-handler): add suppress_native_transcript param to avoid duplicate utterances"
```

---

## Task 6: main.py — wire WhisperAudioSink

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: Update imports at the top of `src/main.py`**

Add `WhisperAudioSink` to the audio_sink import line:

```python
from src.transcript.audio_sink import build_audio_sink, WhisperAudioSink
```

- [ ] **Step 2: Replace the `audio_sink` construction block in `main.py`**

Find this block (around line 57–67):

```python
    # 2.b Recall WS handler (transport が websocket/both のとき有効)
    recall_ws_handler: Optional[RecallWsHandler] = None
    if config.recall_transport in ("websocket", "both"):
        audio_sink = build_audio_sink(config.recall_audio_sink)
        recall_ws_handler = RecallWsHandler(
            cosmos_client=cosmos,
            on_utterance=_placeholder_on_utterance,
            audio_sink=audio_sink,
            webhook_secret=config.recall_webhook_secret,
            webhook_handler=recall_handler,
        )
```

Replace with:

```python
    # 2.b Recall WS handler (transport が websocket/both のとき有効)
    recall_ws_handler: Optional[RecallWsHandler] = None
    audio_sink = None
    if config.recall_transport in ("websocket", "both"):
        if config.recall_audio_sink == "azure_openai_whisper":
            from openai import AsyncAzureOpenAI as _AsyncAOAI
            _ws_oai_client = _AsyncAOAI(
                azure_endpoint=config.azure_openai_endpoint,
                api_key=config.azure_openai_key,
                api_version="2024-02-01",
            )
            audio_sink = WhisperAudioSink(
                openai_client=_ws_oai_client,
                whisper_deployment=config.whisper_deployment,
                on_utterance=_placeholder_on_utterance,
                silence_rms_threshold=config.whisper_silence_threshold,
                silence_duration_ms=config.whisper_silence_ms,
                min_segment_secs=config.whisper_min_secs,
                max_segment_secs=config.whisper_max_secs,
            )
            logger.info("WhisperAudioSink 起動 (deployment=%s)", config.whisper_deployment)
        else:
            audio_sink = build_audio_sink(config.recall_audio_sink)

        recall_ws_handler = RecallWsHandler(
            cosmos_client=cosmos,
            on_utterance=_placeholder_on_utterance,
            audio_sink=audio_sink,
            webhook_secret=config.recall_webhook_secret,
            webhook_handler=recall_handler,
            suppress_native_transcript=(config.recall_audio_sink == "azure_openai_whisper"),
        )
        logger.info(
            "RecallWsHandler 起動 (audio_sink=%s, suppress_native=%s)",
            config.recall_audio_sink,
            config.recall_audio_sink == "azure_openai_whisper",
        )
```

- [ ] **Step 3: Update step 9 in `main.py` to also update `WhisperAudioSink.on_utterance`**

Find this block (around line 136–138):

```python
    # 9. inject on_utterance into bot & handlers
    bot._on_utterance = on_utterance
    recall_handler.set_on_utterance(on_utterance)
    if recall_ws_handler is not None:
        recall_ws_handler.set_on_utterance(on_utterance)
```

Replace with:

```python
    # 9. inject on_utterance into bot & handlers
    bot._on_utterance = on_utterance
    recall_handler.set_on_utterance(on_utterance)
    if recall_ws_handler is not None:
        recall_ws_handler.set_on_utterance(on_utterance)
    if audio_sink is not None and hasattr(audio_sink, "set_on_utterance"):
        audio_sink.set_on_utterance(on_utterance)
```

- [ ] **Step 4: Verify import works**

```bash
.venv\Scripts\python -c "from src.transcript.audio_sink import WhisperAudioSink; print('ok')"
```

Expected: `ok`

- [ ] **Step 5: Run full test suite**

```bash
.venv\Scripts\python -m pytest tests/ -v --ignore=tests/test_cosmos_client.py --ignore=tests/test_graph_subscription.py 2>&1 | tail -10
```

Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add src/main.py
git commit -m "feat(main): wire WhisperAudioSink and suppress_native_transcript"
```

---

## Task 7: Fix word-parsing bug in recall_router.py

**Files:**
- Modify: `src/api/recall_router.py`
- Modify: `tests/test_recall_router.py` (create if not exists)

- [ ] **Step 1: Write a failing test**

Check whether `tests/test_recall_router.py` exists:

```bash
.venv\Scripts\python -m pytest tests/test_recall_router.py -v 2>&1 | head -5
```

If it doesn't exist, create `tests/test_recall_router.py`:

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_router():
    from src.api.recall_router import RecallWebhookRouter
    orchestrator = MagicMock()
    orchestrator.process = AsyncMock()
    cosmos = MagicMock()
    cosmos.save_utterance = AsyncMock()
    return RecallWebhookRouter(orchestrator=orchestrator, cosmos=cosmos), orchestrator


def _make_request(body: dict):
    req = AsyncMock()
    req.json = AsyncMock(return_value=body)
    return req


def test_router_parses_words_dict_list():
    """words is list[dict], not list[str] — router must extract .text from each."""
    router, orchestrator = _make_router()
    body = {
        "event": "transcript.data",
        "data": {
            "bot_id": "bot-001",
            "data": {
                "speaker": "田中",
                "words": [{"text": "この"}, {"text": "仕様は"}],
            },
        },
    }
    req = _make_request(body)
    _run(router._handle(req))
    orchestrator.process.assert_awaited_once()
    utterance = orchestrator.process.call_args[0][0]
    assert utterance.text == "この仕様は"
```

- [ ] **Step 2: Run test — expect failure**

```bash
.venv\Scripts\python -m pytest tests/test_recall_router.py::test_router_parses_words_dict_list -v
```

Expected: FAIL — `utterance.text == ""` (bug: `isinstance(w, str)` filters out all dicts)

- [ ] **Step 3: Fix `src/api/recall_router.py`**

Replace the entire `_handle` method:

```python
    async def _handle(self, req: web.Request) -> web.Response:
        body = await req.json()

        if body.get("event") != "transcript.data":
            return web.Response(status=200)

        data = body.get("data", {})
        bot_id = data.get("bot_id", "unknown")

        from src.transcript.transcript_pipeline import extract_utterance_from_transcript_data
        utterance = extract_utterance_from_transcript_data(body, meeting_id=bot_id)
        if utterance is None:
            return web.Response(status=200)

        if self._cosmos is not None:
            try:
                await self._cosmos.save_utterance(utterance)
            except Exception:
                logger.exception("cosmos.save_utterance() failed for utterance %s", utterance.utterance_id)

        try:
            await self._orchestrator.process(utterance)
        except Exception:
            logger.exception("orchestrator.process() failed for utterance %s", utterance.utterance_id)

        return web.Response(status=202)
```

- [ ] **Step 4: Run test — expect PASS**

```bash
.venv\Scripts\python -m pytest tests/test_recall_router.py -v
```

Expected: `1 passed` (or all pass if file already had tests)

- [ ] **Step 5: Commit**

```bash
git add src/api/recall_router.py tests/test_recall_router.py
git commit -m "fix(recall-router): fix word parsing bug — words is list[dict] not list[str]"
```

---

## Task 8: Add `check_search_index.py` smoke test script

**Files:**
- Create: `scripts/check_search_index.py`

- [ ] **Step 1: Create the script**

Create `scripts/check_search_index.py`:

```python
"""
Azure AI Search インデックスの状態を確認するスモークテストスクリプト。

Usage:
    python scripts/check_search_index.py

必要な env vars (setup_search_index.py と共通):
    AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_KEY, AZURE_SEARCH_INDEX
    AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY, AZURE_OPENAI_EMBEDDING_DEPLOYMENT
"""
import os
import sys

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ResourceNotFoundError
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.models import VectorizedQuery
from openai import AzureOpenAI

SEARCH_ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"]
SEARCH_KEY = os.environ["AZURE_SEARCH_KEY"]
INDEX_NAME = os.environ.get("AZURE_SEARCH_INDEX", "documents")
OPENAI_ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"]
OPENAI_KEY = os.environ["AZURE_OPENAI_KEY"]
EMBEDDING_DEPLOYMENT = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")


def check_index_exists() -> bool:
    credential = AzureKeyCredential(SEARCH_KEY)
    index_client = SearchIndexClient(endpoint=SEARCH_ENDPOINT, credential=credential)
    try:
        idx = index_client.get_index(INDEX_NAME)
        print(f"✓ インデックス '{INDEX_NAME}' が存在します (fields={len(idx.fields)})")
        return True
    except ResourceNotFoundError:
        print(f"✗ インデックス '{INDEX_NAME}' が存在しません。setup_search_index.py を実行してください。")
        return False


def check_document_count() -> int:
    credential = AzureKeyCredential(SEARCH_KEY)
    search_client = SearchClient(endpoint=SEARCH_ENDPOINT, index_name=INDEX_NAME, credential=credential)
    count = search_client.get_document_count()
    print(f"✓ ドキュメント数: {count} 件")
    return count


def check_vector_search() -> bool:
    openai_client = AzureOpenAI(
        azure_endpoint=OPENAI_ENDPOINT, api_key=OPENAI_KEY, api_version="2024-02-01"
    )
    credential = AzureKeyCredential(SEARCH_KEY)
    search_client = SearchClient(endpoint=SEARCH_ENDPOINT, index_name=INDEX_NAME, credential=credential)

    query = "認証フロー"
    vector = openai_client.embeddings.create(input=query, model=EMBEDDING_DEPLOYMENT).data[0].embedding
    vq = VectorizedQuery(vector=vector, k_nearest_neighbors=1, fields="content_vector")
    results = list(search_client.search(search_text=query, vector_queries=[vq], select=["id", "title"], top=1))

    if results:
        print(f"✓ ベクトル検索 OK: top result id={results[0]['id']} title={results[0]['title']}")
        return True
    else:
        print("✗ ベクトル検索で結果が0件です。ドキュメントが投入されているか確認してください。")
        return False


if __name__ == "__main__":
    ok = True
    ok &= check_index_exists()
    if ok:
        count = check_document_count()
        ok &= count > 0
        ok &= check_vector_search()
    sys.exit(0 if ok else 1)
```

- [ ] **Step 2: Commit**

```bash
git add scripts/check_search_index.py
git commit -m "feat(scripts): add check_search_index.py smoke test"
```

---

## Task 9: Run setup_search_index.py + update .env

- [ ] **Step 1: Load .env and run setup_search_index.py**

```powershell
# PowerShell: load .env vars then run the script
Get-Content .env | Where-Object { $_ -match '^\s*[^#]' -and $_ -match '=' } | ForEach-Object {
    $parts = $_ -split '=', 2
    [System.Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), 'Process')
}
.venv\Scripts\python scripts/setup_search_index.py
```

Expected output:
```
インデックス 'documents' を作成しました。
11 件のドキュメントを投入しました。
セットアップ完了。
```

- [ ] **Step 2: Verify with check_search_index.py**

```powershell
.venv\Scripts\python scripts/check_search_index.py
```

Expected:
```
✓ インデックス 'documents' が存在します (fields=6)
✓ ドキュメント数: 11 件
✓ ベクトル検索 OK: top result id=doc-001 title=認証フロー仕様書 v2.3
```

- [ ] **Step 3: Add Whisper env vars to .env**

Open `.env` and add these two lines under the Recall.ai section:

```
RECALL_AUDIO_SINK=azure_openai_whisper
RECALL_WHISPER_DEPLOYMENT=whisper
```

(The silence/min/max defaults are fine; add them only if you want to tune.)

- [ ] **Step 4: Run full test suite one last time**

```bash
.venv\Scripts\python -m pytest tests/ -v --ignore=tests/test_cosmos_client.py --ignore=tests/test_graph_subscription.py 2>&1 | tail -15
```

Expected: all tests pass

- [ ] **Step 5: Final commit**

```bash
git add .env
git commit -m "chore: enable WhisperAudioSink in .env and populate Azure AI Search index"
```
