# src/bot/teams_bot.py
import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Awaitable, Optional

from botbuilder.core import ActivityHandler, TurnContext
from botbuilder.schema import Activity

from src.models import Meeting, Utterance
from src.storage.cosmos_client import CosmosClient
from src.transcript.graph_subscription import GraphTranscriptSubscription
from src.transcript.recall_client import RecallBotClient
from src.transcript.recall_source import RecallWebhookHandler

logger = logging.getLogger(__name__)

_VALID_TRANSCRIPT_SOURCES = {"graph", "recall", "both"}


class MeetingBot(ActivityHandler):
    def __init__(
        self,
        cosmos_client: CosmosClient,
        graph_subscription: GraphTranscriptSubscription,
        on_utterance: Callable[[Utterance], Awaitable[None]],
        orchestrator=None,
        recall_client: Optional[RecallBotClient] = None,
        recall_handler: Optional[RecallWebhookHandler] = None,
        transcript_source: str = "graph",
    ) -> None:
        if transcript_source not in _VALID_TRANSCRIPT_SOURCES:
            raise ValueError(f"transcript_source は {_VALID_TRANSCRIPT_SOURCES} のいずれか")
        if transcript_source in ("recall", "both") and (recall_client is None or recall_handler is None):
            # silent fail-open 防止 (S7)
            raise ValueError(
                f"transcript_source={transcript_source} には recall_client / recall_handler 両方が必要"
            )

        self._cosmos = cosmos_client
        self._subscription = graph_subscription
        self._on_utterance = on_utterance
        self._orchestrator = orchestrator
        self._recall_client = recall_client
        self._recall_handler = recall_handler
        self._transcript_source = transcript_source
        # meeting_id -> subscription_id のマッピング
        self._active_subscriptions: dict[str, str] = {}
        # meeting_id -> recall bot_id のマッピング
        self._active_recall_bots: dict[str, str] = {}
        # speaker_id -> meeting_id（どの会議中に曖昧発言したかの追跡）
        self._active_meeting_by_speaker: dict[str, str] = {}

    # ------- 公開アクセサ（テスト・運用復旧用） -------

    def has_active_recall_bot(self, meeting_id: str) -> bool:
        return meeting_id in self._active_recall_bots

    def get_recall_bot_id(self, meeting_id: str) -> Optional[str]:
        return self._active_recall_bots.get(meeting_id)

    def register_recall_bot(self, meeting_id: str, bot_id: str) -> None:
        self._active_recall_bots[meeting_id] = bot_id

    async def on_teams_meeting_start_activity(self, turn_context: TurnContext) -> None:
        channel_data = turn_context.activity.channel_data or {}
        meeting_info = channel_data.get("meeting") or {}
        meeting_id = meeting_info.get("id", "unknown")
        online_meeting_id = channel_data.get("onlineMeetingId", "")
        thread_id = turn_context.activity.conversation.id
        organizer_id = turn_context.activity.from_property.id

        # Idempotency: 同じ meeting_id で2度目の start が来ても二重投入しない
        if meeting_id in self._active_subscriptions or meeting_id in self._active_recall_bots:
            logger.info("meeting_start 重複検知、無視 (meeting_id=%s)", meeting_id)
            return

        meeting = Meeting(
            meeting_id=meeting_id,
            thread_id=thread_id,
            organizer_id=organizer_id,
            started_at=datetime.now(tz=timezone.utc),
            transcript_source=self._transcript_source,
        )

        if self._transcript_source in ("graph", "both"):
            await self._start_graph_subscription(meeting, online_meeting_id)

        if self._transcript_source in ("recall", "both"):
            await self._start_recall_bot(meeting, meeting_info)

        await self._cosmos.save_meeting(meeting)

        if self._orchestrator:
            from botbuilder.schema import ConversationReference
            ref = TurnContext.get_conversation_reference(turn_context.activity)
            self._orchestrator.register_meeting(meeting.meeting_id, ref)

    async def _start_graph_subscription(self, meeting: Meeting, online_meeting_id: str) -> None:
        try:
            sub_id = await self._subscription.subscribe(
                meeting_id=meeting.meeting_id,
                online_meeting_id=online_meeting_id,
            )
            meeting.transcript_subscription_id = sub_id
            self._active_subscriptions[meeting.meeting_id] = sub_id
        except Exception:
            logger.exception(
                "Graph subscribe 失敗 (meeting_id=%s)", meeting.meeting_id
            )

    async def _start_recall_bot(self, meeting: Meeting, meeting_info: dict) -> None:
        # 制約はコンストラクタで検証済みだが、防御的に再チェック
        if self._recall_client is None or self._recall_handler is None:
            return
        meeting_url = self._extract_meeting_url(meeting_info)
        if not meeting_url:
            logger.warning(
                "meeting_url が取得できず Recall bot 投入をスキップ (meeting_id=%s)",
                meeting.meeting_id,
            )
            return
        bot_id = await self._recall_client.create_bot(meeting_url=meeting_url)
        if not bot_id:
            logger.warning(
                "Recall create_bot 失敗 (meeting_id=%s)", meeting.meeting_id
            )
            return
        self._recall_handler.register_bot(bot_id, meeting.meeting_id)
        self._active_recall_bots[meeting.meeting_id] = bot_id
        meeting.recall_bot_id = bot_id

    async def on_teams_meeting_end_activity(self, turn_context: TurnContext) -> None:
        channel_data = turn_context.activity.channel_data or {}
        meeting_id = (channel_data.get("meeting") or {}).get("id", "unknown")

        sub_id = self._active_subscriptions.pop(meeting_id, None)
        if sub_id:
            try:
                await self._subscription.unsubscribe(sub_id)
            except Exception:
                logger.exception(
                    "Graph unsubscribe 失敗 (meeting_id=%s)", meeting_id
                )

        bot_id = self._active_recall_bots.pop(meeting_id, None)
        if bot_id:
            if self._recall_client:
                ok = await self._recall_client.leave_call(bot_id)
                if not ok:
                    # leave_call 失敗は bot がそのまま課金され続けるため、必ず可視化する
                    logger.error(
                        "Recall leave_call 失敗 (meeting_id=%s bot_id=%s) — 手動 cleanup 必要",
                        meeting_id, bot_id,
                    )
            if self._recall_handler:
                self._recall_handler.unregister_bot(bot_id)

        if self._orchestrator:
            self._orchestrator.unregister_meeting(meeting_id)

    @staticmethod
    def _extract_meeting_url(meeting_info: dict) -> Optional[str]:
        """Bot Framework channel_data から Teams join URL を取り出す。"""
        candidate = meeting_info.get("joinUrl") or meeting_info.get("join_url")
        if not isinstance(candidate, str):
            return None
        # Teams ドメイン以外は受け取らない（攻撃者制御の URL で課金を発生させない）
        if not (candidate.startswith("https://teams.microsoft.com/")
                or candidate.startswith("https://teams.live.com/")):
            return None
        if len(candidate) > 2048:
            return None
        return candidate

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
