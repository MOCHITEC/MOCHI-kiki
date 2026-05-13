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

        # C-03 の AMBIGUOUS 処理は後で追加

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
