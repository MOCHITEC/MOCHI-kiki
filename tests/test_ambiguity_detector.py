# tests/test_ambiguity_detector.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.plugins.ambiguity_detector import AmbiguityDetectorPlugin, AmbiguityResult


@pytest.mark.asyncio
async def test_detect_ambiguous_utterance():
    plugin = AmbiguityDetectorPlugin.__new__(AmbiguityDetectorPlugin)

    mock_kernel = MagicMock()
    mock_result = MagicMock()
    mock_result.__str__ = lambda self: (
        '{"is_ambiguous": true, '
        '"reason": "主語「あれ」が不明確", '
        '"question": "「あれ」とは具体的に何を指しますか？"}'
    )
    mock_kernel.invoke = AsyncMock(return_value=mock_result)
    plugin._kernel = mock_kernel
    plugin._function = MagicMock()

    result = await plugin.detect("あれをやっておいて")

    assert result.is_ambiguous is True
    assert "不明確" in result.reason
    assert "あれ" in result.question


@pytest.mark.asyncio
async def test_detect_clear_utterance():
    plugin = AmbiguityDetectorPlugin.__new__(AmbiguityDetectorPlugin)

    mock_kernel = MagicMock()
    mock_result = MagicMock()
    mock_result.__str__ = lambda self: (
        '{"is_ambiguous": false, "reason": "", "question": ""}'
    )
    mock_kernel.invoke = AsyncMock(return_value=mock_result)
    plugin._kernel = mock_kernel
    plugin._function = MagicMock()

    result = await plugin.detect("認証フローの実装を田中さんが担当します。")

    assert result.is_ambiguous is False
    assert result.question == ""
