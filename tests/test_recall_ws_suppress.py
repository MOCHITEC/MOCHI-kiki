import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def _run(coro):
    return asyncio.run(coro)


def _make_session(meeting_id="m1"):
    """Return a minimal _ConnectionState-like mock."""
    import collections
    from unittest.mock import MagicMock
    session = MagicMock()
    session.meeting_id = meeting_id
    session.transcript_partial_count = 0
    session.transcript_final_count = 0
    session.transcript_extract_none_count = 0
    return session


def _make_handler(suppress: bool):
    """Return a RecallWsHandler with a mock on_utterance."""
    from src.transcript.recall_ws_handler import RecallWsHandler
    mock_cb = AsyncMock()
    mock_cosmos = MagicMock()
    mock_cosmos.save_utterance = AsyncMock()
    handler = RecallWsHandler(
        cosmos_client=mock_cosmos,
        on_utterance=mock_cb,
        suppress_native_transcript=suppress,
    )
    handler._mock_cb = mock_cb
    return handler


def test_suppress_true_skips_on_utterance():
    """With suppress=True, _handle_transcript must NOT call on_utterance."""
    handler = _make_handler(suppress=True)
    session = _make_session(meeting_id="m1")
    payload = {
        "event": "transcript.data",
        "data": {
            "data": {
                "words": [{"text": "こんにちは"}],
                "participant": {"id": 1, "name": "Alice"},
            },
            "bot": {"id": "b1"},
        },
    }
    _run(handler._handle_transcript(session, payload, partial=False))
    handler._mock_cb.assert_not_awaited()


def test_suppress_false_allows_on_utterance():
    """With suppress=False (default), _handle_transcript calls on_utterance normally."""
    handler = _make_handler(suppress=False)
    session = _make_session(meeting_id="m1")
    payload = {
        "event": "transcript.data",
        "data": {
            "data": {
                "words": [{"text": "こんにちは"}],
                "participant": {"id": 1, "name": "Alice"},
            },
            "bot": {"id": "b1"},
        },
    }
    _run(handler._handle_transcript(session, payload, partial=False))
    handler._mock_cb.assert_awaited_once()


def test_suppress_default_is_false():
    """RecallWsHandler() with no suppress kwarg defaults to suppress=False."""
    from src.transcript.recall_ws_handler import RecallWsHandler
    mock_cb = AsyncMock()
    mock_cosmos = MagicMock()
    handler = RecallWsHandler(cosmos_client=mock_cosmos, on_utterance=mock_cb)
    assert handler._suppress_native_transcript is False
