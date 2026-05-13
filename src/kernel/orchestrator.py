# src/kernel/orchestrator.py
from typing import Dict, Optional

import semantic_kernel as sk
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI
from botbuilder.core import BotFrameworkAdapter
from botbuilder.schema import ConversationReference

from src.models import Utterance
from src.plugins.intent_analysis import IntentAnalysisPlugin, IntentLabel
from src.plugins.rag_search import RAGSearchPlugin
from src.plugins.answer_generation import AnswerGenerationPlugin
from src.plugins.chat_poster import ChatPosterPlugin


class Orchestrator:
    """
    C-02 パイプライン: 発話受信 → 意図解析 → RAG 検索 → 回答生成 → チャット投稿。
    C-03 パイプライン: 曖昧発言検出 → 発言者問い返し → 整理文投稿（後で追加）。
    """

    def __init__(
        self,
        azure_openai_endpoint: str,
        azure_openai_key: str,
        chat_deployment: str,
        embedding_deployment: str,
        search_endpoint: str,
        search_key: str,
        search_index: str,
        adapter: BotFrameworkAdapter,
        app_id: str,
    ) -> None:
        kernel = sk.Kernel()
        kernel.add_service(
            AzureChatCompletion(
                service_id="chat",
                deployment_name=chat_deployment,
                endpoint=azure_openai_endpoint,
                api_key=azure_openai_key,
            )
        )

        openai_client = AzureOpenAI(
            azure_endpoint=azure_openai_endpoint,
            api_key=azure_openai_key,
            api_version="2024-02-01",
        )
        search_client = SearchClient(
            endpoint=search_endpoint,
            index_name=search_index,
            credential=AzureKeyCredential(search_key),
        )

        self._intent = IntentAnalysisPlugin(kernel)
        self._rag = RAGSearchPlugin(search_client, openai_client, embedding_deployment)
        self._answer = AnswerGenerationPlugin(kernel)
        self._poster = ChatPosterPlugin(adapter, app_id)
        self._conversation_references: Dict[str, ConversationReference] = {}
        self._speaker_references: Dict[str, ConversationReference] = {}
        self._pending_sessions: Dict[str, str] = {}
        self._cosmos = None

        # C-03 用プラグイン
        from src.plugins.ambiguity_detector import AmbiguityDetectorPlugin
        from src.plugins.clarification_summary import ClarificationSummaryPlugin
        self._ambiguity = AmbiguityDetectorPlugin(kernel)
        self._summary = ClarificationSummaryPlugin(kernel)

    def set_cosmos(self, cosmos) -> None:
        """C-03 で Cosmos DB に ClarificationSession を保存するために注入する。"""
        self._cosmos = cosmos

    def register_meeting(self, meeting_id: str, ref: ConversationReference) -> None:
        self._conversation_references[meeting_id] = ref

    def unregister_meeting(self, meeting_id: str) -> None:
        self._conversation_references.pop(meeting_id, None)

    def register_speaker(self, speaker_id: str, ref: ConversationReference) -> None:
        self._speaker_references[speaker_id] = ref

    async def process(self, utterance: Utterance) -> None:
        intent_result = await self._intent.analyze(utterance.text)

        if intent_result.intent == IntentLabel.SPEC_INQUIRY:
            await self._handle_spec_inquiry(utterance, intent_result)
            return

        if intent_result.intent == IntentLabel.AMBIGUOUS:
            await self._handle_ambiguous(utterance)
            return

        # その他の意図は現状スキップ

    async def _handle_spec_inquiry(self, utterance: Utterance, intent_result) -> None:
        search_results = self._rag.search(keywords=intent_result.keywords, top_k=3)
        if not search_results:
            return

        answer = await self._answer.generate(
            utterance=utterance.text,
            search_results=search_results,
        )

        ref = self._conversation_references.get(utterance.meeting_id)
        if ref is None:
            return

        await self._poster.post(
            conversation_reference=ref,
            text=f"**[仕様補完]** {answer}",
        )

    async def _handle_ambiguous(self, utterance: Utterance) -> None:
        """曖昧発言を処理する。検出 → セッション作成 → 発言者に確認メッセージ送信。"""
        from src.kernel.clarification_session import ClarificationSession

        ambiguity = await self._ambiguity.detect(utterance.text)
        if not ambiguity.is_ambiguous:
            return

        session = ClarificationSession.new(
            meeting_id=utterance.meeting_id,
            utterance_id=utterance.utterance_id,
            speaker_id=utterance.speaker_id,
            speaker_name=utterance.speaker_name,
            original_text=utterance.text,
            clarification_question=ambiguity.question,
        )

        if self._cosmos:
            await self._cosmos.save_clarification_session(session)

        self._pending_sessions[utterance.speaker_id] = session.session_id

        speaker_ref = self._speaker_references.get(utterance.speaker_id)
        if speaker_ref is None:
            return

        # 発言者に 1:1 で確認メッセージを送る
        message = (
            f"確認させてください: {ambiguity.question}\n"
            f"（会議での発言「{utterance.text}」に関して）"
        )
        await self._poster.post(
            conversation_reference=speaker_ref,
            text=message,
        )

        # タイムアウト処理（60 秒後にセッションを破棄）
        import asyncio
        asyncio.create_task(self._timeout_session(utterance.speaker_id, session.session_id))

    async def _timeout_session(self, speaker_id: str, session_id: str) -> None:
        import asyncio
        await asyncio.sleep(60)
        if self._pending_sessions.get(speaker_id) == session_id:
            self._pending_sessions.pop(speaker_id, None)

    async def handle_clarification_reply(
        self, speaker_id: str, meeting_id: str, reply_text: str
    ) -> None:
        """
        発言者が返信したときの処理。
        整理文を生成して会議チャットに投稿し、セッションを完了させる。
        """
        session_id = self._pending_sessions.pop(speaker_id, None)
        if session_id is None:
            return

        session_dict = None
        if self._cosmos:
            session_dict = await self._cosmos.get_clarification_session(session_id, meeting_id)

        if session_dict is None:
            return

        summary = await self._summary.summarize(
            speaker_name=session_dict["speaker_name"],
            original_text=session_dict["original_text"],
            clarification_question=session_dict["clarification_question"],
            reply=reply_text,
        )

        ref = self._conversation_references.get(meeting_id)
        if ref is None:
            return

        await self._poster.post(
            conversation_reference=ref,
            text=f"**[明確化]** {summary}",
        )

        if self._cosmos:
            from src.kernel.clarification_session import ClarificationSession, SessionStatus
            import datetime as dt
            created_at_raw = session_dict["created_at"]
            created_at = (
                dt.datetime.fromisoformat(created_at_raw)
                if isinstance(created_at_raw, str)
                else dt.datetime.now(tz=dt.timezone.utc)
            )
            updated = ClarificationSession(
                session_id=session_dict["id"],
                meeting_id=session_dict["meeting_id"],
                utterance_id=session_dict["utterance_id"],
                speaker_id=session_dict["speaker_id"],
                speaker_name=session_dict["speaker_name"],
                original_text=session_dict["original_text"],
                clarification_question=session_dict["clarification_question"],
                status=SessionStatus.SUMMARIZED,
                created_at=created_at,
                reply=reply_text,
                summary=summary,
            )
            await self._cosmos.save_clarification_session(updated)
