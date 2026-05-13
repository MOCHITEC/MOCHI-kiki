# tests/test_clarification_session.py
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from src.kernel.clarification_session import ClarificationSession, SessionStatus
from src.storage.cosmos_client import CosmosClient


def test_session_creation():
    session = ClarificationSession.new(
        meeting_id="meet-001",
        utterance_id="utt-001",
        speaker_id="user-111",
        speaker_name="田中 太郎",
        original_text="あれをやっておいて",
        clarification_question="「あれ」とは具体的に何を指しますか？担当タスクの名前か番号を教えてください。",
    )
    assert session.status == SessionStatus.PENDING
    assert session.reply is None
    assert session.meeting_id == "meet-001"


def test_session_to_dict():
    session = ClarificationSession.new(
        meeting_id="meet-001",
        utterance_id="utt-001",
        speaker_id="user-111",
        speaker_name="田中 太郎",
        original_text="あれをやっておいて",
        clarification_question="「あれ」とは何ですか？",
    )
    d = session.to_dict()
    assert d["id"] == session.session_id
    assert d["status"] == "pending"
    assert d["reply"] is None


@pytest.fixture
def mock_cosmos_container():
    container = MagicMock()
    container.upsert_item = AsyncMock(return_value={})
    container.read_item = AsyncMock()
    container.query_items = MagicMock(return_value=iter([]))
    return container


@pytest.mark.asyncio
async def test_cosmos_save_clarification_session(mock_cosmos_container):
    cosmos = CosmosClient.__new__(CosmosClient)
    cosmos._clarification_sessions = mock_cosmos_container

    session = ClarificationSession.new(
        meeting_id="meet-001",
        utterance_id="utt-002",
        speaker_id="user-222",
        speaker_name="鈴木 花子",
        original_text="その辺はいい感じで",
        clarification_question="「その辺」とは具体的にどの範囲を指しますか？",
    )
    await cosmos.save_clarification_session(session)
    mock_cosmos_container.upsert_item.assert_called_once()
    call_args = mock_cosmos_container.upsert_item.call_args[0][0]
    assert call_args["id"] == session.session_id
