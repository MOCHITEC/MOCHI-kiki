# tests/test_recall_client.py
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from src.transcript.recall_client import RecallBotClient


class _FakeResponse:
    def __init__(self, status: int, json_body: dict | None = None, text_body: str = "", headers: dict | None = None):
        self.status = status
        self._json = json_body or {}
        self._text = text_body
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return self._json

    async def text(self):
        return self._text


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.closed = False

    def request(self, method, url, *, headers=None, json=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "json": json})
        if not self._responses:
            raise AssertionError("予定外のリクエスト")
        return self._responses.pop(0)

    async def close(self):
        self.closed = True


def _client(session: _FakeSession) -> RecallBotClient:
    return RecallBotClient(
        api_key="test-key",
        webhook_url="https://example.com/api/recall/webhook",
        region="ap-northeast-1",
        bot_name="MOCHI-kiki",
        language_code="ja",
        session=session,
    )


@pytest.mark.asyncio
async def test_create_bot_success_returns_id():
    session = _FakeSession([_FakeResponse(201, {"id": "bot-uuid-001"})])
    client = _client(session)
    bot_id = await client.create_bot("https://teams.microsoft.com/l/meetup-join/x")
    assert bot_id == "bot-uuid-001"

    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://ap-northeast-1.recall.ai/api/v1/bot/"
    assert call["headers"]["Authorization"] == "Token test-key"

    body = call["json"]
    assert body["meeting_url"] == "https://teams.microsoft.com/l/meetup-join/x"
    assert body["bot_name"] == "MOCHI-kiki"
    rt = body["recording_config"]["realtime_endpoints"][0]
    assert rt["type"] == "webhook"
    assert rt["url"] == "https://example.com/api/recall/webhook"
    assert "transcript.data" in rt["events"]
    provider = body["recording_config"]["transcript"]["provider"]
    assert provider["recallai_streaming"]["language_code"] == "ja"
    assert provider["recallai_streaming"]["mode"] == "prioritize_low_latency"


@pytest.mark.asyncio
async def test_create_bot_empty_meeting_url_returns_none():
    session = _FakeSession([])
    client = _client(session)
    assert await client.create_bot("") is None
    assert session.calls == []


@pytest.mark.asyncio
async def test_create_bot_401_returns_none():
    session = _FakeSession([_FakeResponse(401, text_body="unauthorized")])
    client = _client(session)
    assert await client.create_bot("https://teams.microsoft.com/l/x") is None


@pytest.mark.asyncio
async def test_create_bot_429_retries_then_succeeds():
    session = _FakeSession([
        _FakeResponse(429, text_body="rate limited"),
        _FakeResponse(201, {"id": "bot-after-retry"}),
    ])
    client = _client(session)
    bot_id = await client.create_bot("https://teams.microsoft.com/l/x")
    assert bot_id == "bot-after-retry"
    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_create_bot_5xx_three_times_returns_none():
    session = _FakeSession([
        _FakeResponse(503, text_body="x"),
        _FakeResponse(503, text_body="x"),
        _FakeResponse(503, text_body="x"),
    ])
    client = _client(session)
    assert await client.create_bot("https://teams.microsoft.com/l/x") is None
    assert len(session.calls) == 3


@pytest.mark.asyncio
async def test_create_bot_response_without_id_returns_none():
    session = _FakeSession([_FakeResponse(201, {"foo": "bar"})])
    client = _client(session)
    assert await client.create_bot("https://teams.microsoft.com/l/x") is None


@pytest.mark.asyncio
async def test_create_bot_id_not_string_returns_none():
    session = _FakeSession([_FakeResponse(201, {"id": 12345})])
    client = _client(session)
    assert await client.create_bot("https://teams.microsoft.com/l/x") is None


@pytest.mark.asyncio
async def test_leave_call_success():
    session = _FakeSession([_FakeResponse(200, {})])
    client = _client(session)
    assert await client.leave_call("bot-001") is True
    call = session.calls[0]
    assert call["url"].endswith("/api/v1/bot/bot-001/leave_call/")


@pytest.mark.asyncio
async def test_leave_call_204_success():
    session = _FakeSession([_FakeResponse(204)])
    client = _client(session)
    assert await client.leave_call("bot-001") is True


@pytest.mark.asyncio
async def test_leave_call_404_returns_false_no_retry():
    """404 はリトライ対象外。1回だけ呼ばれる。"""
    session = _FakeSession([_FakeResponse(404, text_body="not found")])
    client = _client(session)
    assert await client.leave_call("bot-deleted") is False
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_meeting_url_non_teams_rejected():
    session = _FakeSession([])  # 呼ばれないはず
    client = _client(session)
    assert await client.create_bot("https://zoom.us/j/12345") is None
    assert session.calls == []


@pytest.mark.asyncio
async def test_meeting_url_too_long_rejected():
    session = _FakeSession([])
    client = _client(session)
    too_long = "https://teams.microsoft.com/l/" + ("x" * 3000)
    assert await client.create_bot(too_long) is None
    assert session.calls == []


@pytest.mark.asyncio
async def test_meeting_url_log_injection_rejected():
    session = _FakeSession([])
    client = _client(session)
    assert await client.create_bot("https://teams.microsoft.com/l/x\nINJECTED") is None
    assert session.calls == []


def test_constructor_rejects_bad_region():
    with pytest.raises(ValueError):
        RecallBotClient(
            api_key="k",
            webhook_url="https://x/",
            region="evil.com/x",
        )


@pytest.mark.asyncio
async def test_response_not_dict_returns_empty_then_no_id():
    """成功レスポンスが list の場合、{} 扱いで bot_id 取得失敗 → None。"""
    session = _FakeSession([_FakeResponse(201, json_body=None)])
    # _FakeResponse の json() は dict を返す実装なので、別のフェイクで list を返す
    class _ListResp(_FakeResponse):
        async def json(self):
            return ["not", "a", "dict"]

    session = _FakeSession([_ListResp(201)])
    client = _client(session)
    assert await client.create_bot("https://teams.microsoft.com/l/x") is None


@pytest.mark.asyncio
async def test_owned_session_is_closed_on_close():
    """session=None で渡したら client.close() で内部 session が閉じる。"""
    client = RecallBotClient(api_key="k", webhook_url="https://x/")
    # 一度リクエスト発生時に session が作られる仕掛けなので、強制初期化
    await client._ensure_session()
    assert client._session is not None
    await client.close()
    assert client._session.closed


@pytest.mark.asyncio
async def test_retry_after_timeout_then_success():
    """timeout → 次の attempt で 201 を返す（exception path のリトライ）。"""
    import asyncio as _asyncio

    class _TimeoutOnce:
        def __init__(self):
            self.count = 0

        def request(self, *a, **kw):
            self.count += 1
            if self.count == 1:
                raise _asyncio.TimeoutError()
            return _FakeResponse(201, {"id": "bot-after-timeout"})

        closed = False
        async def close(self):
            self.closed = True

    s = _TimeoutOnce()
    client = RecallBotClient(api_key="k", webhook_url="https://x/", session=s)
    bot_id = await client.create_bot("https://teams.microsoft.com/l/y")
    assert bot_id == "bot-after-timeout"
    assert s.count == 2


@pytest.mark.asyncio
async def test_leave_call_empty_id_returns_false():
    session = _FakeSession([])
    client = _client(session)
    assert await client.leave_call("") is False


@pytest.mark.asyncio
async def test_constructor_rejects_non_https_webhook():
    with pytest.raises(ValueError):
        RecallBotClient(api_key="k", webhook_url="http://insecure/")


@pytest.mark.asyncio
async def test_constructor_rejects_empty_api_key():
    with pytest.raises(ValueError):
        RecallBotClient(api_key="", webhook_url="https://x/")


@pytest.mark.asyncio
async def test_client_error_returns_none():
    """ClientError 系も例外を漏らさず None を返す。"""

    class _ErrorSession:
        closed = False
        def request(self, *a, **kw):
            raise aiohttp.ClientError("boom")
        async def close(self):
            self.closed = True

    client = RecallBotClient(
        api_key="k",
        webhook_url="https://x/",
        session=_ErrorSession(),
    )
    assert await client.create_bot("https://teams.microsoft.com/l/m") is None
