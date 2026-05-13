# tests/test_chat_poster.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.plugins.chat_poster import ChatPosterPlugin


@pytest.mark.asyncio
async def test_post_to_meeting_chat():
    plugin = ChatPosterPlugin.__new__(ChatPosterPlugin)
    mock_adapter = MagicMock()
    mock_adapter.continue_conversation = AsyncMock()
    plugin._adapter = mock_adapter
    plugin._app_id = "app-id-001"

    conversation_ref = MagicMock()
    await plugin.post(
        conversation_reference=conversation_ref,
        text="**[仕様補完]** 認証フローは OAuth 2.0 を採用しています。",
    )
    mock_adapter.continue_conversation.assert_called_once()
