# C-02 仕様補完（リアルタイム RAG 投稿）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**前提条件:** C-01 が完成し、`src/models.py`（Utterance）、`src/storage/cosmos_client.py`（CosmosClient）、`src/bot/teams_bot.py`（MeetingBot）、`src/main.py` が動作していること。

**Goal:** 会議中の発話から「仕様確認」「用語不明」意図を検出し、Azure AI Search で社内ドキュメントをハイブリッド検索し、GPT-4o で 200 文字以内の回答を生成して Teams 会議チャットに投稿する。

**Architecture:** Semantic Kernel のプラグイン機構を使い、3 つの処理（意図解析 → RAG 検索 → 回答生成）をプラグインとして実装する。Orchestrator クラスが発話を受け取り、意図が「仕様確認」の場合のみ RAG → 生成 → 投稿のパイプラインを実行する。既存の `on_utterance` コールバックを Orchestrator に差し替えることで C-01 と接続する。

**Tech Stack:** Python 3.11+, semantic-kernel>=1.5.0, azure-search-documents>=11.6.0, openai>=1.40.0（Azure OpenAI 経由）, botbuilder-core（C-01 から継承）

---

## ファイル構成

```
src/
├── (C-01 で作成済み)
├── plugins/
│   ├── __init__.py
│   ├── intent_analysis.py       # Semantic Kernel プラグイン: 意図分類
│   ├── rag_search.py            # Semantic Kernel プラグイン: Azure AI Search
│   ├── answer_generation.py     # Semantic Kernel プラグイン: GPT-4o 回答生成
│   └── chat_poster.py           # Semantic Kernel プラグイン: Teams チャット投稿
└── kernel/
    ├── __init__.py
    └── orchestrator.py          # Semantic Kernel セットアップ + C-02 パイプライン実行
scripts/
└── setup_search_index.py        # Azure AI Search インデックスとサンプルデータ投入スクリプト
tests/
├── (C-01 で作成済み)
├── test_intent_analysis.py
├── test_rag_search.py
├── test_answer_generation.py
├── test_chat_poster.py
└── test_orchestrator.py
```

**config.py への追加フィールド（既存ファイルを編集）:**
```
AZURE_OPENAI_ENDPOINT
AZURE_OPENAI_KEY
AZURE_OPENAI_DEPLOYMENT   # GPT-4o のデプロイ名
AZURE_OPENAI_EMBEDDING_DEPLOYMENT  # text-embedding-3-small のデプロイ名
AZURE_SEARCH_ENDPOINT
AZURE_SEARCH_KEY
AZURE_SEARCH_INDEX        # インデックス名（デフォルト: "documents"）
```

---

### Task 1: 依存パッケージの追加と Config 拡張

**Files:**
- Modify: `pyproject.toml`（dependencies に追加）
- Modify: `src/config.py`（フィールド追加）
- Modify: `.env.example`（変数追加）

- [ ] **Step 1: pyproject.toml の dependencies に追加する**

`pyproject.toml` の `dependencies` リストに以下を追加する：

```toml
    "semantic-kernel>=1.5.0",
    "azure-search-documents>=11.6.0",
    "openai>=1.40.0",
```

- [ ] **Step 2: src/config.py を編集して Azure OpenAI / AI Search フィールドを追加する**

`Config.__init__` に以下を追加する：

```python
        self.azure_openai_endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
        self.azure_openai_key = os.environ["AZURE_OPENAI_KEY"]
        self.azure_openai_deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
        self.azure_openai_embedding_deployment = os.environ.get(
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small"
        )
        self.azure_search_endpoint = os.environ["AZURE_SEARCH_ENDPOINT"]
        self.azure_search_key = os.environ["AZURE_SEARCH_KEY"]
        self.azure_search_index = os.environ.get("AZURE_SEARCH_INDEX", "documents")
```

- [ ] **Step 3: .env.example に変数を追加する**

```bash
# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://your-openai.openai.azure.com/
AZURE_OPENAI_KEY=your-openai-key
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small

# Azure AI Search
AZURE_SEARCH_ENDPOINT=https://your-search.search.windows.net
AZURE_SEARCH_KEY=your-search-key
AZURE_SEARCH_INDEX=documents
```

- [ ] **Step 4: パッケージを再インストールする**

```bash
pip install -e ".[dev]"
```

Expected: エラーなし

- [ ] **Step 5: コミット**

```bash
git add pyproject.toml src/config.py .env.example
git commit -m "chore(c02): add Azure OpenAI and AI Search dependencies and config"
```

---

### Task 2: Azure AI Search インデックスのセットアップスクリプト

**Files:**
- Create: `scripts/setup_search_index.py`
- Create: `scripts/sample_docs/spec_sample.json`

- [ ] **Step 1: サンプルドキュメントを作成する**

```json
// scripts/sample_docs/spec_sample.json
[
  {
    "id": "doc-001",
    "title": "認証フロー仕様書 v2.3",
    "content": "本システムの認証は OAuth 2.0 On-Behalf-Of フローを採用する。ユーザーは Entra ID でログイン後、アクセストークンを Bot に渡す。Bot はこのトークンを使って Graph API にアクセスする。トークンの有効期限は 1 時間。リフレッシュトークンは Cosmos DB に暗号化して保存する。",
    "source": "sharepoint",
    "category": "auth"
  },
  {
    "id": "doc-002",
    "title": "API レート制限ポリシー",
    "content": "Azure OpenAI の呼び出しは 1 分あたり 60 リクエストに制限される。制限を超えた場合は HTTP 429 が返却される。指数バックオフで最大 3 回リトライする。GPT-4o の最大トークン数は 128,000。",
    "source": "confluence",
    "category": "api"
  },
  {
    "id": "doc-003",
    "title": "用語集: SKU（Stock Keeping Unit）",
    "content": "SKU とは在庫管理単位のこと。本システムでは Azure のサービスプラン識別子（例: S1, P1v3）を指す場合と、社内の製品コード（例: PRD-001）を指す場合がある。文脈によって意味が異なるため注意が必要。",
    "source": "internal_glossary",
    "category": "terminology"
  }
]
```

- [ ] **Step 2: scripts/setup_search_index.py を作成する**

```python
# scripts/setup_search_index.py
"""
Azure AI Search インデックスを作成し、サンプルドキュメントを投入するスクリプト。
実行前に AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY を設定すること。

Usage:
    python scripts/setup_search_index.py
"""
import asyncio
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
```

- [ ] **Step 3: スクリプトをテスト実行する（Azure 接続が必要）**

```bash
python scripts/setup_search_index.py
```

Expected:
```
インデックス 'documents' を作成しました。
3 件のドキュメントを投入しました。
セットアップ完了。
```

- [ ] **Step 4: コミット**

```bash
git add scripts/
git commit -m "feat(c02): add Azure AI Search index setup script with sample documents"
```

---

### Task 3: 意図解析プラグインの実装

**Files:**
- Create: `src/plugins/__init__.py`
- Create: `src/plugins/intent_analysis.py`
- Create: `tests/test_intent_analysis.py`

- [ ] **Step 1: テストを書く**

```python
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
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
pytest tests/test_intent_analysis.py -v
```

Expected: `ImportError: cannot import name 'IntentAnalysisPlugin'`

- [ ] **Step 3: src/plugins/intent_analysis.py を実装する**

```python
# src/plugins/intent_analysis.py
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import List

import semantic_kernel as sk
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.functions import KernelArguments


class IntentLabel(str, Enum):
    SPEC_INQUIRY = "spec_inquiry"   # 仕様確認・用語不明
    AMBIGUOUS = "ambiguous"         # 曖昧発言（C-03 で処理）
    NORMAL = "normal"               # 通常会話（スキップ）


@dataclass
class IntentResult:
    intent: IntentLabel
    confidence: float
    keywords: List[str] = field(default_factory=list)


INTENT_PROMPT = """
あなたは会議の発話を分析する AI です。
以下の発話を分析し、JSON 形式で意図を返してください。

発話: {{$utterance}}

意図の分類:
- spec_inquiry: 仕様確認、用語の意味確認、ドキュメント参照が必要な発言
  例: 「〇〇の仕様はどうなっていますか？」「〇〇とはどういう意味ですか？」
- ambiguous: 主語や目的語が不明確で解釈が複数できる発言
  例: 「あれをやっておいて」「その辺はいい感じで」
- normal: 上記以外の通常会話

JSON のみを返す（説明不要）:
{
  "intent": "spec_inquiry" | "ambiguous" | "normal",
  "confidence": 0.0-1.0,
  "keywords": ["キーワード1", "キーワード2"]
}
"""


class IntentAnalysisPlugin:
    def __init__(self, kernel: sk.Kernel) -> None:
        self._kernel = kernel
        self._function = kernel.add_function(
            plugin_name="IntentAnalysis",
            function_name="analyze",
            prompt=INTENT_PROMPT,
        )

    async def analyze(self, utterance: str) -> IntentResult:
        result = await self._kernel.invoke(
            self._function,
            KernelArguments(utterance=utterance),
        )
        try:
            raw = json.loads(str(result))
            return IntentResult(
                intent=IntentLabel(raw.get("intent", "normal")),
                confidence=float(raw.get("confidence", 0.0)),
                keywords=raw.get("keywords", []),
            )
        except (json.JSONDecodeError, ValueError):
            return IntentResult(intent=IntentLabel.NORMAL, confidence=0.0)
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
pytest tests/test_intent_analysis.py -v
```

Expected: `2 passed`

- [ ] **Step 5: コミット**

```bash
git add src/plugins/__init__.py src/plugins/intent_analysis.py tests/test_intent_analysis.py
git commit -m "feat(c02): add intent analysis plugin with spec_inquiry / ambiguous / normal classification"
```

---

### Task 4: RAG 検索プラグインの実装

**Files:**
- Create: `src/plugins/rag_search.py`
- Create: `tests/test_rag_search.py`

- [ ] **Step 1: テストを書く**

```python
# tests/test_rag_search.py
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from src.plugins.rag_search import RAGSearchPlugin, SearchResult


@pytest.fixture
def mock_search_client():
    client = MagicMock()
    mock_results = [
        MagicMock(
            **{
                "get": lambda key, default=None: {
                    "id": "doc-001",
                    "title": "認証フロー仕様書",
                    "content": "本システムの認証は OAuth 2.0 を採用する。",
                    "@search.score": 0.95,
                }.get(key, default),
                "__getitem__": lambda self, key: {
                    "id": "doc-001",
                    "title": "認証フロー仕様書",
                    "content": "本システムの認証は OAuth 2.0 を採用する。",
                    "@search.score": 0.95,
                }[key],
            }
        )
    ]
    client.search = MagicMock(return_value=iter(mock_results))
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
    # キーワードなしでも空リストを返す（エラーにならない）
    assert isinstance(results, list)
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
pytest tests/test_rag_search.py -v
```

Expected: `ImportError: cannot import name 'RAGSearchPlugin'`

- [ ] **Step 3: src/plugins/rag_search.py を実装する**

```python
# src/plugins/rag_search.py
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


class RAGSearchPlugin:
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
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
pytest tests/test_rag_search.py -v
```

Expected: `2 passed`

- [ ] **Step 5: コミット**

```bash
git add src/plugins/rag_search.py tests/test_rag_search.py
git commit -m "feat(c02): add RAG search plugin with hybrid vector + keyword search"
```

---

### Task 5: 回答生成プラグインとチャット投稿プラグインの実装

**Files:**
- Create: `src/plugins/answer_generation.py`
- Create: `src/plugins/chat_poster.py`
- Create: `tests/test_answer_generation.py`
- Create: `tests/test_chat_poster.py`

- [ ] **Step 1: テストを書く（回答生成）**

```python
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
```

- [ ] **Step 2: テストを書く（チャット投稿）**

```python
# tests/test_chat_poster.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.plugins.chat_poster import ChatPosterPlugin


@pytest.mark.asyncio
async def test_post_to_meeting_chat():
    plugin = ChatPosterPlugin.__new__(ChatPosterPlugin)
    mock_adapter = MagicMock()
    mock_adapter.continue_conversation = AsyncMock()
    plugin._adapter = mock_adapter
    plugin._app_id = "app-id-001"

    conversation_ref = MagicMock()
    await plugin.post(
        conversation_reference=conversation_ref,
        text="**[仕様補完]** 認証フローは OAuth 2.0 を採用しています。",
    )
    mock_adapter.continue_conversation.assert_called_once()
```

- [ ] **Step 3: テストが失敗することを確認する**

```bash
pytest tests/test_answer_generation.py tests/test_chat_poster.py -v
```

Expected: `ImportError` × 2

- [ ] **Step 4: src/plugins/answer_generation.py を実装する**

```python
# src/plugins/answer_generation.py
from typing import List

import semantic_kernel as sk
from semantic_kernel.functions import KernelArguments

from src.plugins.rag_search import SearchResult


ANSWER_PROMPT = """
あなたは会議中に仕様情報を提供する AI アシスタントです。
以下の会議での発言と、社内ドキュメントから取得した関連情報をもとに、
200 文字以内で簡潔に回答してください。

発言: {{$utterance}}

関連ドキュメント:
{{$context}}

回答は **[仕様補完]** というプレフィックスをつけずに、事実のみを簡潔に述べてください。
200 文字を超えた場合は最も重要な情報のみを残して切り詰めてください。
"""


class AnswerGenerationPlugin:
    def __init__(self, kernel: sk.Kernel) -> None:
        self._kernel = kernel
        self._function = kernel.add_function(
            plugin_name="AnswerGeneration",
            function_name="generate",
            prompt=ANSWER_PROMPT,
        )

    async def generate(self, utterance: str, search_results: List[SearchResult]) -> str:
        context = "\n---\n".join(
            f"【{r.title}】\n{r.content}" for r in search_results
        )
        result = await self._kernel.invoke(
            self._function,
            KernelArguments(utterance=utterance, context=context),
        )
        text = str(result).strip()
        return text[:200] if len(text) > 200 else text
```

- [ ] **Step 5: src/plugins/chat_poster.py を実装する**

```python
# src/plugins/chat_poster.py
from botbuilder.core import BotFrameworkAdapter, TurnContext
from botbuilder.schema import Activity, ConversationReference


class ChatPosterPlugin:
    def __init__(self, adapter: BotFrameworkAdapter, app_id: str) -> None:
        self._adapter = adapter
        self._app_id = app_id

    async def post(self, conversation_reference: ConversationReference, text: str) -> None:
        """
        Bot が主体的に会議チャットにメッセージを投稿する（プロアクティブメッセージ）。
        """
        async def callback(turn_context: TurnContext) -> None:
            await turn_context.send_activity(Activity(type="message", text=text))

        await self._adapter.continue_conversation(
            conversation_reference,
            callback,
            self._app_id,
        )
```

- [ ] **Step 6: テストが通ることを確認する**

```bash
pytest tests/test_answer_generation.py tests/test_chat_poster.py -v
```

Expected: `2 passed`

- [ ] **Step 7: コミット**

```bash
git add src/plugins/answer_generation.py src/plugins/chat_poster.py \
        tests/test_answer_generation.py tests/test_chat_poster.py
git commit -m "feat(c02): add answer generation and chat poster plugins"
```

---

### Task 6: Orchestrator の実装（C-02 パイプライン統合）

**Files:**
- Create: `src/kernel/__init__.py`
- Create: `src/kernel/orchestrator.py`
- Create: `tests/test_orchestrator.py`

- [ ] **Step 1: テストを書く**

```python
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
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
pytest tests/test_orchestrator.py -v
```

Expected: `ImportError: cannot import name 'Orchestrator'`

- [ ] **Step 3: src/kernel/orchestrator.py を実装する**

```python
# src/kernel/orchestrator.py
from typing import Dict, Optional

import semantic_kernel as sk
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion, AzureTextEmbedding
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI
from botbuilder.core import BotFrameworkAdapter
from botbuilder.schema import ConversationReference

from src.models import Utterance
from src.plugins.intent_analysis import IntentAnalysisPlugin, IntentLabel
from src.plugins.rag_search import RAGSearchPlugin
from src.plugins.answer_generation import AnswerGenerationPlugin
from src.plugins.chat_poster import ChatPosterPlugin


class Orchestrator:
    """
    C-02 パイプライン: 発話受信 → 意図解析 → RAG 検索 → 回答生成 → チャット投稿。
    """

    def __init__(
        self,
        azure_openai_endpoint: str,
        azure_openai_key: str,
        chat_deployment: str,
        embedding_deployment: str,
        search_endpoint: str,
        search_key: str,
        search_index: str,
        adapter: BotFrameworkAdapter,
        app_id: str,
    ) -> None:
        kernel = sk.Kernel()
        kernel.add_service(
            AzureChatCompletion(
                service_id="chat",
                deployment_name=chat_deployment,
                endpoint=azure_openai_endpoint,
                api_key=azure_openai_key,
            )
        )

        openai_client = AzureOpenAI(
            azure_endpoint=azure_openai_endpoint,
            api_key=azure_openai_key,
            api_version="2024-02-01",
        )
        search_client = SearchClient(
            endpoint=search_endpoint,
            index_name=search_index,
            credential=AzureKeyCredential(search_key),
        )

        self._intent = IntentAnalysisPlugin(kernel)
        self._rag = RAGSearchPlugin(search_client, openai_client, embedding_deployment)
        self._answer = AnswerGenerationPlugin(kernel)
        self._poster = ChatPosterPlugin(adapter, app_id)
        # meeting_id -> ConversationReference（Bot が投稿する際に必要）
        self._conversation_references: Dict[str, ConversationReference] = {}

    def register_meeting(self, meeting_id: str, ref: ConversationReference) -> None:
        """会議開始時に ConversationReference を登録する。"""
        self._conversation_references[meeting_id] = ref

    def unregister_meeting(self, meeting_id: str) -> None:
        self._conversation_references.pop(meeting_id, None)

    async def process(self, utterance: Utterance) -> None:
        intent_result = await self._intent.analyze(utterance.text)

        if intent_result.intent != IntentLabel.SPEC_INQUIRY:
            return

        search_results = self._rag.search(keywords=intent_result.keywords, top_k=3)
        if not search_results:
            return

        answer = await self._answer.generate(
            utterance=utterance.text,
            search_results=search_results,
        )

        ref = self._conversation_references.get(utterance.meeting_id)
        if ref is None:
            return

        await self._poster.post(
            conversation_reference=ref,
            text=f"**[仕様補完]** {answer}",
        )
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
pytest tests/test_orchestrator.py -v
```

Expected: `2 passed`

- [ ] **Step 5: コミット**

```bash
git add src/kernel/__init__.py src/kernel/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(c02): implement C-02 orchestrator pipeline (intent -> RAG -> answer -> post)"
```

---

### Task 7: C-01 との接続（main.py の更新）

**Files:**
- Modify: `src/main.py`
- Modify: `src/bot/teams_bot.py`（Orchestrator 受け取り対応）

- [ ] **Step 1: teams_bot.py に orchestrator 連携を追加する**

`src/bot/teams_bot.py` の `MeetingBot.__init__` に `orchestrator` パラメータを追加し、`on_teams_meeting_start_activity` で `orchestrator.register_meeting` を呼ぶ。`on_teams_meeting_end_activity` で `orchestrator.unregister_meeting` を呼ぶ。

```python
# src/bot/teams_bot.py の __init__ シグネチャを変更する
from src.kernel.orchestrator import Orchestrator  # 追加

class MeetingBot(ActivityHandler):
    def __init__(
        self,
        cosmos_client: CosmosClient,
        graph_subscription: GraphTranscriptSubscription,
        on_utterance: Callable[[Utterance], Awaitable[None]],
        orchestrator: Optional["Orchestrator"] = None,  # 追加
    ) -> None:
        self._cosmos = cosmos_client
        self._subscription = graph_subscription
        self._on_utterance = on_utterance
        self._orchestrator = orchestrator
        self._active_subscriptions: dict[str, str] = {}
```

`on_teams_meeting_start_activity` に以下を追加する（`save_meeting` 呼び出しの後）：

```python
        if self._orchestrator:
            from botbuilder.schema import ConversationReference
            ref = TurnContext.get_conversation_reference(turn_context.activity)
            self._orchestrator.register_meeting(meeting_id, ref)
```

`on_teams_meeting_end_activity` に以下を追加する（`unsubscribe` の後）：

```python
        if self._orchestrator:
            self._orchestrator.unregister_meeting(meeting_id)
```

- [ ] **Step 2: src/main.py を更新する**

`main()` 関数内に Orchestrator の初期化と `on_utterance` コールバックの差し替えを追加する：

```python
# src/main.py の import に追加
from src.kernel.orchestrator import Orchestrator
from src.bot.app import create_app_with_adapter  # アダプターを外から渡すため

# main() 内の on_utterance を以下に差し替える
    orchestrator = Orchestrator(
        azure_openai_endpoint=config.azure_openai_endpoint,
        azure_openai_key=config.azure_openai_key,
        chat_deployment=config.azure_openai_deployment,
        embedding_deployment=config.azure_openai_embedding_deployment,
        search_endpoint=config.azure_search_endpoint,
        search_key=config.azure_search_key,
        search_index=config.azure_search_index,
        adapter=adapter,           # BotFrameworkAdapter をここで渡す
        app_id=config.microsoft_app_id,
    )

    async def on_utterance(utterance: Utterance) -> None:
        logger.info(f"[発話受信] {utterance.speaker_name}: {utterance.text}")
        await orchestrator.process(utterance)
```

- [ ] **Step 3: src/bot/app.py を編集して adapter を返す形に変更する**

```python
# src/bot/app.py の create_app を create_app_with_adapter に変更する
def create_app_with_adapter(
    bot: MeetingBot, app_id: str, app_password: str
) -> tuple[web.Application, BotFrameworkAdapter]:
    settings = BotFrameworkAdapterSettings(app_id=app_id, app_password=app_password)
    adapter = BotFrameworkAdapter(settings)

    async def messages(req: web.Request) -> web.Response:
        body = await req.json()
        activity = Activity().deserialize(body)
        auth_header = req.headers.get("Authorization", "")
        response = await adapter.process_activity(activity, auth_header, bot.on_turn)
        if response:
            return web.json_response(data=response.body, status=response.status)
        return web.Response(status=201)

    async def notifications(req: web.Request) -> web.Response:
        validation_token = req.rel_url.query.get("validationToken")
        if validation_token:
            return web.Response(text=validation_token, content_type="text/plain")
        body = await req.json()
        for notification in body.get("value", []):
            await bot.handle_transcript_notification(notification)
        return web.Response(status=202)

    app = web.Application()
    app.router.add_post("/api/messages", messages)
    app.router.add_post("/api/notifications", notifications)
    return app, adapter
```

- [ ] **Step 4: 全テストが通ることを確認する**

```bash
pytest -v
```

Expected: 全テスト PASSED（既存の C-01 テストを含む）

- [ ] **Step 5: コミット**

```bash
git add src/main.py src/bot/teams_bot.py src/bot/app.py
git commit -m "feat(c02): wire orchestrator into Teams bot and main entry point"
```

---

### Task 8: エンドツーエンド動作確認（モックを使ったローカルテスト）

**Files:**
- Create: `scripts/local_e2e_test.py`

- [ ] **Step 1: E2E テストスクリプトを作成する**

```python
# scripts/local_e2e_test.py
"""
C-01 + C-02 のローカル E2E テスト。
モック発話ソースで会議シナリオを再現し、意図解析→RAG→回答生成のログを確認する。
Azure OpenAI と Azure AI Search への実際の接続が必要。
"""
import asyncio
import logging
import os
from unittest.mock import AsyncMock, MagicMock
from src.config import Config
from src.models import Utterance
from src.kernel.orchestrator import Orchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TEST_UTTERANCES = [
    ("user-001", "田中 太郎", "了解しました。"),
    ("user-002", "鈴木 花子", "認証フローの仕様はどうなっていましたっけ？"),
    ("user-001", "田中 太郎", "SKU の定義を確認したいのですが。"),
    ("user-003", "佐藤 次郎", "ありがとうございます。"),
]


async def main():
    config = Config()

    # Adapter と app_id はモック（実際の Teams 投稿はしない）
    mock_adapter = MagicMock()
    mock_adapter.continue_conversation = AsyncMock()

    orchestrator = Orchestrator(
        azure_openai_endpoint=config.azure_openai_endpoint,
        azure_openai_key=config.azure_openai_key,
        chat_deployment=config.azure_openai_deployment,
        embedding_deployment=config.azure_openai_embedding_deployment,
        search_endpoint=config.azure_search_endpoint,
        search_key=config.azure_search_key,
        search_index=config.azure_search_index,
        adapter=mock_adapter,
        app_id=config.microsoft_app_id,
    )

    # 会議の ConversationReference をモック登録
    mock_ref = MagicMock()
    orchestrator.register_meeting("meet-local-001", mock_ref)

    for speaker_id, speaker_name, text in TEST_UTTERANCES:
        utterance = Utterance.new(
            meeting_id="meet-local-001",
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            text=text,
        )
        logger.info(f"--- 発話: [{speaker_name}] {text}")
        await orchestrator.process(utterance)

    # 投稿された内容を確認
    calls = mock_adapter.continue_conversation.call_args_list
    logger.info(f"\n=== チャット投稿数: {len(calls)} ===")
    for i, call in enumerate(calls, 1):
        # callback を実行して投稿内容を取り出す
        logger.info(f"投稿 {i}: (continue_conversation が呼ばれました)")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: E2E テストを実行する（Azure 接続必要）**

```bash
python scripts/local_e2e_test.py
```

Expected:
```
--- 発話: [田中 太郎] 了解しました。
--- 発話: [鈴木 花子] 認証フローの仕様はどうなっていましたっけ？
--- 発話: [田中 太郎] SKU の定義を確認したいのですが。
--- 発話: [佐藤 次郎] ありがとうございます。
=== チャット投稿数: 2 ===
```
（「了解」「ありがとう」は NORMAL なのでスキップ、「認証フロー」「SKU」は SPEC_INQUIRY なので投稿）

- [ ] **Step 3: コミット**

```bash
git add scripts/local_e2e_test.py
git commit -m "test(c02): add local E2E test script for C-01 + C-02 pipeline"
```

---

## C-02 完成チェックリスト（自己レビュー）

| 要件 | 対応タスク | 実装済みか |
|------|-----------|-----------|
| FR-02: 発話意図解析（仕様確認/曖昧/通常） | Task 3 | `IntentAnalysisPlugin` |
| FR-03: RAG 検索（ハイブリッド） | Task 2/4 | `RAGSearchPlugin` + AI Search |
| FR-04: 回答生成（200文字以内） | Task 5 | `AnswerGenerationPlugin` |
| FR-06: チャット投稿 | Task 5 | `ChatPosterPlugin` |
| C-02 パイプライン統合 | Task 6 | `Orchestrator` |
| C-01 との接続 | Task 7 | `main.py` + `MeetingBot` 更新 |
| F-01: 用語解説（SPEC_INQUIRY で自動対応） | Task 3 | 意図解析プロンプトに含む |
