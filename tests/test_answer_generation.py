# tests/test_answer_generation.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.plugins.answer_generation import AnswerGenerationPlugin
from src.plugins.rag_search import SearchResult


@pytest.mark.asyncio
async def test_generate_returns_text_under_200_chars():
    plugin = AnswerGenerationPlugin.__new__(AnswerGenerationPlugin)

    mock_kernel = MagicMock()
    mock_result = MagicMock()
    mock_result.__str__ = lambda self: "認証フローは OAuth 2.0 を採用しており、トークンの有効期限は 1 時間です。"
    mock_kernel.invoke = AsyncMock(return_value=mock_result)
    plugin._kernel = mock_kernel
    plugin._function = MagicMock()

    docs = [
        SearchResult(
            doc_id="doc-001",
            title="認証フロー仕様書",
            content="本システムの認証は OAuth 2.0 を採用する。トークン有効期限は 1 時間。",
            score=0.95,
        )
    ]
    result = await plugin.generate(
        utterance="認証フローの仕様は？",
        search_results=docs,
    )
    assert len(result) <= 200
    assert "OAuth" in result or "認証" in result
