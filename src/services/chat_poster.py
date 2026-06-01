# src/services/chat_poster.py
"""
Bot Framework の proactive message (continue_conversation) ラッパー。
Semantic Kernel の Plugin ではなく通常の Python クラス。
Orchestrator が決定論的に呼んで会議チャットへ投稿する。
"""
from botbuilder.core import BotFrameworkAdapter, TurnContext
from botbuilder.schema import Activity, ConversationReference


class ChatPoster:
    def __init__(self, adapter: BotFrameworkAdapter, app_id: str) -> None:
        self._adapter = adapter
        self._app_id = app_id

    async def post(self, conversation_reference: ConversationReference, text: str) -> None:
        """
        Bot が主体的に会議チャットにメッセージを投稿する（プロアクティブメッセージ）。
        """
        async def callback(turn_context: TurnContext) -> None:
            await turn_context.send_activity(Activity(type="message", text=text))

        await self._adapter.continue_conversation(
            conversation_reference,
            callback,
            self._app_id,
        )
