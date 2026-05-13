# tests/test_clarification_flow.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from src.models import Utterance
from src.kernel.orchestrator import Orchestrator
from src.plugins.intent_analysis import IntentResult, IntentLabel
from src.plugins.ambiguity_detector import AmbiguityResult
from src.kernel.clarification_session import SessionStatus


@pytest.fixture
def mock_components():
    intent = MagicMock()
    intent.analyze = AsyncMock(
        return_value=IntentResult(intent=IntentLabel.AMBIGUOUS, confidence=0.88, keywords=[])
    )

    ambiguity = MagicMock()
    ambiguity.detect = AsyncMock(
        return_value=AmbiguityResult(
            is_ambiguous=True,
            reason="主語が不明確",
            question="「あれ」とは何を指しますか？",
        )
    )

    cosmos = MagicMock()
    cosmos.save_clarification_session = AsyncMock()
    cosmos.get_clarification_session = AsyncMock(return_value=None)
    cosmos.save_utterance = AsyncMock()

    poster = MagicMock()
    poster.post = AsyncMock()

    summary = MagicMock()
    summary.summarize = AsyncMock(
        return_value="田中さんの「あれ」は PR #42 のレビューを指していました。"
    )

    return intent, ambiguity, cosmos, poster, summary


@pytest.fixture
def orchestrator_c03(mock_components):
    intent, ambiguity, cosmos, poster, summary = mock_components
    orc = Orchestrator.__new__(Orchestrator)
    orc._intent = intent
    orc._rag = MagicMock()
    orc._answer = MagicMock()
    orc._poster = poster
    orc._ambiguity = ambiguity
    orc._summary = summary
    orc._cosmos = cosmos
    orc._conversation_references = {"meet-001": MagicMock()}
    orc._speaker_references = {"user-111": MagicMock()}
    orc._pending_sessions = {}
    return orc


@pytest.mark.asyncio
async def test_ambiguous_utterance_sends_private_message(orchestrator_c03, mock_components):
    _, _, _, poster, _ = mock_components
    utterance = Utterance.new(
        meeting_id="meet-001",
        speaker_id="user-111",
        speaker_name="田中 太郎",
        text="あれをやっておいて",
    )
    await orchestrator_c03.process(utterance)

    # 発言者へのプライベートメッセージが送られたことを確認
    poster.post.assert_called_once()
    call_kwargs = poster.post.call_args[1]
    assert "あれ" in call_kwargs["text"] or "確認" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_reply_triggers_summary_and_meeting_post(orchestrator_c03, mock_components):
    _, _, cosmos, poster, summary = mock_components

    # セッションをセットアップ
    from src.kernel.clarification_session import ClarificationSession, SessionStatus
    session = ClarificationSession.new(
        meeting_id="meet-001",
        utterance_id="utt-001",
        speaker_id="user-111",
        speaker_name="田中 太郎",
        original_text="あれをやっておいて",
        clarification_question="「あれ」とは何ですか？",
    )
    cosmos.get_clarification_session = AsyncMock(return_value=session.to_dict())
    orchestrator_c03._pending_sessions["user-111"] = session.session_id

    await orchestrator_c03.handle_clarification_reply(
        speaker_id="user-111",
        meeting_id="meet-001",
        reply_text="認証フローのレビュー（PR #42）です",
    )

    # 整理文生成が呼ばれたことを確認
    summary.summarize.assert_called_once()
    # 会議チャットへの投稿が呼ばれたことを確認
    assert poster.post.call_count >= 1
    last_call = poster.post.call_args_list[-1]
    post_text = last_call[1]["text"]
    assert "**[明確化]**" in post_text
