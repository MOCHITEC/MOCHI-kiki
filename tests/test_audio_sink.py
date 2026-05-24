# tests/test_audio_sink.py
import os
import tempfile

import pytest

from src.transcript.audio_sink import (
    AudioSink,
    FileAudioSink,
    NoopAudioSink,
    build_audio_sink,
)


def test_noop_sink_implements_protocol() -> None:
    sink = NoopAudioSink()
    assert isinstance(sink, AudioSink)


async def test_noop_sink_methods_do_not_raise() -> None:
    sink = NoopAudioSink()
    await sink.on_open(meeting_id="m1", bot_id="b1", sample_rate=16000)
    await sink.push(
        meeting_id="m1",
        pcm_bytes=b"\x00\x01" * 100,
        absolute_ts="2026-05-22T00:00:00Z",
        relative_ts=0.1,
    )
    await sink.on_close(meeting_id="m1", reason="end")


async def test_file_sink_writes_pcm_bytes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        sink = FileAudioSink(output_dir=tmp)
        await sink.on_open(meeting_id="m1", bot_id="b1", sample_rate=16000)
        pcm = b"\x00\x01\x02\x03"
        await sink.push(
            meeting_id="m1",
            pcm_bytes=pcm,
            absolute_ts="2026-05-22T00:00:00Z",
            relative_ts=0.0,
        )
        await sink.on_close(meeting_id="m1", reason="end")
        # ファイルが作られて中身が一致
        files = os.listdir(tmp)
        assert len(files) == 1
        with open(os.path.join(tmp, files[0]), "rb") as f:
            assert f.read() == pcm


async def test_file_sink_push_without_open_is_noop() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        sink = FileAudioSink(output_dir=tmp)
        # on_open を呼ばずに push しても例外を出さない
        await sink.push(
            meeting_id="never-opened",
            pcm_bytes=b"\x00",
            absolute_ts="",
            relative_ts=0.0,
        )
        assert os.listdir(tmp) == []


def test_build_audio_sink_noop() -> None:
    assert isinstance(build_audio_sink("noop"), NoopAudioSink)


def test_build_audio_sink_file() -> None:
    sink = build_audio_sink("file")
    assert isinstance(sink, FileAudioSink)


def test_build_audio_sink_azure_speech_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        build_audio_sink("azure_speech")


def test_build_audio_sink_unknown() -> None:
    with pytest.raises(ValueError):
        build_audio_sink("does-not-exist")
