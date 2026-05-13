# tests/test_graph_subscription.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.transcript.graph_subscription import GraphTranscriptSubscription


@pytest.fixture
def mock_http_client():
    client = AsyncMock()
    client.post = AsyncMock(return_value=MagicMock(
        status=201,
        json=AsyncMock(return_value={"id": "sub-abc-123"}),
    ))
    client.delete = AsyncMock(return_value=MagicMock(status=204))
    return client


@pytest.mark.asyncio
async def test_subscribe_returns_subscription_id(mock_http_client):
    subscription = GraphTranscriptSubscription(
        tenant_id="tenant-001",
        client_id="client-001",
        client_secret="secret",
        notification_url="https://bot.example.com/api/notifications",
    )
    subscription._http_client = mock_http_client
    subscription._access_token = "fake-token"

    sub_id = await subscription.subscribe(
        meeting_id="meet-001",
        online_meeting_id="MSoxxx",
    )
    assert sub_id == "sub-abc-123"


@pytest.mark.asyncio
async def test_unsubscribe_calls_delete(mock_http_client):
    subscription = GraphTranscriptSubscription(
        tenant_id="tenant-001",
        client_id="client-001",
        client_secret="secret",
        notification_url="https://bot.example.com/api/notifications",
    )
    subscription._http_client = mock_http_client
    subscription._access_token = "fake-token"

    await subscription.unsubscribe("sub-abc-123")
    mock_http_client.delete.assert_called_once()
