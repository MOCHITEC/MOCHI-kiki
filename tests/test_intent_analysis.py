# tests/test_intent_analysis.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.plugins.intent_analysis import IntentAnalysisPlugin, IntentLabel


def test_intent_label_values():
    assert IntentLabel.SPEC_INQUIRY == "spec_inquiry"
    assert IntentLabel.AMBIGUOUS == "ambiguous"
    assert IntentLabel.NORMAL == "normal"


@pytest.mark.asyncio
async def test_analyze_spec_inquiry():
    plugin = IntentAnalysisPlugin.__new__(IntentAnalysisPlugin)

    mock_kernel = MagicMock()
    mock_result = MagicMock()
    mock_result.__str__ = lambda self: '{"intent": "spec_inquiry", "confidence": 0.92, "keywords": ["認証", "フロー"]}'
    mock_func = AsyncMock(return_value=mock_result)
    mock_kernel.invoke = mock_func
    plugin._kernel = mock_kernel
    plugin._function = MagicMock()

    result = await plugin.analyze("認証フローの仕様はどうなっていましたっけ？")

    assert result.intent == IntentLabel.SPEC_INQUIRY
    assert result.confidence >= 0.9
    assert "認証" in result.keywords


@pytest.mark.asyncio
async def test_analyze_normal_utterance():
    plugin = IntentAnalysisPlugin.__new__(IntentAnalysisPlugin)

    mock_kernel = MagicMock()
    mock_result = MagicMock()
    mock_result.__str__ = lambda self: '{"intent": "normal", "confidence": 0.95, "keywords": []}'
    mock_func = AsyncMock(return_value=mock_result)
    mock_kernel.invoke = mock_func
    plugin._kernel = mock_kernel
    plugin._function = MagicMock()

    result = await plugin.analyze("了解しました。")

    assert result.intent == IntentLabel.NORMAL
