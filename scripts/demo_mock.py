"""
完全モック版デモ — Azure API キー不要。
キーワードベースの疑似 AI で C-02 / C-03 パイプラインを実演する。
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.models import Utterance
from src.plugins.intent_analysis import IntentLabel, IntentResult
from src.plugins.ambiguity_detector import AmbiguityResult
from src.services.rag_search import SearchResult
from src.kernel.clarification_session import ClarificationSession, SessionStatus

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sample documents (same content as scripts/sample_docs/spec_sample.json)
# ---------------------------------------------------------------------------
SAMPLE_DOCS: List[SearchResult] = [
    SearchResult(
        doc_id="doc-001",
        title="認証フロー仕様書 v2.3",
        content=(
            "本システムの認証は OAuth 2.0 On-Behalf-Of フローを採用する。"
            "ユーザーは Entra ID でログイン後、アクセストークンを Bot に渡す。"
            "Bot はこのトークンを使って Graph API にアクセスする。"
            "トークンの有効期限は 1 時間。リフレッシュトークンは Cosmos DB に暗号化して保存する。"
        ),
        score=1.0,
    ),
    SearchResult(
        doc_id="doc-002",
        title="API レート制限ポリシー",
        content=(
            "Azure OpenAI の呼び出しは 1 分あたり 60 リクエストに制限される。"
            "制限を超えた場合は HTTP 429 が返却される。"
            "指数バックオフで最大 3 回リトライする。GPT-4o の最大トークン数は 128,000。"
        ),
        score=0.85,
    ),
    SearchResult(
        doc_id="doc-003",
        title="用語集: SKU（Stock Keeping Unit）",
        content=(
            "SKU とは在庫管理単位のこと。本システムでは Azure のサービスプラン識別子"
            "（例: S1, P1v3）を指す場合と、社内の製品コード（例: PRD-001）を指す場合がある。"
            "文脈によって意味が異なるため注意が必要。"
        ),
        score=0.75,
    ),
]

SPEC_KEYWORDS = ["仕様", "定義", "どうなって", "どういう", "とは", "確認", "認証", "sku", "api", "レート"]
AMBIGUOUS_KEYWORDS = ["あれ", "これ", "それ", "その辺", "いい感じ", "適当", "あとで", "そこ"]


# ---------------------------------------------------------------------------
# Mock plugins
# ---------------------------------------------------------------------------

class MockIntentAnalysis:
    async def analyze(self, utterance: str) -> IntentResult:
        text_lower = utterance.lower()
        if any(k in text_lower for k in AMBIGUOUS_KEYWORDS):
            return IntentResult(intent=IntentLabel.AMBIGUOUS, confidence=0.9, keywords=[])
        if any(k in text_lower for k in SPEC_KEYWORDS):
            keywords = [k for k in SPEC_KEYWORDS if k in text_lower]
            return IntentResult(intent=IntentLabel.SPEC_INQUIRY, confidence=0.85, keywords=keywords)
        return IntentResult(intent=IntentLabel.NORMAL, confidence=0.95, keywords=[])


class MockAmbiguityDetector:
    async def detect(self, utterance: str) -> AmbiguityResult:
        text_lower = utterance.lower()
        matched = [k for k in AMBIGUOUS_KEYWORDS if k in text_lower]
        if matched:
            pronoun = matched[0]
            return AmbiguityResult(
                is_ambiguous=True,
                reason=f"「{pronoun}」の指示対象が不明確",
                question=f"「{pronoun}」とは具体的に何を指していますか？",
            )
        return AmbiguityResult(is_ambiguous=False, reason="", question="")


class MockRAGSearch:
    def search(self, keywords: List[str], top_k: int = 3) -> List[SearchResult]:
        if not keywords:
            return []
        results = []
        for doc in SAMPLE_DOCS:
            score = sum(k in doc.title.lower() or k in doc.content.lower() for k in keywords)
            if score > 0:
                results.append(SearchResult(doc.doc_id, doc.title, doc.content, float(score)))
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k] if results else SAMPLE_DOCS[:1]


class MockAnswerGeneration:
    async def generate(self, utterance: str, search_results: List[SearchResult]) -> str:
        if not search_results:
            return "関連情報が見つかりませんでした。"
        top = search_results[0]
        summary = top.content[:150]
        return f"【{top.title}】{summary}"


class MockClarificationSummary:
    async def summarize(
        self,
        speaker_name: str,
        original_text: str,
        clarification_question: str,
        reply: str,
    ) -> str:
        return (
            f"{speaker_name}さんの「{original_text}」は「{reply}」を指していました。"
        )


# ---------------------------------------------------------------------------
# In-memory Cosmos replacement
# ---------------------------------------------------------------------------

class MockCosmos:
    def __init__(self):
        self._sessions: Dict[str, dict] = {}

    async def save_clarification_session(self, session: ClarificationSession) -> None:
        self._sessions[session.session_id] = {
            "id": session.session_id,
            "meeting_id": session.meeting_id,
            "utterance_id": session.utterance_id,
            "speaker_id": session.speaker_id,
            "speaker_name": session.speaker_name,
            "original_text": session.original_text,
            "clarification_question": session.clarification_question,
            "status": session.status,
            "created_at": session.created_at,
            "reply": session.reply,
            "summary": session.summary,
        }
        logger.debug(f"[Cosmos mock] session saved: {session.session_id}")

    async def get_clarification_session(self, session_id: str, meeting_id: str) -> Optional[dict]:
        return self._sessions.get(session_id)


# ---------------------------------------------------------------------------
# Console poster (replaces ChatPoster / Teams)
# ---------------------------------------------------------------------------

class ConsolePoster:
    def __init__(self, label: str = "会議チャット"):
        self._label = label

    async def post(self, conversation_reference, text: str) -> None:
        dest = getattr(conversation_reference, "_label", self._label)
        print(f"\n{'='*60}")
        print(f"  [投稿先: {dest}]")
        print(f"  {text}")
        print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Mock Orchestrator (same logic as the real one, all Azure deps removed)
# ---------------------------------------------------------------------------

class MockOrchestrator:
    def __init__(self) -> None:
        self._intent = MockIntentAnalysis()
        self._ambiguity = MockAmbiguityDetector()
        self._rag = MockRAGSearch()
        self._answer = MockAnswerGeneration()
        self._summary = MockClarificationSummary()
        self._cosmos = MockCosmos()

        self._meeting_poster = ConsolePoster("会議チャット")
        self._speaker_poster = ConsolePoster("発言者 DM")

        self._conversation_references: Dict[str, object] = {}
        self._speaker_references: Dict[str, object] = {}
        self._pending_sessions: Dict[str, str] = {}

    def register_meeting(self, meeting_id: str, ref=None) -> None:
        ref = ref or type("Ref", (), {"_label": f"会議チャット({meeting_id})"})()
        self._conversation_references[meeting_id] = ref

    def register_speaker(self, speaker_id: str, name: str = "", ref=None) -> None:
        ref = ref or type("Ref", (), {"_label": f"DM({name or speaker_id})"})()
        self._speaker_references[speaker_id] = ref

    async def process(self, utterance: Utterance) -> None:
        intent_result = await self._intent.analyze(utterance.text)
        logger.info(
            f"  → 意図: {intent_result.intent.value} "
            f"(confidence={intent_result.confidence:.2f}, keywords={intent_result.keywords})"
        )

        if intent_result.intent == IntentLabel.SPEC_INQUIRY:
            await self._handle_spec_inquiry(utterance, intent_result)
        elif intent_result.intent == IntentLabel.AMBIGUOUS:
            await self._handle_ambiguous(utterance)

    async def _handle_spec_inquiry(self, utterance: Utterance, intent_result: IntentResult) -> None:
        search_results = self._rag.search(keywords=intent_result.keywords, top_k=3)
        if not search_results:
            return
        answer = await self._answer.generate(utterance=utterance.text, search_results=search_results)
        ref = self._conversation_references.get(utterance.meeting_id)
        if ref is None:
            return
        await self._meeting_poster.post(ref, f"**[仕様補完]** {answer}")

    async def _handle_ambiguous(self, utterance: Utterance) -> None:
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
        await self._cosmos.save_clarification_session(session)
        self._pending_sessions[utterance.speaker_id] = session.session_id

        speaker_ref = self._speaker_references.get(utterance.speaker_id)
        if speaker_ref is None:
            logger.warning(f"  → 発言者 {utterance.speaker_id} の ConversationReference が未登録")
            return

        message = (
            f"確認させてください: {ambiguity.question}\n"
            f"（会議での発言「{utterance.text}」に関して）"
        )
        await self._speaker_poster.post(speaker_ref, message)

    async def handle_clarification_reply(
        self, speaker_id: str, meeting_id: str, reply_text: str
    ) -> None:
        session_id = self._pending_sessions.pop(speaker_id, None)
        if session_id is None:
            logger.warning("  → 対応する ClarificationSession が見つかりません")
            return

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
        await self._meeting_poster.post(ref, f"**[明確化]** {summary}")


# ---------------------------------------------------------------------------
# Demo scenario
# ---------------------------------------------------------------------------

DEMO_UTTERANCES = [
    ("user-001", "田中 太郎", "了解しました。"),
    ("user-002", "鈴木 花子", "認証フローの仕様はどうなっていましたっけ？"),
    ("user-001", "田中 太郎", "SKU の定義を確認したいのですが。"),
    ("user-003", "佐藤 次郎", "あれをやっておいて"),
    ("user-002", "鈴木 花子", "その辺はいい感じで"),
    ("user-001", "田中 太郎", "API のレート制限はどうなっていますか？"),
]


async def main() -> None:
    print("\n" + "#" * 60)
    print("  MOCHI-kiki デモ (完全モック / Azure API キー不要)")
    print("#" * 60 + "\n")

    orchestrator = MockOrchestrator()
    orchestrator.register_meeting("meet-demo-001")
    for uid, name, _ in DEMO_UTTERANCES:
        orchestrator.register_speaker(uid, name)

    # --- C-02 / C-03 : 発話処理 ---
    for speaker_id, speaker_name, text in DEMO_UTTERANCES:
        utterance = Utterance.new(
            meeting_id="meet-demo-001",
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            text=text,
        )
        logger.info(f"[発話] {speaker_name}: {text}")
        await orchestrator.process(utterance)

    # --- C-03 : 返信フロー ---
    print("\n" + "-" * 60)
    print("  (シミュレーション) 佐藤さんが Bot の質問に返信")
    print("-" * 60)
    await orchestrator.handle_clarification_reply(
        speaker_id="user-003",
        meeting_id="meet-demo-001",
        reply_text="認証フローのレビュー（PR #42）のことです",
    )

    print("\n" + "#" * 60)
    print("  デモ完了")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
