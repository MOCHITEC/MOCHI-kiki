# tests/test_teams_bot.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from botbuilder.schema import Activity, ActivityTypes
from src.bot.teams_bot import MeetingBot


@pytest.fixture
def mock_cosmos():
    cosmos = MagicMock()
    cosmos.save_meeting = AsyncMock()
    cosmos.save_utterance = AsyncMock()
    return cosmos


@pytest.fixture
def mock_subscription():
    sub = MagicMock()
    sub.subscribe = AsyncMock(return_value="sub-abc-123")
    sub.unsubscribe = AsyncMock()
    return sub


@pytest.fixture
def mock_utterance_queue():
    return AsyncMock()


@pytest.fixture
def bot(mock_cosmos, mock_subscription, mock_utterance_queue):
    return MeetingBot(
        cosmos_client=mock_cosmos,
        graph_subscription=mock_subscription,
        on_utterance=mock_utterance_queue,
    )


@pytest.mark.asyncio
async def test_on_meeting_start_saves_meeting(bot, mock_cosmos):
    activity = MagicMock()
    activity.channel_data = {
        "meeting": {"id": "meet-001"},
        "onlineMeetingId": "MSo-online-001",
    }
    activity.conversation = MagicMock(id="19:thread@thread.v2")
    activity.from_property = MagicMock(id="user-000")
    turn_context = MagicMock()
    turn_context.activity = activity

    await bot.on_teams_meeting_start_activity(turn_context)

    mock_cosmos.save_meeting.assert_called_once()
    saved_meeting = mock_cosmos.save_meeting.call_args[0][0]
    assert saved_meeting.meeting_id == "meet-001"


@pytest.mark.asyncio
async def test_on_meeting_start_subscribes_transcript(bot, mock_subscription):
    activity = MagicMock()
    activity.channel_data = {
        "meeting": {"id": "meet-002"},
        "onlineMeetingId": "MSo-online-002",
    }
    activity.conversation = MagicMock(id="19:thread@thread.v2")
    activity.from_property = MagicMock(id="user-000")
    turn_context = MagicMock()
    turn_context.activity = activity

    await bot.on_teams_meeting_start_activity(turn_context)

    mock_subscription.subscribe.assert_called_once_with(
        meeting_id="meet-002",
        online_meeting_id="MSo-online-002",
    )


@pytest.mark.asyncio
async def test_1on1_message_triggers_clarification_reply(mock_cosmos, mock_subscription):
    from unittest.mock import AsyncMock, MagicMock
    mock_orchestrator = MagicMock()
    mock_orchestrator.handle_clarification_reply = AsyncMock()

    from src.bot.teams_bot import MeetingBot
    bot = MeetingBot(
        cosmos_client=mock_cosmos,
        graph_subscription=mock_subscription,
        on_utterance=AsyncMock(),
        orchestrator=mock_orchestrator,
    )

    # 会議の mapping を登録
    bot._active_meeting_by_speaker = {"user-111": "meet-001"}

    activity = MagicMock()
    activity.type = "message"
    activity.text = "認証フローのレビュー（PR #42）です"
    activity.conversation = MagicMock(conversation_type="personal")
    activity.from_property = MagicMock(id="user-111")

    turn_context = MagicMock()
    turn_context.activity = activity
    turn_context.send_activity = AsyncMock()

    await bot.on_message_activity(turn_context)

    mock_orchestrator.handle_clarification_reply.assert_called_once_with(
        speaker_id="user-111",
        meeting_id="meet-001",
        reply_text="認証フローのレビュー（PR #42）です",
    )
