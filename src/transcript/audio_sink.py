# src/transcript/audio_sink.py
"""
AudioSink: Recall.ai の WS 経路で受け取った PCM フレームの後段プラグイン I/F。

本ファイルは I/F と最小実装 (NoopAudioSink / FileAudioSink) のみを提供する。
Azure AI Speech などへの実接続は別 spec で扱う。

契約:
- すべてのメソッドは例外を投げない（投げた場合は呼び出し側で握り潰す責務）
- push() は best-effort。呼び出し側でキュー / backpressure を制御する
"""
from __future__ import annotations

import io
import logging
import math
import os
import struct
import threading
import wave
from pathlib import Path
from typing import Awaitable, Callable, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


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


@runtime_checkable
class AudioSink(Protocol):
    """Recall WS 経路の生音声 (S16LE / 16 kHz / mono PCM) を受ける後段。"""

    async def on_open(self, *, meeting_id: str, bot_id: str, sample_rate: int) -> None:
        ...

    async def push(
        self,
        *,
        meeting_id: str,
        pcm_bytes: bytes,
        absolute_ts: str,
        relative_ts: float,
    ) -> None:
        ...

    async def on_close(self, *, meeting_id: str, reason: str) -> None:
        ...


class NoopAudioSink:
    """何もしない Sink。Spec scope のデフォルト。"""

    async def on_open(self, *, meeting_id: str, bot_id: str, sample_rate: int) -> None:
        logger.info(
            "NoopAudioSink: opened meeting_id=%s sample_rate=%d", meeting_id, sample_rate
        )

    async def push(
        self,
        *,
        meeting_id: str,
        pcm_bytes: bytes,
        absolute_ts: str,
        relative_ts: float,
    ) -> None:
        # bytes 長だけログに記録、PCM 自体は出さない
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "NoopAudioSink.push meeting_id=%s bytes=%d relative_ts=%.3f",
                meeting_id, len(pcm_bytes), relative_ts,
            )

    async def on_close(self, *, meeting_id: str, reason: str) -> None:
        logger.info("NoopAudioSink: closed meeting_id=%s reason=%s", meeting_id, reason)


class FileAudioSink:
    """
    Dev/debug 用。1 接続 = 1 raw ファイルとして保存する。
    出力フォーマットは S16LE / 16 kHz / mono の生 PCM。
    再生時は ffmpeg -f s16le -ar 16000 -ac 1 -i <file>.pcm out.wav
    """

    def __init__(self, output_dir: str = "/tmp/mochi-kiki-audio") -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        # meeting_id ごとのファイルハンドル。マルチスレッド/並行接続を想定して lock
        self._handles: dict[str, "object"] = {}
        self._lock = threading.Lock()

    async def on_open(self, *, meeting_id: str, bot_id: str, sample_rate: int) -> None:
        safe = "".join(c for c in meeting_id if c.isalnum() or c in "-_")[:64] or "unknown"
        path = self._output_dir / f"{safe}.pcm"
        with self._lock:
            # 既に開いていれば閉じる（再接続シナリオ）
            old = self._handles.pop(meeting_id, None)
            if old is not None:
                try:
                    old.close()  # type: ignore[attr-defined]
                except Exception:
                    pass
            self._handles[meeting_id] = open(path, "ab", buffering=0)
        logger.info("FileAudioSink: opened path=%s sample_rate=%d", path, sample_rate)

    async def push(
        self,
        *,
        meeting_id: str,
        pcm_bytes: bytes,
        absolute_ts: str,
        relative_ts: float,
    ) -> None:
        with self._lock:
            f = self._handles.get(meeting_id)
        if f is None:
            return
        try:
            f.write(pcm_bytes)  # type: ignore[attr-defined]
        except Exception:
            logger.exception("FileAudioSink: write failed meeting_id=%s", meeting_id)

    async def on_close(self, *, meeting_id: str, reason: str) -> None:
        with self._lock:
            f = self._handles.pop(meeting_id, None)
        if f is None:
            return
        try:
            f.close()  # type: ignore[attr-defined]
        except Exception:
            pass
        logger.info("FileAudioSink: closed meeting_id=%s reason=%s", meeting_id, reason)


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
            self._consecutive_silence = 0
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
                    if self._speech_end > 0:
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


def build_audio_sink(kind: str) -> AudioSink:
    """Config の RECALL_AUDIO_SINK 値から Sink を組み立てるファクトリ。"""
    if kind == "noop":
        return NoopAudioSink()
    if kind == "file":
        return FileAudioSink(
            output_dir=os.environ.get("RECALL_AUDIO_SINK_DIR", "/tmp/mochi-kiki-audio")
        )
    if kind == "azure_speech":
        raise NotImplementedError(
            "azure_speech sink は本 spec の範囲外。別 spec で実装予定。"
        )
    raise ValueError(f"未知の audio sink kind: {kind!r}")
