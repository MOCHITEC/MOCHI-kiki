#!/usr/bin/env python3
"""Smoke test: verify Azure AI Search index state.

Usage:
    python scripts/check_search_index.py

Exit codes:
    0 — index exists (may be empty)
    1 — index missing or connection failed
"""
import os
import sys
from pathlib import Path

# Load .env from project root
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.models import VectorizedQuery
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient


def main() -> int:
    endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT", "")
    key = os.environ.get("AZURE_SEARCH_KEY", "")
    index_name = os.environ.get("AZURE_SEARCH_INDEX", "documents")

    if not endpoint or not key:
        print("✗ AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY must be set", file=sys.stderr)
        return 1

    credential = AzureKeyCredential(key)

    # 1. Check index exists
    index_client = SearchIndexClient(endpoint=endpoint, credential=credential)
    try:
        index_client.get_index(index_name)
        print(f"✓ Index exists: {index_name}")
    except Exception as e:
        print(f"✗ Index not found: {index_name} ({e})", file=sys.stderr)
        return 1

    # 2. Document count
    search_client = SearchClient(endpoint=endpoint, index_name=index_name, credential=credential)
    try:
        count = search_client.get_document_count()
        print(f"✓ Documents: {count}")
    except Exception as e:
        print(f"✗ Could not get document count: {e}", file=sys.stderr)
        return 1

    # 3. Vector search smoke test using a zero vector as a no-op probe
    # The index uses a 1536-dim field named "content_vector" (text-embedding-3-small)
    try:
        zero_vector = [0.0] * 1536
        vector_query = VectorizedQuery(
            vector=zero_vector,
            k_nearest_neighbors=3,
            fields="content_vector",
        )
        results = list(search_client.search(
            search_text=None,
            vector_queries=[vector_query],
            top=3,
        ))
        if results:
            print(f"✓ Vector search: returned {len(results)} results")
        else:
            print("○ Vector search: no results (index may be empty)")
    except Exception as e:
        print(f"✗ Vector search failed: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
