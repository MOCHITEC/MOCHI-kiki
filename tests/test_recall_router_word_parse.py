"""Verify the deprecated recall_router word-parsing bug is fixed.

The old code used ``isinstance(w, str)`` to filter words, but Recall.ai
sends ``words`` as ``list[dict]``.  That filter always produced an empty
string, so the handler silently dropped every real transcript.

This file tests the fixed behaviour: word-dicts must produce non-empty text
that is forwarded to the orchestrator.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.api.recall_router import RecallWebhookRouter


def _make_request(body: dict) -> MagicMock:
    req = MagicMock()
    req.json = AsyncMock(return_value=body)
    return req


def _make_router() -> tuple[RecallWebhookRouter, MagicMock]:
    orchestrator = MagicMock()
    orchestrator.process = AsyncMock()
    router = RecallWebhookRouter(orchestrator=orchestrator)
    return router, orchestrator


# ---------------------------------------------------------------------------
# The core regression test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_word_dicts_produce_non_empty_text():
    """words=[{"text": ...}] must extract non-empty text and call orchestrator."""
    router, orchestrator = _make_router()
    payload = {
        "event": "transcript.data",
        "data": {
            "bot": {"id": "bot-xyz"},
            "data": {
                "words": [{"text": "こんにちは"}, {"text": "世界"}],
                "participant": {"id": 42, "name": "Alice"},
            },
        },
    }
    req = _make_request(payload)
    resp = await router._handle(req)

    assert resp.status == 202, "expected 202 when valid word dicts are provided"
    orchestrator.process.assert_called_once()
    utterance = orchestrator.process.call_args[0][0]
    assert utterance.text == "こんにちは世界", (
        f"word dicts must be joined without spaces; got {utterance.text!r}"
    )
    assert utterance.meeting_id == "bot-xyz"
    assert utterance.speaker_name == "Alice"
    assert utterance.speaker_id == "42"


@pytest.mark.asyncio
async def test_word_dicts_japanese_no_space():
    """Japanese words joined without spaces (extract_utterance_from_transcript_data behaviour)."""
    router, orchestrator = _make_router()
    payload = {
        "event": "transcript.data",
        "data": {
            "bot": {"id": "bot1"},
            "data": {
                "words": [{"text": "認証"}, {"text": "フロー"}, {"text": "について"}],
                "participant": {"id": 1, "name": "Bob"},
            },
        },
    }
    resp = await router._handle(_make_request(payload))
    assert resp.status == 202
    utterance = orchestrator.process.call_args[0][0]
    assert utterance.text == "認証フローについて"


@pytest.mark.asyncio
async def test_partial_transcript_is_ignored():
    """is_final=False must be silently dropped (status 200, no orchestrator call)."""
    router, orchestrator = _make_router()
    payload = {
        "event": "transcript.data",
        "data": {
            "bot": {"id": "bot1"},
            "data": {
                "is_final": False,
                "words": [{"text": "途中"}],
                "participant": {"id": 1, "name": "X"},
            },
        },
    }
    resp = await router._handle(_make_request(payload))
    assert resp.status == 200
    orchestrator.process.assert_not_called()


@pytest.mark.asyncio
async def test_missing_is_final_treated_as_final():
    """is_final absent → treated as confirmed utterance (WS realtime form)."""
    router, orchestrator = _make_router()
    payload = {
        "event": "transcript.data",
        "data": {
            "bot": {"id": "bot1"},
            "data": {
                # no is_final key
                "words": [{"text": "hello"}],
                "participant": {"id": 1, "name": "X"},
            },
        },
    }
    resp = await router._handle(_make_request(payload))
    assert resp.status == 202
    orchestrator.process.assert_called_once()
