import pytest
from unittest.mock import AsyncMock, MagicMock
from src.api.recall_router import RecallWebhookRouter


def make_request(body: dict) -> MagicMock:
    req = MagicMock()
    req.json = AsyncMock(return_value=body)
    return req


VALID_PAYLOAD = {
    "event": "transcript.data",
    "data": {
        "bot": {"id": "bot_abc123"},
        "data": {
            "speaker": "田中 太郎",
            "words": [{"text": "この"}, {"text": "仕様は"}],
            "participant": {"id": 99, "name": "田中 太郎"},
        },
    },
}


@pytest.fixture
def orchestrator():
    mock = MagicMock()
    mock.process = AsyncMock()
    return mock


@pytest.fixture
def cosmos():
    mock = MagicMock()
    mock.save_utterance = AsyncMock()
    return mock


@pytest.fixture
def router(orchestrator):
    return RecallWebhookRouter(orchestrator=orchestrator)


@pytest.fixture
def router_with_cosmos(orchestrator, cosmos):
    return RecallWebhookRouter(orchestrator=orchestrator, cosmos=cosmos)


@pytest.mark.asyncio
async def test_valid_payload_calls_orchestrator(router, orchestrator):
    req = make_request(VALID_PAYLOAD)
    resp = await router._handle(req)
    assert resp.status == 202
    orchestrator.process.assert_called_once()
    utterance = orchestrator.process.call_args[0][0]
    assert utterance.meeting_id == "bot_abc123"
    assert utterance.speaker_name == "田中 太郎"
    assert utterance.speaker_id == "99"
    assert utterance.text == "この仕様は"


@pytest.mark.asyncio
async def test_non_target_event_is_ignored(router, orchestrator):
    req = make_request({"event": "bot.status_change", "data": {}})
    resp = await router._handle(req)
    assert resp.status == 200
    orchestrator.process.assert_not_called()


@pytest.mark.asyncio
async def test_empty_words_is_ignored(router, orchestrator):
    payload = {
        "event": "transcript.data",
        "data": {
            "bot": {"id": "bot_abc123"},
            "data": {
                "words": [],
                "participant": {"id": 1, "name": "田中 太郎"},
            },
        },
    }
    req = make_request(payload)
    resp = await router._handle(req)
    assert resp.status == 200
    orchestrator.process.assert_not_called()


@pytest.mark.asyncio
async def test_cosmos_none_does_not_error(router, orchestrator):
    # router fixture has cosmos=None — must not raise
    req = make_request(VALID_PAYLOAD)
    resp = await router._handle(req)
    assert resp.status == 202
    orchestrator.process.assert_called_once()


@pytest.mark.asyncio
async def test_orchestrator_exception_returns_202(router, orchestrator):
    orchestrator.process.side_effect = RuntimeError("boom")
    req = make_request(VALID_PAYLOAD)
    resp = await router._handle(req)
    assert resp.status == 202


@pytest.mark.asyncio
async def test_cosmos_save_called_when_provided(router_with_cosmos, orchestrator, cosmos):
    req = make_request(VALID_PAYLOAD)
    resp = await router_with_cosmos._handle(req)
    assert resp.status == 202
    cosmos.save_utterance.assert_called_once()
    utterance = cosmos.save_utterance.call_args[0][0]
    assert utterance.meeting_id == "bot_abc123"
    assert utterance.speaker_name == "田中 太郎"


@pytest.mark.asyncio
async def test_cosmos_exception_still_calls_orchestrator(router_with_cosmos, orchestrator, cosmos):
    cosmos.save_utterance.side_effect = RuntimeError("cosmos down")
    req = make_request(VALID_PAYLOAD)
    resp = await router_with_cosmos._handle(req)
    assert resp.status == 202
    orchestrator.process.assert_called_once()


@pytest.mark.asyncio
async def test_blank_text_after_strip_is_ignored(router, orchestrator):
    payload = {
        "event": "transcript.data",
        "data": {
            "bot": {"id": "bot_abc123"},
            "data": {
                "words": [{"text": "   "}],
                "participant": {"id": 1, "name": "田中 太郎"},
            },
        },
    }
    req = make_request(payload)
    resp = await router._handle(req)
    assert resp.status == 200
    orchestrator.process.assert_not_called()
