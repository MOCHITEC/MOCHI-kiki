# tests/test_chat_poster.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.services.chat_poster import ChatPoster


@pytest.mark.asyncio
async def test_post_to_meeting_chat():
    poster = ChatPoster.__new__(ChatPoster)
    mock_adapter = MagicMock()
    mock_adapter.continue_conversation = AsyncMock()
    poster._adapter = mock_adapter
    poster._app_id = "app-id-001"

    conversation_ref = MagicMock()
    await poster.post(
        conversation_reference=conversation_ref,
        text="**[仕様補完]** 認証フローは OAuth 2.0 を採用しています。",
    )
    mock_adapter.continue_conversation.assert_called_once()
