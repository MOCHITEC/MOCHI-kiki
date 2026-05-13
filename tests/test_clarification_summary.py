# tests/test_clarification_summary.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.plugins.clarification_summary import ClarificationSummaryPlugin


@pytest.mark.asyncio
async def test_summarize_produces_clear_text():
    plugin = ClarificationSummaryPlugin.__new__(ClarificationSummaryPlugin)

    mock_kernel = MagicMock()
    mock_result = MagicMock()
    mock_result.__str__ = lambda self: (
        "田中さんの「あれをやっておいて」は、「認証フローのレビュー（PR #42）」を指していました。"
    )
    mock_kernel.invoke = AsyncMock(return_value=mock_result)
    plugin._kernel = mock_kernel
    plugin._function = MagicMock()

    result = await plugin.summarize(
        speaker_name="田中 太郎",
        original_text="あれをやっておいて",
        clarification_question="「あれ」とは何を指しますか？",
        reply="認証フローのレビュー（PR #42）のことです",
    )

    assert "田中" in result
    assert len(result) <= 200
