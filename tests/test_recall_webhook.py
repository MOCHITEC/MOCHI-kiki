# tests/test_recall_webhook.py
import base64
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.transcript.recall_source import (
    RecallSecretError,
    RecallWebhookHandler,
)


_FAKE_SECRET_BYTES = b"super-secret-key-for-tests-1234567890"
_FAKE_SECRET = "whsec_" + base64.b64encode(_FAKE_SECRET_BYTES).decode("ascii")
_FIXED_NOW = 1_700_000_000.0


def _sign(body: bytes, msg_id: str, ts: int, secret_bytes: bytes = _FAKE_SECRET_BYTES) -> str:
    signed = f"{msg_id}.{ts}.".encode("utf-8") + body
    sig = base64.b64encode(hmac.new(secret_bytes, signed, hashlib.sha256).digest()).decode("ascii")
    return f"v1,{sig}"


def _make_request(headers: dict, body: bytes) -> MagicMock:
    req = MagicMock()
    req.headers = headers
    req.content_length = len(body)
    req.read = AsyncMock(return_value=body)
    return req


@pytest.fixture
def cosmos():
    c = MagicMock()
    c.save_utterance = AsyncMock()
    return c


@pytest.fixture
def on_utterance():
    return AsyncMock()


@pytest.fixture
def handler(cosmos, on_utterance):
    h = RecallWebhookHandler(
        cosmos_client=cosmos,
        on_utterance=on_utterance,
        webhook_secret=_FAKE_SECRET,
        clock=lambda: _FIXED_NOW,
    )
    h.register_bot("bot-001", "meet-001")
    return h


def _signed_request(body_dict, msg_id="msg-1", ts=int(_FIXED_NOW)):
    body = json.dumps(body_dict).encode("utf-8") if isinstance(body_dict, dict) else body_dict
    headers = {
        "svix-id": msg_id,
        "svix-timestamp": str(ts),
        "svix-signature": _sign(body, msg_id, ts),
    }
    return _make_request(headers, body)


@pytest.mark.asyncio
async def test_transcript_data_final_dispatches_utterance(handler, cosmos, on_utterance):
    payload = {
        "event": "transcript.data",
        "data": {
            "bot": {"id": "bot-001"},
            "data": {
                "is_final": True,
                "words": [{"text": "認証フロー"}, {"text": "について"}],
                "participant": {"id": 12345, "name": "田中 太郎"},
            },
        },
    }
    res = await handler.handle(_signed_request(payload))
    assert res.status == 200
    cosmos.save_utterance.assert_awaited_once()
    on_utterance.assert_awaited_once()
    utterance = on_utterance.await_args[0][0]
    assert utterance.meeting_id == "meet-001"
    # 日本語は空白なしで連結
    assert utterance.text == "認証フローについて"
    assert utterance.speaker_id == "12345"
    assert utterance.speaker_name == "田中 太郎"


@pytest.mark.asyncio
async def test_partial_transcript_is_ignored(handler, cosmos, on_utterance):
    payload = {
        "event": "transcript.data",
        "data": {
            "bot": {"id": "bot-001"},
            "data": {
                "is_final": False,
                "words": [{"text": "途中"}],
                "participant": {"id": 1, "name": "X"},
            },
        },
    }
    res = await handler.handle(_signed_request(payload))
    assert res.status == 200
    cosmos.save_utterance.assert_not_called()
    on_utterance.assert_not_called()


@pytest.mark.asyncio
async def test_unregistered_bot_is_ignored(handler, cosmos, on_utterance):
    payload = {
        "event": "transcript.data",
        "data": {
            "bot": {"id": "bot-UNKNOWN"},
            "data": {
                "is_final": True,
                "words": [{"text": "hi"}],
                "participant": {"id": 1, "name": "X"},
            },
        },
    }
    res = await handler.handle(_signed_request(payload))
    assert res.status == 200
    cosmos.save_utterance.assert_not_called()
    on_utterance.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_signature_returns_401(handler, cosmos):
    body = json.dumps({"event": "transcript.data"}).encode("utf-8")
    headers = {
        "svix-id": "m",
        "svix-timestamp": str(int(_FIXED_NOW)),
        "svix-signature": "v1,not-a-valid-signature",
    }
    res = await handler.handle(_make_request(headers, body))
    assert res.status == 401
    # 情報漏洩しない: 本文なし
    assert res.body is None or res.body == b""
    cosmos.save_utterance.assert_not_called()


@pytest.mark.asyncio
async def test_replay_old_timestamp_rejected(handler):
    body = json.dumps({"event": "transcript.data"}).encode("utf-8")
    old_ts = int(_FIXED_NOW) - 6 * 60
    headers = {
        "svix-id": "m",
        "svix-timestamp": str(old_ts),
        "svix-signature": _sign(body, "m", old_ts),
    }
    res = await handler.handle(_make_request(headers, body))
    assert res.status == 401


@pytest.mark.asyncio
async def test_replay_future_timestamp_rejected(handler):
    """未来側のクロックスキューも同じ窓でガード。"""
    body = json.dumps({"event": "transcript.data"}).encode("utf-8")
    future_ts = int(_FIXED_NOW) + 6 * 60
    headers = {
        "svix-id": "m",
        "svix-timestamp": str(future_ts),
        "svix-signature": _sign(body, "m", future_ts),
    }
    res = await handler.handle(_make_request(headers, body))
    assert res.status == 401


@pytest.mark.asyncio
async def test_replay_boundary_accepted(handler, on_utterance):
    """境界 (= 5分ジャスト) は許可。"""
    payload = {
        "event": "transcript.data",
        "data": {
            "bot": {"id": "bot-001"},
            "data": {
                "is_final": True,
                "words": [{"text": "ok"}],
                "participant": {"id": 1, "name": "X"},
            },
        },
    }
    body = json.dumps(payload).encode("utf-8")
    boundary_ts = int(_FIXED_NOW) - 5 * 60
    headers = {
        "svix-id": "boundary",
        "svix-timestamp": str(boundary_ts),
        "svix-signature": _sign(body, "boundary", boundary_ts),
    }
    res = await handler.handle(_make_request(headers, body))
    assert res.status == 200
    on_utterance.assert_awaited_once()


@pytest.mark.asyncio
async def test_duplicate_svix_id_is_ignored(handler, cosmos, on_utterance):
    """リプレイ防御: 同じ svix-id を 2回受け取ったら 2回目は破棄。"""
    payload = {
        "event": "transcript.data",
        "data": {
            "bot": {"id": "bot-001"},
            "data": {
                "is_final": True,
                "words": [{"text": "hi"}],
                "participant": {"id": 1, "name": "X"},
            },
        },
    }
    req1 = _signed_request(payload, msg_id="dup-id")
    await handler.handle(req1)
    req2 = _signed_request(payload, msg_id="dup-id")
    res = await handler.handle(req2)
    assert res.status == 200
    assert cosmos.save_utterance.await_count == 1
    assert on_utterance.await_count == 1


@pytest.mark.asyncio
async def test_invalid_json_returns_400(handler):
    body = b"{not-json"
    msg_id = "m"
    ts = int(_FIXED_NOW)
    headers = {
        "svix-id": msg_id,
        "svix-timestamp": str(ts),
        "svix-signature": _sign(body, msg_id, ts),
    }
    res = await handler.handle(_make_request(headers, body))
    assert res.status == 400


@pytest.mark.asyncio
async def test_payload_not_dict_returns_400(handler):
    body = b'["not", "a", "dict"]'
    msg_id = "m"
    ts = int(_FIXED_NOW)
    headers = {
        "svix-id": msg_id,
        "svix-timestamp": str(ts),
        "svix-signature": _sign(body, msg_id, ts),
    }
    res = await handler.handle(_make_request(headers, body))
    assert res.status == 400


@pytest.mark.asyncio
async def test_body_too_large_rejected(handler):
    """content_length が上限を超えていれば、body 読まずに 413。"""
    headers = {"svix-id": "m", "svix-timestamp": str(int(_FIXED_NOW)), "svix-signature": "v1,x"}
    req = MagicMock()
    req.headers = headers
    req.content_length = 999_999
    req.read = AsyncMock(return_value=b"")  # 呼ばれないはず
    res = await handler.handle(req)
    assert res.status == 413


@pytest.mark.asyncio
async def test_bot_status_done_unregisters(handler):
    payload = {
        "event": "bot.status_change",
        "data": {
            "bot": {"id": "bot-001"},
            "status": "done",
        },
    }
    res = await handler.handle(_signed_request(payload))
    assert res.status == 200
    assert not handler.is_bot_registered("bot-001")


@pytest.mark.asyncio
async def test_bot_status_fatal_unregisters(handler):
    payload = {
        "event": "bot.status_change",
        "data": {"bot": {"id": "bot-001"}, "status": "fatal"},
    }
    res = await handler.handle(_signed_request(payload))
    assert res.status == 200
    assert not handler.is_bot_registered("bot-001")


@pytest.mark.asyncio
async def test_bot_status_dict_form(handler):
    """Recall が {code: ...} オブジェクトで送ってきても受け付ける。"""
    payload = {
        "event": "bot.status_change",
        "data": {"bot": {"id": "bot-001"}, "status": {"code": "done"}},
    }
    res = await handler.handle(_signed_request(payload))
    assert res.status == 200
    assert not handler.is_bot_registered("bot-001")


@pytest.mark.asyncio
async def test_missing_secret_fails_closed(cosmos, on_utterance):
    handler = RecallWebhookHandler(
        cosmos_client=cosmos,
        on_utterance=on_utterance,
        webhook_secret=None,
        clock=lambda: _FIXED_NOW,
    )
    handler.register_bot("bot-001", "meet-001")
    body = json.dumps({"event": "transcript.data"}).encode("utf-8")
    headers = {
        "svix-id": "m",
        "svix-timestamp": str(int(_FIXED_NOW)),
        "svix-signature": "v1,whatever",
    }
    res = await handler.handle(_make_request(headers, body))
    assert res.status == 401


@pytest.mark.asyncio
async def test_missing_secret_rejects_all_requests(cosmos, on_utterance):
    """secret 未設定の場合は insecure_mode 脱出弁がないので全て 401。"""
    handler = RecallWebhookHandler(
        cosmos_client=cosmos,
        on_utterance=on_utterance,
        webhook_secret=None,
        clock=lambda: _FIXED_NOW,
    )
    handler.register_bot("bot-001", "meet-001")
    body = b'{"event":"transcript.data"}'
    res = await handler.handle(_make_request({}, body))
    assert res.status == 401
    on_utterance.assert_not_awaited()


@pytest.mark.asyncio
async def test_participant_name_fallback(handler, on_utterance):
    payload = {
        "event": "transcript.data",
        "data": {
            "bot": {"id": "bot-001"},
            "data": {
                "is_final": True,
                "words": [{"text": "hi"}],
                "participant": {"id": 1},  # name 欠落
            },
        },
    }
    res = await handler.handle(_signed_request(payload))
    assert res.status == 200
    utterance = on_utterance.await_args[0][0]
    assert utterance.speaker_name == "不明"


@pytest.mark.asyncio
async def test_participant_id_missing_fallback(handler, on_utterance):
    """participant.id が無いケースは "unknown" にフォールバック。"""
    payload = {
        "event": "transcript.data",
        "data": {
            "bot": {"id": "bot-001"},
            "data": {
                "is_final": True,
                "words": [{"text": "hi"}],
                "participant": {},
            },
        },
    }
    res = await handler.handle(_signed_request(payload))
    assert res.status == 200
    utterance = on_utterance.await_args[0][0]
    assert utterance.speaker_id == "unknown"


@pytest.mark.asyncio
async def test_participant_id_none_fallback(handler, on_utterance):
    """participant.id が明示的に None でも "unknown"。"""
    payload = {
        "event": "transcript.data",
        "data": {
            "bot": {"id": "bot-001"},
            "data": {
                "is_final": True,
                "words": [{"text": "hi"}],
                "participant": {"id": None, "name": None},
            },
        },
    }
    res = await handler.handle(_signed_request(payload))
    assert res.status == 200
    utterance = on_utterance.await_args[0][0]
    assert utterance.speaker_id == "unknown"
    assert utterance.speaker_name == "不明"


@pytest.mark.asyncio
async def test_long_name_is_truncated(handler, on_utterance):
    long_name = "あ" * 1000
    payload = {
        "event": "transcript.data",
        "data": {
            "bot": {"id": "bot-001"},
            "data": {
                "is_final": True,
                "words": [{"text": "hi"}],
                "participant": {"id": 1, "name": long_name},
            },
        },
    }
    res = await handler.handle(_signed_request(payload))
    assert res.status == 200
    utterance = on_utterance.await_args[0][0]
    assert len(utterance.speaker_name) <= 200


@pytest.mark.asyncio
async def test_words_empty_returns_200(handler, on_utterance):
    payload = {
        "event": "transcript.data",
        "data": {
            "bot": {"id": "bot-001"},
            "data": {
                "is_final": True,
                "words": [],
                "participant": {"id": 1, "name": "X"},
            },
        },
    }
    res = await handler.handle(_signed_request(payload))
    assert res.status == 200
    on_utterance.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_event_returns_200(handler, on_utterance):
    payload = {"event": "some.future.event", "data": {}}
    res = await handler.handle(_signed_request(payload))
    assert res.status == 200
    on_utterance.assert_not_called()


@pytest.mark.asyncio
async def test_missing_signature_header_rejected(handler):
    body = json.dumps({"event": "x"}).encode("utf-8")
    headers = {"svix-id": "m", "svix-timestamp": str(int(_FIXED_NOW))}
    res = await handler.handle(_make_request(headers, body))
    assert res.status == 401


@pytest.mark.asyncio
async def test_unsupported_signature_scheme_rejected(handler):
    body = json.dumps({"event": "x"}).encode("utf-8")
    msg_id = "m"
    ts = int(_FIXED_NOW)
    # v2 スキームは未対応扱い
    signed = f"{msg_id}.{ts}.".encode("utf-8") + body
    sig = base64.b64encode(hmac.new(_FAKE_SECRET_BYTES, signed, hashlib.sha256).digest()).decode("ascii")
    headers = {
        "svix-id": msg_id,
        "svix-timestamp": str(ts),
        "svix-signature": f"v2,{sig}",
    }
    res = await handler.handle(_make_request(headers, body))
    assert res.status == 401


@pytest.mark.asyncio
async def test_multi_signature_second_valid_accepted(handler, on_utterance):
    """'v1,bad v1,good' の形式で 2つ目が valid なら受け入れる。"""
    payload = {
        "event": "transcript.data",
        "data": {
            "bot": {"id": "bot-001"},
            "data": {
                "is_final": True,
                "words": [{"text": "hi"}],
                "participant": {"id": 1, "name": "X"},
            },
        },
    }
    body = json.dumps(payload).encode("utf-8")
    msg_id = "m"
    ts = int(_FIXED_NOW)
    good_sig = _sign(body, msg_id, ts)  # 'v1,<sig>'
    headers = {
        "svix-id": msg_id,
        "svix-timestamp": str(ts),
        "svix-signature": f"v1,AAAA {good_sig}",
    }
    res = await handler.handle(_make_request(headers, body))
    assert res.status == 200


@pytest.mark.asyncio
async def test_timestamp_with_garbage_rejected(handler):
    body = json.dumps({"event": "x"}).encode("utf-8")
    headers = {
        "svix-id": "m",
        "svix-timestamp": "not-a-number",
        "svix-signature": "v1,x",
    }
    res = await handler.handle(_make_request(headers, body))
    assert res.status == 401


@pytest.mark.asyncio
async def test_timestamp_huge_digits_rejected(handler):
    body = json.dumps({"event": "x"}).encode("utf-8")
    huge = "1" * 100  # 桁数上限超え
    headers = {
        "svix-id": "m",
        "svix-timestamp": huge,
        "svix-signature": "v1,x",
    }
    res = await handler.handle(_make_request(headers, body))
    assert res.status == 401


def test_malformed_secret_raises_at_construction(cosmos):
    with pytest.raises(RecallSecretError):
        RecallWebhookHandler(
            cosmos_client=cosmos,
            on_utterance=AsyncMock(),
            webhook_secret="whsec_!!!not-base64!!!",
        )


def test_register_bot_size_cap(cosmos):
    h = RecallWebhookHandler(
        cosmos_client=cosmos,
        on_utterance=AsyncMock(),
        webhook_secret=_FAKE_SECRET,
    )
    # 直接 dict を埋める（_MAX_BOT_MAPPINGS = 10000）
    from src.transcript.recall_source import _MAX_BOT_MAPPINGS
    for i in range(_MAX_BOT_MAPPINGS):
        h._bot_to_meeting[f"bot-{i}"] = f"meet-{i}"
    h.register_bot("overflow", "x")
    assert not h.is_bot_registered("overflow")


def test_word_join_skips_non_dict_and_non_string(cosmos):
    h = RecallWebhookHandler(
        cosmos_client=cosmos,
        on_utterance=AsyncMock(),
        webhook_secret=_FAKE_SECRET,
    )
    out = h._join_words([{"text": "a"}, "noise", {"text": 123}, {"text": "b"}])
    assert out == "ab"
