import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from src.models import Utterance, Meeting
from src.storage.cosmos_client import CosmosClient


@pytest.fixture
def mock_cosmos_container():
    container = MagicMock()
    container.upsert_item = AsyncMock(return_value={})
    container.read_item = AsyncMock()
    return container


@pytest.fixture
def cosmos_client(mock_cosmos_container):
    client = CosmosClient.__new__(CosmosClient)
    client._utterances = mock_cosmos_container
    client._meetings = mock_cosmos_container
    return client


@pytest.mark.asyncio
async def test_save_utterance(cosmos_client, mock_cosmos_container):
    u = Utterance.new(
        meeting_id="meet-001",
        speaker_id="user-111",
        speaker_name="田中 太郎",
        text="仕様の確認をしたい",
    )
    await cosmos_client.save_utterance(u)
    mock_cosmos_container.upsert_item.assert_called_once()
    call_args = mock_cosmos_container.upsert_item.call_args[0][0]
    assert call_args["id"] == u.utterance_id
    assert call_args["text"] == "仕様の確認をしたい"


@pytest.mark.asyncio
async def test_save_meeting(cosmos_client, mock_cosmos_container):
    m = Meeting(
        meeting_id="meet-001",
        thread_id="19:abc@thread.v2",
        organizer_id="user-000",
        started_at=datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc),
    )
    await cosmos_client.save_meeting(m)
    mock_cosmos_container.upsert_item.assert_called_once()
    call_args = mock_cosmos_container.upsert_item.call_args[0][0]
    assert call_args["id"] == "meet-001"
