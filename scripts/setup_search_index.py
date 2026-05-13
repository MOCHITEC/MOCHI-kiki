# scripts/setup_search_index.py
"""
Azure AI Search インデックスを作成し、サンプルドキュメントを投入するスクリプト。
実行前に AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY を設定すること。

Usage:
    python scripts/setup_search_index.py
"""
import json
import os
from pathlib import Path
from openai import AzureOpenAI
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SearchField,
    SearchFieldDataType,
    SimpleField,
    SearchableField,
    VectorSearch,
    HnswAlgorithmConfiguration,
    VectorSearchProfile,
)
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential

SEARCH_ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"]
SEARCH_KEY = os.environ["AZURE_SEARCH_KEY"]
INDEX_NAME = os.environ.get("AZURE_SEARCH_INDEX", "documents")
OPENAI_ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"]
OPENAI_KEY = os.environ["AZURE_OPENAI_KEY"]
EMBEDDING_DEPLOYMENT = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
EMBEDDING_DIMENSIONS = 1536


def create_index() -> None:
    credential = AzureKeyCredential(SEARCH_KEY)
    index_client = SearchIndexClient(endpoint=SEARCH_ENDPOINT, credential=credential)

    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="title", type=SearchFieldDataType.String, analyzer_name="ja.lucene"),
        SearchableField(name="content", type=SearchFieldDataType.String, analyzer_name="ja.lucene"),
        SimpleField(name="source", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="category", type=SearchFieldDataType.String, filterable=True),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=EMBEDDING_DIMENSIONS,
            vector_search_profile_name="hnsw-profile",
        ),
    ]

    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="hnsw-algo")],
        profiles=[VectorSearchProfile(name="hnsw-profile", algorithm_configuration_name="hnsw-algo")],
    )

    index = SearchIndex(name=INDEX_NAME, fields=fields, vector_search=vector_search)
    index_client.create_or_update_index(index)
    print(f"インデックス '{INDEX_NAME}' を作成しました。")


def embed_text(text: str, client: AzureOpenAI) -> list[float]:
    response = client.embeddings.create(input=text, model=EMBEDDING_DEPLOYMENT)
    return response.data[0].embedding


def upload_documents() -> None:
    openai_client = AzureOpenAI(azure_endpoint=OPENAI_ENDPOINT, api_key=OPENAI_KEY, api_version="2024-02-01")
    credential = AzureKeyCredential(SEARCH_KEY)
    search_client = SearchClient(endpoint=SEARCH_ENDPOINT, index_name=INDEX_NAME, credential=credential)

    docs_path = Path(__file__).parent / "sample_docs" / "spec_sample.json"
    with open(docs_path, encoding="utf-8") as f:
        docs = json.load(f)

    for doc in docs:
        doc["content_vector"] = embed_text(doc["content"], openai_client)

    result = search_client.upload_documents(documents=docs)
    print(f"{len(docs)} 件のドキュメントを投入しました。")


if __name__ == "__main__":
    create_index()
    upload_documents()
    print("セットアップ完了。")
