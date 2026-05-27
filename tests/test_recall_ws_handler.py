# tests/test_recall_ws_handler.py
"""
RecallWsHandler の単体・統合テスト。

- 認証ヘッダ検証
- bot_id 解決 (inmem hit / cosmos fallback / miss)
- イベント分岐 (audio_mixed_raw.data / transcript.data / unknown)
- AudioSink フックの呼び出し
"""
import asyncio
import base64
import hashlib
import hmac
import json
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import WSCloseCode, WSMsgType, web
from aiohttp.test_utils import TestClient, TestServer

from src.transcript.recall_ws_handler import RecallWsHandler


_FAKE_SECRET_BYTES = b"super-secret-key-for-tests-1234567890"
_FAKE_SECRET = "whsec_" + base64.b64encode(_FAKE_SECRET_BYTES).decode("ascii")
_FIXED_NOW = 1_700_000_000.0


def _sign_upgrade(msg_id: str, ts: int, secret: bytes = _FAKE_SECRET_BYTES) -> str:
    signed = f"{msg_id}.{ts}.".encode("utf-8")  # body 空
    sig = base64.b64encode(hmac.new(secret, signed, hashlib.sha256).digest()).decode("ascii")
    return f"v1,{sig}"


def _audio_envelope(bot_id: str, pcm: bytes, *, absolute: str = "2026-05-22T00:00:00Z", relative: float = 0.1) -> dict:
    return {
        "event": "audio_mixed_raw.data",
        "data": {
            "data": {
                "buffer": base64.b64encode(pcm).decode("ascii"),
                "timestamp": {"absolute": absolute, "relative": relative},
            },
            "bot": {"id": bot_id, "metadata": {}},
            "recording": {"id": "rec_x", "metadata": {}},
            "realtime_endpoint": {"id": "rte_x", "metadata": {}},
            "audio_mixed": {"id": "amx_x", "metadata": {}},
        },
    }


def _transcript_envelope(bot_id: str, *, is_final: bool = True, words=("こんにちは",), speaker_id: int = 1, speaker_name: str = "田中 太郎") -> dict:
    return {
        "event": "transcript.data",
        "data": {
            "data": {
                "is_final": is_final,
                "words": [{"text": w} for w in words],
                "language_code": "ja",
                "participant": {"id": speaker_id, "name": speaker_name, "is_host": False},
            },
            "bot": {"id": bot_id, "metadata": {}},
            "transcript": {"id": "trn_x", "metadata": {}},
            "recording": {"id": "rec_x", "metadata": {}},
        },
    }


# ----------------------------------------------------------------------
# AudioSink double
# ----------------------------------------------------------------------

class _SinkSpy:
    def __init__(self) -> None:
        self.opened: list[tuple[str, str, int]] = []
        self.pushes: list[bytes] = []
        self.closed: list[tuple[str, str]] = []

    async def on_open(self, *, meeting_id: str, bot_id: str, sample_rate: int) -> None:
        self.opened.append((meeting_id, bot_id, sample_rate))

    async def push(self, *, meeting_id: str, pcm_bytes: bytes, absolute_ts: str, relative_ts: float) -> None:
        self.pushes.append(pcm_bytes)

    async def on_close(self, *, meeting_id: str, reason: str) -> None:
        self.closed.append((meeting_id, reason))


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------

@pytest.fixture
def cosmos():
    c = MagicMock()
    c.save_utterance = AsyncMock()
    c.find_meeting_id_by_recall_bot_id = AsyncMock(return_value=None)
    return c


@pytest.fixture
def webhook_handler_stub():
    """RecallWebhookHandler の最小スタブ。is_bot_registered と _bot_to_meeting だけあればよい。"""
    h = MagicMock()
    h._bot_to_meeting = {}
    h.is_bot_registered = lambda bot_id: bot_id in h._bot_to_meeting
    return h


@pytest.fixture
def on_utterance():
    return AsyncMock()


@pytest.fixture
def sink():
    return _SinkSpy()


@pytest.fixture
def handler(cosmos, on_utterance, sink, webhook_handler_stub):
    return RecallWsHandler(
        cosmos_client=cosmos,
        on_utterance=on_utterance,
        audio_sink=sink,
        webhook_secret=_FAKE_SECRET,
        webhook_handler=webhook_handler_stub,
        clock=lambda: _FIXED_NOW,
        heartbeat_seconds=1000.0,  # テスト中の自動 ping を抑止
    )


# ----------------------------------------------------------------------
# Test app helper
# ----------------------------------------------------------------------

async def _make_client(handler: RecallWsHandler) -> tuple[TestClient, TestServer]:
    app = web.Application()
    app.router.add_get("/api/recall/ws", handler.handle)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    return client, server


# ----------------------------------------------------------------------
# Tests: Upgrade auth
# ----------------------------------------------------------------------

async def test_upgrade_rejected_without_auth_headers(handler) -> None:
    client, server = await _make_client(handler)
    try:
        resp = await client.get("/api/recall/ws")
        assert resp.status == 401
    finally:
        await client.close()
        await server.close()


async def test_upgrade_rejected_with_bad_signature(handler) -> None:
    client, server = await _make_client(handler)
    try:
        resp = await client.get(
            "/api/recall/ws",
            headers={
                "webhook-id": "msg-1",
                "webhook-timestamp": str(int(_FIXED_NOW)),
                "webhook-signature": "v1,bad-sig",
            },
        )
        assert resp.status == 401
    finally:
        await client.close()
        await server.close()


async def test_upgrade_rejected_with_old_timestamp(handler) -> None:
    client, server = await _make_client(handler)
    old_ts = int(_FIXED_NOW) - 10_000  # 5min より十分古い
    try:
        resp = await client.get(
            "/api/recall/ws",
            headers={
                "webhook-id": "msg-old",
                "webhook-timestamp": str(old_ts),
                "webhook-signature": _sign_upgrade("msg-old", old_ts),
            },
        )
        assert resp.status == 401
    finally:
        await client.close()
        await server.close()


async def test_upgrade_accepts_svix_prefixed_headers(handler) -> None:
    client, server = await _make_client(handler)
    ts = int(_FIXED_NOW)
    try:
        ws = await client.ws_connect(
            "/api/recall/ws",
            headers={
                "svix-id": "msg-svix",
                "svix-timestamp": str(ts),
                "svix-signature": _sign_upgrade("msg-svix", ts),
            },
        )
        assert ws.closed is False
        await ws.close()
    finally:
        await client.close()
        await server.close()


# ----------------------------------------------------------------------
# Tests: bot_id resolution
# ----------------------------------------------------------------------

async def test_unknown_bot_falls_back_to_bot_id_as_meeting_id(handler, cosmos, sink) -> None:
    """mapping 未登録の bot からの接続でも切らず、bot_id を meeting_id として処理する。"""
    cosmos.find_meeting_id_by_recall_bot_id = AsyncMock(return_value=None)
    client, server = await _make_client(handler)
    ts = int(_FIXED_NOW)
    pcm = b"\xaa\xbb" * 100
    try:
        ws = await client.ws_connect(
            "/api/recall/ws",
            headers={
                "webhook-id": "msg-1",
                "webhook-timestamp": str(ts),
                "webhook-signature": _sign_upgrade("msg-1", ts),
            },
        )
        await ws.send_json(_audio_envelope("bot-unknown", pcm))
        for _ in range(20):
            if sink.pushes:
                break
            await asyncio.sleep(0.05)
        await ws.close()
    finally:
        await client.close()
        await server.close()
    # 切断されずに音声が AudioSink に push されていること
    assert sink.opened == [("bot-unknown", "bot-unknown", 16_000)]
    assert sink.pushes == [pcm]


async def test_inmemory_bot_mapping_takes_precedence(handler, webhook_handler_stub, sink) -> None:
    webhook_handler_stub._bot_to_meeting["bot-A"] = "meet-A"
    client, server = await _make_client(handler)
    ts = int(_FIXED_NOW)
    try:
        ws = await client.ws_connect(
            "/api/recall/ws",
            headers={
                "webhook-id": "msg-1",
                "webhook-timestamp": str(ts),
                "webhook-signature": _sign_upgrade("msg-1", ts),
            },
        )
        pcm = b"\x10\x00" * 320  # 20 ms 分
        await ws.send_json(_audio_envelope("bot-A", pcm))
        # サーバ側処理を進めるための短い待機
        for _ in range(20):
            if sink.pushes:
                break
            await asyncio.sleep(0.05)
        await ws.close()
    finally:
        await client.close()
        await server.close()
    assert sink.opened == [("meet-A", "bot-A", 16_000)]
    assert sink.pushes == [pcm]
    assert sink.closed[0][0] == "meet-A"


async def test_cosmos_fallback_resolves_meeting_id(handler, cosmos, sink) -> None:
    cosmos.find_meeting_id_by_recall_bot_id = AsyncMock(return_value="meet-B")
    client, server = await _make_client(handler)
    ts = int(_FIXED_NOW)
    try:
        ws = await client.ws_connect(
            "/api/recall/ws",
            headers={
                "webhook-id": "msg-2",
                "webhook-timestamp": str(ts),
                "webhook-signature": _sign_upgrade("msg-2", ts),
            },
        )
        pcm = b"\xab\xcd" * 100
        await ws.send_json(_audio_envelope("bot-B", pcm))
        for _ in range(20):
            if sink.pushes:
                break
            await asyncio.sleep(0.05)
        await ws.close()
    finally:
        await client.close()
        await server.close()
    cosmos.find_meeting_id_by_recall_bot_id.assert_awaited_once_with("bot-B")
    assert sink.opened[0][0] == "meet-B"
    assert sink.pushes == [pcm]


# ----------------------------------------------------------------------
# Tests: transcript dispatch
# ----------------------------------------------------------------------

async def test_transcript_data_invokes_pipeline(handler, webhook_handler_stub, cosmos, on_utterance) -> None:
    webhook_handler_stub._bot_to_meeting["bot-T"] = "meet-T"
    client, server = await _make_client(handler)
    ts = int(_FIXED_NOW)
    try:
        ws = await client.ws_connect(
            "/api/recall/ws",
            headers={
                "webhook-id": "msg-T",
                "webhook-timestamp": str(ts),
                "webhook-signature": _sign_upgrade("msg-T", ts),
            },
        )
        await ws.send_json(_transcript_envelope("bot-T", words=("仕様", "は")))
        for _ in range(20):
            if on_utterance.await_count:
                break
            await asyncio.sleep(0.05)
        await ws.close()
    finally:
        await client.close()
        await server.close()
    assert cosmos.save_utterance.await_count == 1
    saved = cosmos.save_utterance.await_args.args[0]
    assert saved.text == "仕様は"
    assert saved.meeting_id == "meet-T"
    assert saved.speaker_name == "田中 太郎"
    on_utterance.assert_awaited_once()


async def test_non_final_transcript_is_ignored(handler, webhook_handler_stub, cosmos, on_utterance) -> None:
    webhook_handler_stub._bot_to_meeting["bot-T2"] = "meet-T2"
    client, server = await _make_client(handler)
    ts = int(_FIXED_NOW)
    try:
        ws = await client.ws_connect(
            "/api/recall/ws",
            headers={
                "webhook-id": "msg-NF",
                "webhook-timestamp": str(ts),
                "webhook-signature": _sign_upgrade("msg-NF", ts),
            },
        )
        await ws.send_json(_transcript_envelope("bot-T2", is_final=False))
        await asyncio.sleep(0.2)
        await ws.close()
    finally:
        await client.close()
        await server.close()
    assert cosmos.save_utterance.await_count == 0
    assert on_utterance.await_count == 0


async def test_realtime_ws_transcript_without_is_final_is_accepted(
    handler, webhook_handler_stub, cosmos, on_utterance
) -> None:
    """
    Recall realtime WebSocket は transcript.data の data.data に is_final を含めない。
    event 名で final/partial を区別する設計。
    欠落は確定扱いとして処理されることを保証する (regression テスト)。
    """
    webhook_handler_stub._bot_to_meeting["bot-RT"] = "meet-RT"
    # is_final フィールドを意図的に欠落させた envelope
    envelope = {
        "event": "transcript.data",
        "data": {
            "data": {
                # NOTE: is_final intentionally omitted (matches Recall WS realtime payload)
                "words": [{"text": "こんにちは"}, {"text": "テスト"}],
                "language_code": "ja",
                "participant": {"id": 1, "name": "田中 太郎", "is_host": False},
            },
            "bot": {"id": "bot-RT", "metadata": {}},
            "transcript": {"id": "trn_x", "metadata": {}},
            "recording": {"id": "rec_x", "metadata": {}},
            "realtime_endpoint": {"id": "rte_x", "metadata": {}},
        },
    }
    client, server = await _make_client(handler)
    ts = int(_FIXED_NOW)
    try:
        ws = await client.ws_connect(
            "/api/recall/ws",
            headers={
                "webhook-id": "msg-RT",
                "webhook-timestamp": str(ts),
                "webhook-signature": _sign_upgrade("msg-RT", ts),
            },
        )
        await ws.send_json(envelope)
        for _ in range(20):
            if on_utterance.await_count:
                break
            await asyncio.sleep(0.05)
        await ws.close()
    finally:
        await client.close()
        await server.close()
    assert cosmos.save_utterance.await_count == 1
    saved = cosmos.save_utterance.await_args.args[0]
    assert saved.text == "こんにちはテスト"
    on_utterance.assert_awaited_once()


async def test_invalid_json_does_not_close_connection(handler, webhook_handler_stub, sink) -> None:
    webhook_handler_stub._bot_to_meeting["bot-J"] = "meet-J"
    client, server = await _make_client(handler)
    ts = int(_FIXED_NOW)
    try:
        ws = await client.ws_connect(
            "/api/recall/ws",
            headers={
                "webhook-id": "msg-J",
                "webhook-timestamp": str(ts),
                "webhook-signature": _sign_upgrade("msg-J", ts),
            },
        )
        await ws.send_str("not json")
        # 接続継続を確認するため後続メッセージ
        await ws.send_json(_audio_envelope("bot-J", b"\x00\x00\x00\x00"))
        for _ in range(20):
            if sink.pushes:
                break
            await asyncio.sleep(0.05)
        await ws.close()
    finally:
        await client.close()
        await server.close()
    assert sink.pushes == [b"\x00\x00\x00\x00"]
