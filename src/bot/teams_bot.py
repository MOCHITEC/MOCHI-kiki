# src/bot/teams_bot.py
import asyncio
from datetime import datetime, timezone
from typing import Callable, Awaitable, Optional

from botbuilder.core import ActivityHandler, TurnContext
from botbuilder.schema import Activity

from src.models import Meeting, Utterance
from src.storage.cosmos_client import CosmosClient
from src.transcript.graph_subscription import GraphTranscriptSubscription


class MeetingBot(ActivityHandler):
    def __init__(
        self,
        cosmos_client: CosmosClient,
        graph_subscription: GraphTranscriptSubscription,
        on_utterance: Callable[[Utterance], Awaitable[None]],
        orchestrator=None,
    ) -> None:
        self._cosmos = cosmos_client
        self._subscription = graph_subscription
        self._on_utterance = on_utterance
        self._orchestrator = orchestrator
        # meeting_id -> subscription_id のマッピング
        self._active_subscriptions: dict[str, str] = {}
        # speaker_id -> meeting_id（どの会議中に曖昧発言したかの追跡）
        self._active_meeting_by_speaker: dict[str, str] = {}

    async def on_teams_meeting_start_activity(self, turn_context: TurnContext) -> None:
        channel_data = turn_context.activity.channel_data or {}
        meeting_info = channel_data.get("meeting", {})
        meeting_id = meeting_info.get("id", "unknown")
        online_meeting_id = channel_data.get("onlineMeetingId", "")
        thread_id = turn_context.activity.conversation.id
        organizer_id = turn_context.activity.from_property.id

        meeting = Meeting(
            meeting_id=meeting_id,
            thread_id=thread_id,
            organizer_id=organizer_id,
            started_at=datetime.now(tz=timezone.utc),
        )

        sub_id = await self._subscription.subscribe(
            meeting_id=meeting_id,
            online_meeting_id=online_meeting_id,
        )
        meeting.transcript_subscription_id = sub_id
        self._active_subscriptions[meeting_id] = sub_id

        await self._cosmos.save_meeting(meeting)

        if self._orchestrator:
            from botbuilder.schema import ConversationReference
            ref = TurnContext.get_conversation_reference(turn_context.activity)
            self._orchestrator.register_meeting(meeting_id, ref)

    async def on_teams_meeting_end_activity(self, turn_context: TurnContext) -> None:
        channel_data = turn_context.activity.channel_data or {}
        meeting_id = channel_data.get("meeting", {}).get("id", "unknown")

        sub_id = self._active_subscriptions.pop(meeting_id, None)
        if sub_id:
            await self._subscription.unsubscribe(sub_id)

        if self._orchestrator:
            self._orchestrator.unregister_meeting(meeting_id)

    async def handle_transcript_notification(self, notification: dict) -> None:
        """
        Graph API の変更通知を受け取り、発話として処理する。
        """
        resource_data = notification.get("resourceData", {})
        text = resource_data.get("text", "").strip()
        if not text:
            return

        meeting_id = resource_data.get("meetingId", "unknown")
        utterance = Utterance.new(
            meeting_id=meeting_id,
            speaker_id=resource_data.get("speakerId", "unknown"),
            speaker_name=resource_data.get("speakerDisplayName", "不明"),
            text=text,
        )

        await self._cosmos.save_utterance(utterance)
        await self._on_utterance(utterance)

    async def on_message_activity(self, turn_context: TurnContext) -> None:
        """
        1:1 チャットでのメッセージ受信（発言者からの確認返信）を処理する。
        """
        conversation_type = getattr(turn_context.activity.conversation, "conversation_type", "")
        if conversation_type != "personal":
            return

        speaker_id = turn_context.activity.from_property.id
        reply_text = (turn_context.activity.text or "").strip()
        meeting_id = self._active_meeting_by_speaker.get(speaker_id)

        if not meeting_id or not reply_text:
            return

        if self._orchestrator:
            await self._orchestrator.handle_clarification_reply(
                speaker_id=speaker_id,
                meeting_id=meeting_id,
                reply_text=reply_text,
            )
            await turn_context.send_activity("ありがとうございます。会議チャットに反映しました。")

    def track_speaker_meeting(self, speaker_id: str, meeting_id: str) -> None:
        """発言者が曖昧発言をした際に、どの会議中かを記録する。"""
        self._active_meeting_by_speaker[speaker_id] = meeting_id
