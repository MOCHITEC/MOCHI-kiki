# src/services/rag_search.py
"""
Azure AI Search のハイブリッド検索 (ベクトル + キーワード) を叩く薄いラッパー。
Semantic Kernel の Plugin ではなく通常の Python クラスとして提供し、
Orchestrator から決定論的に呼ばれる。
"""
from dataclasses import dataclass
from typing import List

from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from openai import AzureOpenAI


@dataclass
class SearchResult:
    doc_id: str
    title: str
    content: str
    score: float


class RAGSearch:
    def __init__(
        self,
        search_client: SearchClient,
        openai_client: AzureOpenAI,
        embedding_deployment: str,
    ) -> None:
        self._search_client = search_client
        self._openai_client = openai_client
        self._embedding_deployment = embedding_deployment

    def _embed(self, text: str) -> List[float]:
        response = self._openai_client.embeddings.create(
            input=text, model=self._embedding_deployment
        )
        return response.data[0].embedding

    def search(self, keywords: List[str], top_k: int = 3) -> List[SearchResult]:
        """
        ハイブリッド検索（ベクトル + キーワード）でドキュメントを検索する。
        keywords が空の場合は空リストを返す。
        """
        if not keywords:
            return []

        query_text = " ".join(keywords)
        query_vector = self._embed(query_text)

        vector_query = VectorizedQuery(
            vector=query_vector,
            k_nearest_neighbors=top_k,
            fields="content_vector",
        )

        raw = self._search_client.search(
            search_text=query_text,
            vector_queries=[vector_query],
            select=["id", "title", "content"],
            top=top_k,
        )

        results = []
        for item in raw:
            results.append(
                SearchResult(
                    doc_id=item["id"],
                    title=item["title"],
                    content=item["content"],
                    score=item.get("@search.score", 0.0),
                )
            )
        return results
