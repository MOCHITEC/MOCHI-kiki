# scripts/upload_mochi_kiki_spec.py
"""
MOCHI-kiki 自身の仕様ドキュメントを Azure AI Search に追加投入する。
既存 documents インデックスに upsert (同じ id があれば上書き)。

Usage:
    set -a; . .env; set +a
    python scripts/upload_mochi_kiki_spec.py
"""
import json
import os
from pathlib import Path

from openai import AzureOpenAI
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential

SEARCH_ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"]
SEARCH_KEY = os.environ["AZURE_SEARCH_KEY"]
INDEX_NAME = os.environ.get("AZURE_SEARCH_INDEX", "documents")
OPENAI_ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"]
OPENAI_KEY = os.environ["AZURE_OPENAI_KEY"]
EMBEDDING_DEPLOYMENT = os.environ.get(
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small"
)


def main() -> None:
    openai_client = AzureOpenAI(
        azure_endpoint=OPENAI_ENDPOINT,
        api_key=OPENAI_KEY,
        api_version="2024-02-01",
    )
    credential = AzureKeyCredential(SEARCH_KEY)
    search_client = SearchClient(
        endpoint=SEARCH_ENDPOINT, index_name=INDEX_NAME, credential=credential
    )

    docs_path = Path(__file__).parent / "sample_docs" / "mochi_kiki_spec.json"
    with open(docs_path, encoding="utf-8") as f:
        docs = json.load(f)

    for doc in docs:
        resp = openai_client.embeddings.create(
            input=doc["content"], model=EMBEDDING_DEPLOYMENT
        )
        doc["content_vector"] = resp.data[0].embedding
        print(f"  embed: {doc['id']} ({doc['title']})")

    result = search_client.merge_or_upload_documents(documents=docs)
    succeeded = sum(1 for r in result if r.succeeded)
    print(f"\nupserted: {succeeded}/{len(docs)} 件")


if __name__ == "__main__":
    main()
