import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from src.plugins.rag_search import RAGSearchPlugin, SearchResult


@pytest.fixture
def mock_search_client():
    client = MagicMock()
    mock_doc = MagicMock()
    mock_doc.__getitem__ = lambda self, key: {
        "id": "doc-001",
        "title": "認証フロー仕様書",
        "content": "本システムの認証は OAuth 2.0 を採用する。",
        "@search.score": 0.95,
    }[key]
    mock_doc.get = lambda key, default=None: {
        "id": "doc-001",
        "title": "認証フロー仕様書",
        "content": "本システムの認証は OAuth 2.0 を採用する。",
        "@search.score": 0.95,
    }.get(key, default)
    client.search = MagicMock(return_value=iter([mock_doc]))
    return client


@pytest.fixture
def mock_openai_client():
    client = MagicMock()
    client.embeddings.create = MagicMock(
        return_value=MagicMock(data=[MagicMock(embedding=[0.1] * 1536)])
    )
    return client


def test_search_returns_results(mock_search_client, mock_openai_client):
    plugin = RAGSearchPlugin.__new__(RAGSearchPlugin)
    plugin._search_client = mock_search_client
    plugin._openai_client = mock_openai_client
    plugin._embedding_deployment = "text-embedding-3-small"

    results = plugin.search(keywords=["認証", "フロー"], top_k=3)

    assert len(results) >= 1
    assert results[0].title == "認証フロー仕様書"
    assert results[0].score >= 0.9


def test_search_with_empty_keywords(mock_search_client, mock_openai_client):
    plugin = RAGSearchPlugin.__new__(RAGSearchPlugin)
    plugin._search_client = mock_search_client
    plugin._openai_client = mock_openai_client
    plugin._embedding_deployment = "text-embedding-3-small"

    results = plugin.search(keywords=[], top_k=3)
    assert isinstance(results, list)
    assert len(results) == 0
