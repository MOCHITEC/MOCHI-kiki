# tests/test_orchestrator.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.models import Utterance
from src.kernel.orchestrator import Orchestrator
from src.plugins.intent_analysis import IntentResult, IntentLabel
from src.plugins.rag_search import SearchResult


@pytest.fixture
def mock_intent_plugin():
    plugin = MagicMock()
    plugin.analyze = AsyncMock(
        return_value=IntentResult(
            intent=IntentLabel.SPEC_INQUIRY,
            confidence=0.92,
            keywords=["認証", "フロー"],
        )
    )
    return plugin


@pytest.fixture
def mock_rag_plugin():
    plugin = MagicMock()
    plugin.search = MagicMock(
        return_value=[
            SearchResult(
                doc_id="doc-001",
                title="認証フロー仕様書",
                content="OAuth 2.0 を採用",
                score=0.95,
            )
        ]
    )
    return plugin


@pytest.fixture
def mock_answer_plugin():
    plugin = MagicMock()
    plugin.generate = AsyncMock(return_value="認証フローは OAuth 2.0 を採用しています。")
    return plugin


@pytest.fixture
def mock_poster():
    poster = MagicMock()
    poster.post = AsyncMock()
    return poster


@pytest.fixture
def orchestrator(mock_intent_plugin, mock_rag_plugin, mock_answer_plugin, mock_poster):
    orc = Orchestrator.__new__(Orchestrator)
    orc._intent = mock_intent_plugin
    orc._rag = mock_rag_plugin
    orc._answer = mock_answer_plugin
    orc._poster = mock_poster
    orc._conversation_references = {}
    orc._speaker_references = {}
    orc._pending_sessions = {}
    orc._cosmos = None
    return orc


@pytest.mark.asyncio
async def test_spec_inquiry_triggers_rag_and_post(
    orchestrator, mock_rag_plugin, mock_answer_plugin, mock_poster
):
    utterance = Utterance.new(
        meeting_id="meet-001",
        speaker_id="user-111",
        speaker_name="田中 太郎",
        text="認証フローの仕様はどうなっていますか？",
    )
    orchestrator._conversation_references["meet-001"] = MagicMock()

    await orchestrator.process(utterance)

    mock_rag_plugin.search.assert_called_once_with(keywords=["認証", "フロー"], top_k=3)
    mock_answer_plugin.generate.assert_called_once()
    mock_poster.post.assert_called_once()

    post_text = mock_poster.post.call_args[1]["text"]
    assert "**[仕様補完]**" in post_text


@pytest.mark.asyncio
async def test_normal_utterance_skips_rag(orchestrator, mock_rag_plugin):
    orchestrator._intent.analyze = AsyncMock(
        return_value=IntentResult(intent=IntentLabel.NORMAL, confidence=0.95, keywords=[])
    )
    utterance = Utterance.new(
        meeting_id="meet-001",
        speaker_id="user-111",
        speaker_name="田中 太郎",
        text="了解しました。",
    )
    await orchestrator.process(utterance)

    mock_rag_plugin.search.assert_not_called()
