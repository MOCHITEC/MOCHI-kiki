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

import logging
import os
import threading
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


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
