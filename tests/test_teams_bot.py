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
async def test_meeting_start_recall_only_skips_graph(mock_cosmos):
    """transcript_source=recall のときは Graph subscribe を呼ばない。"""
    mock_sub = MagicMock()
    mock_sub.subscribe = AsyncMock()
    mock_sub.unsubscribe = AsyncMock()
    mock_recall_client = MagicMock()
    mock_recall_client.create_bot = AsyncMock(return_value="bot-aaa")
    mock_recall_handler = MagicMock()

    from src.bot.teams_bot import MeetingBot
    bot = MeetingBot(
        cosmos_client=mock_cosmos,
        graph_subscription=mock_sub,
        on_utterance=AsyncMock(),
        recall_client=mock_recall_client,
        recall_handler=mock_recall_handler,
        transcript_source="recall",
    )

    activity = MagicMock()
    activity.channel_data = {
        "meeting": {"id": "meet-r", "joinUrl": "https://teams.microsoft.com/l/meetup-join/x"},
        "onlineMeetingId": "MSo-r",
    }
    activity.conversation = MagicMock(id="19:t@thread.v2")
    activity.from_property = MagicMock(id="u")
    turn_context = MagicMock()
    turn_context.activity = activity

    await bot.on_teams_meeting_start_activity(turn_context)

    mock_sub.subscribe.assert_not_called()
    mock_recall_client.create_bot.assert_awaited_once_with(
        meeting_url="https://teams.microsoft.com/l/meetup-join/x"
    )
    mock_recall_handler.register_bot.assert_called_once_with("bot-aaa", "meet-r")


@pytest.mark.asyncio
async def test_meeting_start_no_join_url_skips_recall(mock_cosmos):
    """meeting_url が無ければ Recall をスキップし、会議は登録される。"""
    mock_sub = MagicMock()
    mock_sub.subscribe = AsyncMock()
    mock_recall_client = MagicMock()
    mock_recall_client.create_bot = AsyncMock()
    mock_recall_handler = MagicMock()

    from src.bot.teams_bot import MeetingBot
    bot = MeetingBot(
        cosmos_client=mock_cosmos,
        graph_subscription=mock_sub,
        on_utterance=AsyncMock(),
        recall_client=mock_recall_client,
        recall_handler=mock_recall_handler,
        transcript_source="recall",
    )

    activity = MagicMock()
    activity.channel_data = {"meeting": {"id": "meet-x"}, "onlineMeetingId": "MSo"}
    activity.conversation = MagicMock(id="19:t@thread.v2")
    activity.from_property = MagicMock(id="u")
    turn_context = MagicMock()
    turn_context.activity = activity

    await bot.on_teams_meeting_start_activity(turn_context)

    mock_recall_client.create_bot.assert_not_called()
    mock_cosmos.save_meeting.assert_called_once()


@pytest.mark.asyncio
async def test_meeting_end_calls_leave_and_unregister():
    """会議終了で leave_call と unregister_bot が呼ばれる。"""
    mock_cosmos = MagicMock()
    mock_sub = MagicMock()
    mock_sub.unsubscribe = AsyncMock()
    mock_recall_client = MagicMock()
    mock_recall_client.leave_call = AsyncMock(return_value=True)
    mock_recall_handler = MagicMock()

    from src.bot.teams_bot import MeetingBot
    bot = MeetingBot(
        cosmos_client=mock_cosmos,
        graph_subscription=mock_sub,
        on_utterance=AsyncMock(),
        recall_client=mock_recall_client,
        recall_handler=mock_recall_handler,
        transcript_source="recall",
    )
    bot._active_recall_bots["meet-z"] = "bot-zzz"

    activity = MagicMock()
    activity.channel_data = {"meeting": {"id": "meet-z"}}
    turn_context = MagicMock()
    turn_context.activity = activity

    await bot.on_teams_meeting_end_activity(turn_context)

    mock_recall_client.leave_call.assert_awaited_once_with("bot-zzz")
    mock_recall_handler.unregister_bot.assert_called_once_with("bot-zzz")
    assert "meet-z" not in bot._active_recall_bots


@pytest.mark.asyncio
async def test_meeting_start_recall_create_failure_does_not_crash(mock_cosmos):
    """Recall create_bot が None を返しても会議自体は登録される。"""
    mock_sub = MagicMock()
    mock_sub.subscribe = AsyncMock(return_value="sub-1")
    mock_recall_client = MagicMock()
    mock_recall_client.create_bot = AsyncMock(return_value=None)
    mock_recall_handler = MagicMock()

    from src.bot.teams_bot import MeetingBot
    bot = MeetingBot(
        cosmos_client=mock_cosmos,
        graph_subscription=mock_sub,
        on_utterance=AsyncMock(),
        recall_client=mock_recall_client,
        recall_handler=mock_recall_handler,
        transcript_source="both",
    )

    activity = MagicMock()
    activity.channel_data = {
        "meeting": {"id": "meet-b", "joinUrl": "https://teams.microsoft.com/l/x"},
        "onlineMeetingId": "MSo-b",
    }
    activity.conversation = MagicMock(id="19:t@thread.v2")
    activity.from_property = MagicMock(id="u")
    turn_context = MagicMock()
    turn_context.activity = activity

    await bot.on_teams_meeting_start_activity(turn_context)

    # Graph は走っている
    mock_sub.subscribe.assert_awaited_once()
    # Recall は失敗したが register_bot は呼ばれない
    mock_recall_handler.register_bot.assert_not_called()
    # 会議自体は保存されている
    mock_cosmos.save_meeting.assert_called_once()


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
