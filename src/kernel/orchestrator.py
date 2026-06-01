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
from src.plugins.recall_chat_poster import RecallChatPosterPlugin
from src.plugins.minutes_generator import MinutesGeneratorPlugin
from src.plugins.timeline_summarizer import TimelineSummarizerPlugin
from datetime import datetime, timezone, timedelta


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
                api_version="2024-10-21",
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
        # Recall.ai 経由でチャット投稿する poster は set_recall_chat_poster で後注入
        self._recall_poster: Optional[RecallChatPosterPlugin] = None
        # ライブ議事録生成
        self._minutes_gen = MinutesGeneratorPlugin(kernel)
        self._timeline_sum = TimelineSummarizerPlugin(kernel)
        # 最後に更新した時刻 (meeting_id -> datetime)
        self._last_minutes_at: Dict[str, datetime] = {}
        self._last_timeline_block_start: Dict[str, datetime] = {}
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

    def set_recall_chat_poster(self, poster: RecallChatPosterPlugin) -> None:
        """Recall.ai 経由でチャット投稿する poster を注入。
        Bot Framework adapter 経由 (会議に Teams App install 必要) ではなく、
        Recall.ai の send_chat_message API を使う。"""
        self._recall_poster = poster

    def register_meeting(self, meeting_id: str, ref: ConversationReference) -> None:
        self._conversation_references[meeting_id] = ref

    def unregister_meeting(self, meeting_id: str) -> None:
        self._conversation_references.pop(meeting_id, None)

    def register_speaker(self, speaker_id: str, ref: ConversationReference) -> None:
        self._speaker_references[speaker_id] = ref

    async def process_dry_run(self, utterance: Utterance) -> dict:
        """C02 パイプラインを dry_run モードで実行。Teams には投稿せず結果を dict で返す。"""
        result: dict = {
            "intent": None,
            "confidence": 0.0,
            "keywords": [],
            "search_results": [],
            "answer": None,
            "posted_text": None,
        }

        intent_result = await self._intent.analyze(utterance.text)
        result["intent"] = intent_result.intent.value
        result["confidence"] = intent_result.confidence
        result["keywords"] = intent_result.keywords

        if intent_result.intent == IntentLabel.SPEC_INQUIRY:
            search_results = self._rag.search(keywords=intent_result.keywords, top_k=3)
            result["search_results"] = [
                {"title": r.title, "content": r.content, "score": r.score}
                for r in search_results
            ]
            if search_results:
                answer = await self._answer.generate(
                    utterance=utterance.text,
                    search_results=search_results,
                )
                result["answer"] = answer
                result["posted_text"] = f"**[仕様補完]** {answer}"

        elif intent_result.intent == IntentLabel.AMBIGUOUS:
            ambiguity = await self._ambiguity.detect(utterance.text)
            if ambiguity.is_ambiguous:
                result["ambiguity_question"] = ambiguity.question

        return result

    async def process(self, utterance: Utterance) -> None:
        # 議事録・タイムラインの非同期更新 (失敗しても本処理は止めない)
        import asyncio
        asyncio.create_task(self._maybe_update_live_minutes(utterance.meeting_id))

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

        text = f"**[仕様補完]** {answer}"

        # 優先: Recall.ai 経由でチャット投稿 (会議に Teams App install 不要)
        if self._recall_poster is not None:
            ok = await self._recall_poster.post(utterance.meeting_id, text)
            if ok:
                return
            # 失敗時は Bot Framework フォールバックに進む

        # フォールバック: Bot Framework 経由 (要 conversation_reference)
        ref = self._conversation_references.get(utterance.meeting_id)
        if ref is None:
            return

        await self._poster.post(
            conversation_reference=ref,
            text=text,
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

        # 発言者に 1:1 で確認メッセージを送る予定だが、Bot Framework 経由は
        # 会議への app install + speaker_ref 必須。Recall.ai 経由なら
        # 会議のチャットに「@<発言者> に確認」と全体投稿で代用する。
        message_to_chat = (
            f"**[確認]** @{utterance.speaker_name} さん、{ambiguity.question}\n"
            f"（発言「{utterance.text[:100]}」に関する確認です）"
        )

        # 優先: Recall.ai 経由で会議チャットに確認質問を投げる
        if self._recall_poster is not None:
            ok = await self._recall_poster.post(
                utterance.meeting_id, message_to_chat
            )
            if ok:
                return

        # フォールバック: Bot Framework 経由で speaker に 1:1 確認
        speaker_ref = self._speaker_references.get(utterance.speaker_id)
        if speaker_ref is None:
            return
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

    # === ライブ議事録 / タイムライン ===
    _MINUTES_INTERVAL = timedelta(seconds=90)
    _TIMELINE_BLOCK_MIN = timedelta(minutes=5)

    async def refresh_minutes(self, meeting_id: str, force: bool = False) -> bool:
        """外部から議事録/タイムラインの再生成を明示的に呼ぶ (force=True で cooldown 無視)。"""
        return await self._maybe_update_live_minutes(meeting_id, force=force)

    async def _maybe_update_live_minutes(
        self, meeting_id: str, force: bool = False
    ) -> bool:
        """直前更新から _MINUTES_INTERVAL 経過していれば議事録/タイムラインを再生成。
        force=True なら cooldown を無視して即更新。
        失敗しても本処理 (orchestrator.process) は止めない。戻り値は更新したか。
        """
        if not self._cosmos or not meeting_id:
            return False
        now = datetime.now(tz=timezone.utc)
        if not force:
            last = self._last_minutes_at.get(meeting_id)
            if last and (now - last) < self._MINUTES_INTERVAL:
                return False
        self._last_minutes_at[meeting_id] = now
        try:
            utterances = await self._cosmos.list_utterances_for_meeting(
                meeting_id, limit=2000
            )
            if not utterances:
                return False
            # 議事録 Markdown
            markdown = await self._minutes_gen.generate(utterances)
            if markdown:
                await self._cosmos.upsert_minutes(
                    meeting_id=meeting_id,
                    markdown=markdown,
                    utterance_count=len(utterances),
                    updated_at_iso=now.isoformat(),
                )
            # タイムラインブロック (5 分単位、新しい末尾ブロックのみ更新)
            await self._update_latest_timeline_block(meeting_id, utterances, now)
            return True
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "live minutes update failed meeting_id=%s", meeting_id
            )
            return False

    async def _update_latest_timeline_block(
        self,
        meeting_id: str,
        utterances: list,
        now: datetime,
    ) -> None:
        """末尾の 5 分ブロックを再要約する。
        各 utterance の timestamp を見て、最後の utterance の属する 5 分窓を再計算。
        過去の確定ブロックには触らない (再要約しない)。
        """
        if not utterances:
            return
        # utterance を時系列 sorted (cosmos query で既に asc のはず)
        def _ts(u):
            return u.get("timestamp") or ""
        utterances = sorted(utterances, key=_ts)
        # 末尾 utterance の時刻
        last_ts_raw = utterances[-1].get("timestamp")
        if not last_ts_raw:
            return
        try:
            last_ts = datetime.fromisoformat(last_ts_raw.replace("Z", "+00:00"))
        except Exception:
            return
        # 5 分窓の start (floor)
        epoch = datetime(2000, 1, 1, tzinfo=timezone.utc)
        delta = last_ts - epoch
        block_seconds = int(self._TIMELINE_BLOCK_MIN.total_seconds())
        floor_seconds = (int(delta.total_seconds()) // block_seconds) * block_seconds
        block_start = epoch + timedelta(seconds=floor_seconds)
        block_end = block_start + self._TIMELINE_BLOCK_MIN
        # ブロック内の utterance を抽出
        in_block: list = []
        for u in utterances:
            ts_raw = u.get("timestamp")
            if not ts_raw:
                continue
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except Exception:
                continue
            if block_start <= ts < block_end:
                in_block.append(u)
        if not in_block:
            return
        summary = await self._timeline_sum.summarize_block(in_block)
        if not summary:
            return
        await self._cosmos.upsert_timeline_block(
            meeting_id=meeting_id,
            block={
                "start_iso": block_start.isoformat(),
                "end_iso": block_end.isoformat(),
                "summary": summary,
                "utterance_count": len(in_block),
                "updated_at": now.isoformat(),
            },
        )
