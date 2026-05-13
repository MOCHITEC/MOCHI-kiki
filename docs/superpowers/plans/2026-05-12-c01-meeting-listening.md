# C-01 会議内容の常時リスニング 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teams 会議に Bot を参加させ、Teams Live Transcription の文字起こしストリームをリアルタイムで受信し、Cosmos DB に保存する。

**Architecture:** Bot Framework SDK (Python/aiohttp) で Teams Bot を構築し、会議開始イベントを受信したら Graph API 経由で Teams Live Transcription の変更通知を購読する。文字起こしセグメントが届くたびに `Utterance` として Cosmos DB に保存し、ダウンストリーム（C-02/C-03）へイベントキューで渡す。音声直接取得はリスクが高いため、Teams Live Transcription + Graph API 変更通知を採用する。

**Tech Stack:** Python 3.11+, botbuilder-core, botbuilder-integration-aiohttp, azure-cosmos, msgraph-core, aiohttp, pytest, pytest-asyncio

---

## ファイル構成

```
src/
├── config.py                      # 環境変数から設定読み込み
├── models.py                      # Utterance / Meeting データクラス
├── main.py                        # aiohttp サーバー起動エントリポイント
├── bot/
│   ├── __init__.py
│   ├── teams_bot.py               # TeamsActivityHandler - 会議開始/終了/transcriptイベント処理
│   └── app.py                     # aiohttp ルーティング + Bot Framework アダプター
├── transcript/
│   ├── __init__.py
│   ├── base.py                    # UtteranceSource 抽象基底クラス
│   ├── graph_subscription.py      # Graph API 変更通知の購読・管理
│   └── mock_source.py             # テスト用モック発話ソース
└── storage/
    ├── __init__.py
    └── cosmos_client.py           # Cosmos DB CRUD（utterances / meetings コンテナ）
tests/
├── conftest.py                    # 共有フィクスチャ（Mock設定など）
├── test_config.py
├── test_models.py
├── test_cosmos_client.py
├── test_graph_subscription.py
└── test_teams_bot.py
pyproject.toml
Dockerfile
.env.example
```

---

### Task 1: pyproject.toml とプロジェクト骨格の作成

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `src/__init__.py`, `src/bot/__init__.py`, `src/transcript/__init__.py`, `src/storage/__init__.py`
- Create: `tests/__init__.py`, `tests/conftest.py`

- [ ] **Step 1: pyproject.toml を作成する**

```toml
[project]
name = "mochi-kiki"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "botbuilder-core>=4.16.1",
    "botbuilder-integration-aiohttp>=4.16.1",
    "botbuilder-schema>=4.16.1",
    "azure-cosmos>=4.7.0",
    "msgraph-core>=1.1.0",
    "azure-identity>=1.17.0",
    "aiohttp>=3.10.0",
    "pydantic-settings>=2.3.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2.0",
    "pytest-asyncio>=0.23.0",
    "pytest-mock>=3.14.0",
    "httpx>=0.27.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 2: .env.example を作成する**

```bash
# Bot Framework
MICROSOFT_APP_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
MICROSOFT_APP_PASSWORD=your-bot-password

# Azure Cosmos DB
AZURE_COSMOS_ENDPOINT=https://your-account.documents.azure.com:443/
AZURE_COSMOS_KEY=your-cosmos-key
COSMOS_DATABASE=meeting_db

# Microsoft Graph API (アプリ登録の認証情報)
GRAPH_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
GRAPH_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
GRAPH_CLIENT_SECRET=your-graph-secret

# Graph 変更通知の受信先 URL（外部公開 URL が必要）
GRAPH_NOTIFICATION_URL=https://your-bot-url.azurecontainerapps.io/api/notifications

# App
PORT=3978
```

- [ ] **Step 3: `__init__.py` を空ファイルとして作成する**

```bash
touch src/__init__.py src/bot/__init__.py src/transcript/__init__.py src/storage/__init__.py
touch tests/__init__.py
```

- [ ] **Step 4: tests/conftest.py を作成する**

```python
# tests/conftest.py
import pytest

@pytest.fixture
def meeting_id() -> str:
    return "meeting-test-001"

@pytest.fixture
def speaker_id() -> str:
    return "user-aaa-111"

@pytest.fixture
def speaker_name() -> str:
    return "田中 太郎"
```

- [ ] **Step 5: 依存パッケージをインストールする**

```bash
pip install -e ".[dev]"
```

Expected: エラーなくインストール完了

- [ ] **Step 6: pytest が起動することを確認する**

```bash
pytest --collect-only
```

Expected: `no tests ran` または `0 tests collected`（エラーなし）

- [ ] **Step 7: コミット**

```bash
git add pyproject.toml .env.example src/ tests/
git commit -m "chore: initialize Python project structure for C-01"
```

---

### Task 2: データモデルの定義

**Files:**
- Create: `src/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: テストを書く**

```python
# tests/test_models.py
from datetime import datetime, timezone
from src.models import Utterance, Meeting

def test_utterance_creation():
    u = Utterance(
        utterance_id="utt-001",
        meeting_id="meet-001",
        speaker_id="user-111",
        speaker_name="田中 太郎",
        text="この機能の仕様はどうなっていますか？",
        timestamp=datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc),
    )
    assert u.utterance_id == "utt-001"
    assert u.language == "ja-JP"
    assert u.processed is False

def test_utterance_to_dict():
    u = Utterance(
        utterance_id="utt-002",
        meeting_id="meet-001",
        speaker_id="user-111",
        speaker_name="田中 太郎",
        text="テスト発言",
        timestamp=datetime(2026, 5, 12, 10, 1, 0, tzinfo=timezone.utc),
    )
    d = u.to_dict()
    assert d["id"] == "utt-002"
    assert d["meeting_id"] == "meet-001"
    assert d["text"] == "テスト発言"
    assert "timestamp" in d

def test_meeting_creation():
    m = Meeting(
        meeting_id="meet-001",
        thread_id="19:thread@thread.v2",
        organizer_id="user-000",
        started_at=datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc),
    )
    assert m.meeting_id == "meet-001"
    assert m.ended_at is None
    assert m.transcript_subscription_id is None
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
pytest tests/test_models.py -v
```

Expected: `ImportError: cannot import name 'Utterance' from 'src.models'`

- [ ] **Step 3: src/models.py を実装する**

```python
# src/models.py
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional
import uuid


@dataclass
class Utterance:
    utterance_id: str
    meeting_id: str
    speaker_id: str
    speaker_name: str
    text: str
    timestamp: datetime
    language: str = "ja-JP"
    processed: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.utterance_id,
            "meeting_id": self.meeting_id,
            "speaker_id": self.speaker_id,
            "speaker_name": self.speaker_name,
            "text": self.text,
            "timestamp": self.timestamp.isoformat(),
            "language": self.language,
            "processed": self.processed,
        }

    @classmethod
    def new(cls, meeting_id: str, speaker_id: str, speaker_name: str, text: str) -> "Utterance":
        return cls(
            utterance_id=str(uuid.uuid4()),
            meeting_id=meeting_id,
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            text=text,
            timestamp=datetime.now(tz=timezone.utc),
        )


@dataclass
class Meeting:
    meeting_id: str
    thread_id: str
    organizer_id: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    transcript_subscription_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.meeting_id,
            "thread_id": self.thread_id,
            "organizer_id": self.organizer_id,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "transcript_subscription_id": self.transcript_subscription_id,
        }
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
pytest tests/test_models.py -v
```

Expected: `3 passed`

- [ ] **Step 5: コミット**

```bash
git add src/models.py tests/test_models.py
git commit -m "feat(c01): add Utterance and Meeting data models"
```

---

### Task 3: Cosmos DB クライアントの実装

**Files:**
- Create: `src/storage/cosmos_client.py`
- Create: `tests/test_cosmos_client.py`

- [ ] **Step 1: テストを書く**

```python
# tests/test_cosmos_client.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from src.models import Utterance, Meeting
from src.storage.cosmos_client import CosmosClient


@pytest.fixture
def mock_cosmos_container():
    container = MagicMock()
    container.upsert_item = AsyncMock(return_value={})
    container.read_item = AsyncMock()
    return container


@pytest.fixture
def cosmos_client(mock_cosmos_container):
    client = CosmosClient.__new__(CosmosClient)
    client._utterances = mock_cosmos_container
    client._meetings = mock_cosmos_container
    return client


@pytest.mark.asyncio
async def test_save_utterance(cosmos_client, mock_cosmos_container):
    u = Utterance.new(
        meeting_id="meet-001",
        speaker_id="user-111",
        speaker_name="田中 太郎",
        text="仕様の確認をしたい",
    )
    await cosmos_client.save_utterance(u)
    mock_cosmos_container.upsert_item.assert_called_once()
    call_args = mock_cosmos_container.upsert_item.call_args[0][0]
    assert call_args["id"] == u.utterance_id
    assert call_args["text"] == "仕様の確認をしたい"


@pytest.mark.asyncio
async def test_save_meeting(cosmos_client, mock_cosmos_container):
    m = Meeting(
        meeting_id="meet-001",
        thread_id="19:abc@thread.v2",
        organizer_id="user-000",
        started_at=datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc),
    )
    await cosmos_client.save_meeting(m)
    mock_cosmos_container.upsert_item.assert_called_once()
    call_args = mock_cosmos_container.upsert_item.call_args[0][0]
    assert call_args["id"] == "meet-001"
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
pytest tests/test_cosmos_client.py -v
```

Expected: `ImportError: cannot import name 'CosmosClient' from 'src.storage.cosmos_client'`

- [ ] **Step 3: src/storage/cosmos_client.py を実装する**

```python
# src/storage/cosmos_client.py
from azure.cosmos.aio import CosmosClient as _AzureCosmosClient
from azure.cosmos import PartitionKey
from src.models import Utterance, Meeting


class CosmosClient:
    def __init__(self, endpoint: str, key: str, database_name: str) -> None:
        self._azure_client = _AzureCosmosClient(url=endpoint, credential=key)
        self._database_name = database_name
        self._utterances = None
        self._meetings = None

    async def initialize(self) -> None:
        """DB・コンテナが存在しない場合は作成する。"""
        db = await self._azure_client.create_database_if_not_exists(self._database_name)
        self._utterances = await db.create_container_if_not_exists(
            id="utterances",
            partition_key=PartitionKey(path="/meeting_id"),
        )
        self._meetings = await db.create_container_if_not_exists(
            id="meetings",
            partition_key=PartitionKey(path="/id"),
        )

    async def save_utterance(self, utterance: Utterance) -> None:
        await self._utterances.upsert_item(utterance.to_dict())

    async def save_meeting(self, meeting: Meeting) -> None:
        await self._meetings.upsert_item(meeting.to_dict())

    async def close(self) -> None:
        await self._azure_client.close()
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
pytest tests/test_cosmos_client.py -v
```

Expected: `2 passed`

- [ ] **Step 5: コミット**

```bash
git add src/storage/cosmos_client.py tests/test_cosmos_client.py
git commit -m "feat(c01): add Cosmos DB client for utterances and meetings"
```

---

### Task 4: Graph API 変更通知のサブスクリプション管理

**Files:**
- Create: `src/transcript/base.py`
- Create: `src/transcript/graph_subscription.py`
- Create: `src/transcript/mock_source.py`
- Create: `tests/test_graph_subscription.py`

- [ ] **Step 1: base.py（抽象基底クラス）を作成する**

```python
# src/transcript/base.py
from abc import ABC, abstractmethod
from typing import AsyncIterator
from src.models import Utterance


class UtteranceSource(ABC):
    """会議の発話を非同期で提供する抽象インターフェース。"""

    @abstractmethod
    async def start(self, meeting_id: str) -> None:
        """発話の受信を開始する。"""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """受信を停止し、リソースを解放する。"""
        ...
```

- [ ] **Step 2: mock_source.py を作成する（テスト・デモ用）**

```python
# src/transcript/mock_source.py
import asyncio
from src.transcript.base import UtteranceSource
from src.models import Utterance
from typing import Callable, Awaitable, List


class MockUtteranceSource(UtteranceSource):
    """テスト・デモ用のモック発話ソース。事前定義した発話リストを順番に emit する。"""

    def __init__(
        self,
        utterances: List[Utterance],
        on_utterance: Callable[[Utterance], Awaitable[None]],
        interval_seconds: float = 0.1,
    ) -> None:
        self._utterances = utterances
        self._on_utterance = on_utterance
        self._interval = interval_seconds
        self._task = None

    async def start(self, meeting_id: str) -> None:
        self._task = asyncio.create_task(self._emit_loop())

    async def _emit_loop(self) -> None:
        for u in self._utterances:
            await self._on_utterance(u)
            await asyncio.sleep(self._interval)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
```

- [ ] **Step 3: テストを書く**

```python
# tests/test_graph_subscription.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.transcript.graph_subscription import GraphTranscriptSubscription


@pytest.fixture
def mock_http_client():
    client = AsyncMock()
    client.post = AsyncMock(return_value=MagicMock(
        status=201,
        json=AsyncMock(return_value={"id": "sub-abc-123"}),
    ))
    client.delete = AsyncMock(return_value=MagicMock(status=204))
    return client


@pytest.mark.asyncio
async def test_subscribe_returns_subscription_id(mock_http_client):
    subscription = GraphTranscriptSubscription(
        tenant_id="tenant-001",
        client_id="client-001",
        client_secret="secret",
        notification_url="https://bot.example.com/api/notifications",
    )
    subscription._http_client = mock_http_client
    subscription._access_token = "fake-token"

    sub_id = await subscription.subscribe(
        meeting_id="meet-001",
        online_meeting_id="MSoxxx",
    )
    assert sub_id == "sub-abc-123"


@pytest.mark.asyncio
async def test_unsubscribe_calls_delete(mock_http_client):
    subscription = GraphTranscriptSubscription(
        tenant_id="tenant-001",
        client_id="client-001",
        client_secret="secret",
        notification_url="https://bot.example.com/api/notifications",
    )
    subscription._http_client = mock_http_client
    subscription._access_token = "fake-token"

    await subscription.unsubscribe("sub-abc-123")
    mock_http_client.delete.assert_called_once()
```

- [ ] **Step 4: テストが失敗することを確認する**

```bash
pytest tests/test_graph_subscription.py -v
```

Expected: `ImportError: cannot import name 'GraphTranscriptSubscription'`

- [ ] **Step 5: src/transcript/graph_subscription.py を実装する**

```python
# src/transcript/graph_subscription.py
import aiohttp
from datetime import datetime, timedelta, timezone
from typing import Callable, Awaitable, Optional
from src.models import Utterance


GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"


class GraphTranscriptSubscription:
    """Graph API 変更通知でTeams Live Transcription を購読する。"""

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        notification_url: str,
    ) -> None:
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._notification_url = notification_url
        self._access_token: Optional[str] = None
        self._http_client: Optional[aiohttp.ClientSession] = None

    async def _ensure_token(self) -> str:
        """アクセストークンを取得する（既にセットされている場合はスキップ）。"""
        if self._access_token:
            return self._access_token
        url = TOKEN_URL_TEMPLATE.format(tenant_id=self._tenant_id)
        data = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "scope": "https://graph.microsoft.com/.default",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data) as resp:
                body = await resp.json()
                self._access_token = body["access_token"]
        return self._access_token

    async def subscribe(self, meeting_id: str, online_meeting_id: str) -> str:
        """
        Teams Live Transcription の変更通知を購読する。
        Returns: subscription ID
        """
        token = await self._ensure_token()
        expiry = (datetime.now(tz=timezone.utc) + timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        payload = {
            "changeType": "created,updated",
            "notificationUrl": self._notification_url,
            "resource": f"/communications/onlineMeetings/{online_meeting_id}/transcripts",
            "expirationDateTime": expiry,
        }
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        if self._http_client:
            resp = await self._http_client.post(
                f"{GRAPH_BASE}/subscriptions", json=payload, headers=headers
            )
            body = await resp.json()
        else:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{GRAPH_BASE}/subscriptions", json=payload, headers=headers
                ) as resp:
                    body = await resp.json()

        return body["id"]

    async def unsubscribe(self, subscription_id: str) -> None:
        """購読を解除する。"""
        token = await self._ensure_token()
        headers = {"Authorization": f"Bearer {token}"}
        if self._http_client:
            await self._http_client.delete(
                f"{GRAPH_BASE}/subscriptions/{subscription_id}", headers=headers
            )
        else:
            async with aiohttp.ClientSession() as session:
                async with session.delete(
                    f"{GRAPH_BASE}/subscriptions/{subscription_id}", headers=headers
                ):
                    pass
```

- [ ] **Step 6: テストが通ることを確認する**

```bash
pytest tests/test_graph_subscription.py -v
```

Expected: `2 passed`

- [ ] **Step 7: コミット**

```bash
git add src/transcript/ tests/test_graph_subscription.py
git commit -m "feat(c01): add Graph API transcript subscription and mock source"
```

---

### Task 5: Teams Bot の実装（会議開始・終了・Transcript 通知処理）

**Files:**
- Create: `src/config.py`
- Create: `src/bot/teams_bot.py`
- Create: `src/bot/app.py`
- Create: `tests/test_teams_bot.py`

- [ ] **Step 1: src/config.py を作成する**

```python
# src/config.py
import os


class Config:
    microsoft_app_id: str
    microsoft_app_password: str
    cosmos_endpoint: str
    cosmos_key: str
    cosmos_database: str
    graph_tenant_id: str
    graph_client_id: str
    graph_client_secret: str
    graph_notification_url: str
    port: int

    def __init__(self) -> None:
        self.microsoft_app_id = os.environ["MICROSOFT_APP_ID"]
        self.microsoft_app_password = os.environ["MICROSOFT_APP_PASSWORD"]
        self.cosmos_endpoint = os.environ["AZURE_COSMOS_ENDPOINT"]
        self.cosmos_key = os.environ["AZURE_COSMOS_KEY"]
        self.cosmos_database = os.environ.get("COSMOS_DATABASE", "meeting_db")
        self.graph_tenant_id = os.environ["GRAPH_TENANT_ID"]
        self.graph_client_id = os.environ["GRAPH_CLIENT_ID"]
        self.graph_client_secret = os.environ["GRAPH_CLIENT_SECRET"]
        self.graph_notification_url = os.environ["GRAPH_NOTIFICATION_URL"]
        self.port = int(os.environ.get("PORT", "3978"))
```

- [ ] **Step 2: テストを書く**

```python
# tests/test_teams_bot.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from botbuilder.schema import Activity, ActivityTypes
from src.bot.teams_bot import MeetingBot


@pytest.fixture
def mock_cosmos():
    cosmos = MagicMock()
    cosmos.save_meeting = AsyncMock()
    cosmos.save_utterance = AsyncMock()
    return cosmos


@pytest.fixture
def mock_subscription():
    sub = MagicMock()
    sub.subscribe = AsyncMock(return_value="sub-abc-123")
    sub.unsubscribe = AsyncMock()
    return sub


@pytest.fixture
def mock_utterance_queue():
    return AsyncMock()


@pytest.fixture
def bot(mock_cosmos, mock_subscription, mock_utterance_queue):
    return MeetingBot(
        cosmos_client=mock_cosmos,
        graph_subscription=mock_subscription,
        on_utterance=mock_utterance_queue,
    )


@pytest.mark.asyncio
async def test_on_meeting_start_saves_meeting(bot, mock_cosmos):
    activity = MagicMock()
    activity.channel_data = {
        "meeting": {"id": "meet-001"},
        "onlineMeetingId": "MSo-online-001",
    }
    activity.conversation = MagicMock(id="19:thread@thread.v2")
    activity.from_property = MagicMock(id="user-000")
    turn_context = MagicMock()
    turn_context.activity = activity

    await bot.on_teams_meeting_start_activity(turn_context)

    mock_cosmos.save_meeting.assert_called_once()
    saved_meeting = mock_cosmos.save_meeting.call_args[0][0]
    assert saved_meeting.meeting_id == "meet-001"


@pytest.mark.asyncio
async def test_on_meeting_start_subscribes_transcript(bot, mock_subscription):
    activity = MagicMock()
    activity.channel_data = {
        "meeting": {"id": "meet-002"},
        "onlineMeetingId": "MSo-online-002",
    }
    activity.conversation = MagicMock(id="19:thread@thread.v2")
    activity.from_property = MagicMock(id="user-000")
    turn_context = MagicMock()
    turn_context.activity = activity

    await bot.on_teams_meeting_start_activity(turn_context)

    mock_subscription.subscribe.assert_called_once_with(
        meeting_id="meet-002",
        online_meeting_id="MSo-online-002",
    )
```

- [ ] **Step 3: テストが失敗することを確認する**

```bash
pytest tests/test_teams_bot.py -v
```

Expected: `ImportError: cannot import name 'MeetingBot' from 'src.bot.teams_bot'`

- [ ] **Step 4: src/bot/teams_bot.py を実装する**

```python
# src/bot/teams_bot.py
import asyncio
from datetime import datetime, timezone
from typing import Callable, Awaitable, Optional

from botbuilder.core import ActivityHandler, TurnContext
from botbuilder.schema import Activity

from src.models import Meeting, Utterance
from src.storage.cosmos_client import CosmosClient
from src.transcript.graph_subscription import GraphTranscriptSubscription


class MeetingBot(ActivityHandler):
    def __init__(
        self,
        cosmos_client: CosmosClient,
        graph_subscription: GraphTranscriptSubscription,
        on_utterance: Callable[[Utterance], Awaitable[None]],
    ) -> None:
        self._cosmos = cosmos_client
        self._subscription = graph_subscription
        self._on_utterance = on_utterance
        # meeting_id -> subscription_id のマッピング
        self._active_subscriptions: dict[str, str] = {}

    async def on_teams_meeting_start_activity(self, turn_context: TurnContext) -> None:
        channel_data = turn_context.activity.channel_data or {}
        meeting_info = channel_data.get("meeting", {})
        meeting_id = meeting_info.get("id", "unknown")
        online_meeting_id = channel_data.get("onlineMeetingId", "")
        thread_id = turn_context.activity.conversation.id
        organizer_id = turn_context.activity.from_property.id

        meeting = Meeting(
            meeting_id=meeting_id,
            thread_id=thread_id,
            organizer_id=organizer_id,
            started_at=datetime.now(tz=timezone.utc),
        )

        sub_id = await self._subscription.subscribe(
            meeting_id=meeting_id,
            online_meeting_id=online_meeting_id,
        )
        meeting.transcript_subscription_id = sub_id
        self._active_subscriptions[meeting_id] = sub_id

        await self._cosmos.save_meeting(meeting)

    async def on_teams_meeting_end_activity(self, turn_context: TurnContext) -> None:
        channel_data = turn_context.activity.channel_data or {}
        meeting_id = channel_data.get("meeting", {}).get("id", "unknown")

        sub_id = self._active_subscriptions.pop(meeting_id, None)
        if sub_id:
            await self._subscription.unsubscribe(sub_id)

    async def handle_transcript_notification(self, notification: dict) -> None:
        """
        Graph API の変更通知を受け取り、発話として処理する。
        notification は Graph API の changeNotification オブジェクト。
        """
        resource_data = notification.get("resourceData", {})
        text = resource_data.get("text", "").strip()
        if not text:
            return

        meeting_id = resource_data.get("meetingId", "unknown")
        utterance = Utterance.new(
            meeting_id=meeting_id,
            speaker_id=resource_data.get("speakerId", "unknown"),
            speaker_name=resource_data.get("speakerDisplayName", "不明"),
            text=text,
        )

        await self._cosmos.save_utterance(utterance)
        await self._on_utterance(utterance)
```

- [ ] **Step 5: テストが通ることを確認する**

```bash
pytest tests/test_teams_bot.py -v
```

Expected: `2 passed`

- [ ] **Step 6: src/bot/app.py を作成する**

```python
# src/bot/app.py
import json
from aiohttp import web
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings
from botbuilder.schema import Activity

from src.bot.teams_bot import MeetingBot


def create_app(bot: MeetingBot, app_id: str, app_password: str) -> web.Application:
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
        """Graph API 変更通知の受信エンドポイント。"""
        # Graph API の検証トークンハンドシェイク
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
    return app
```

- [ ] **Step 7: コミット**

```bash
git add src/config.py src/bot/teams_bot.py src/bot/app.py tests/test_teams_bot.py
git commit -m "feat(c01): implement Teams bot with meeting start/end and transcript notification handling"
```

---

### Task 6: エントリポイントとローカル動作確認

**Files:**
- Create: `src/main.py`

- [ ] **Step 1: src/main.py を作成する**

```python
# src/main.py
import asyncio
import logging
from aiohttp import web
from src.config import Config
from src.storage.cosmos_client import CosmosClient
from src.transcript.graph_subscription import GraphTranscriptSubscription
from src.bot.teams_bot import MeetingBot
from src.bot.app import create_app
from src.models import Utterance

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def on_utterance(utterance: Utterance) -> None:
    """発話受信コールバック（C-02/C-03 のオーケストレーターがここに接続する）。"""
    logger.info(f"[発話受信] {utterance.speaker_name}: {utterance.text}")


async def main() -> None:
    config = Config()

    cosmos = CosmosClient(
        endpoint=config.cosmos_endpoint,
        key=config.cosmos_key,
        database_name=config.cosmos_database,
    )
    await cosmos.initialize()
    logger.info("Cosmos DB 接続完了")

    graph_sub = GraphTranscriptSubscription(
        tenant_id=config.graph_tenant_id,
        client_id=config.graph_client_id,
        client_secret=config.graph_client_secret,
        notification_url=config.graph_notification_url,
    )

    bot = MeetingBot(
        cosmos_client=cosmos,
        graph_subscription=graph_sub,
        on_utterance=on_utterance,
    )

    app = create_app(bot, config.microsoft_app_id, config.microsoft_app_password)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.port)
    await site.start()
    logger.info(f"Bot サーバー起動: port {config.port}")

    try:
        await asyncio.Event().wait()
    finally:
        await cosmos.close()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: 全テストが通ることを確認する**

```bash
pytest -v
```

Expected: 全テスト PASSED

- [ ] **Step 3: コミット**

```bash
git add src/main.py
git commit -m "feat(c01): add main entry point with Cosmos and Bot wiring"
```

---

### Task 7: Dockerfile とローカルコンテナ起動確認

**Files:**
- Create: `Dockerfile`

- [ ] **Step 1: Dockerfile を作成する**

```dockerfile
# Dockerfile
FROM python:3.11-slim AS builder
WORKDIR /app
RUN pip install --upgrade pip
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

FROM python:3.11-slim AS runtime
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ ./src/
ENV PYTHONPATH=/app
CMD ["python", "-m", "src.main"]
```

- [ ] **Step 2: Docker イメージをビルドする**

```bash
docker build -t mochi-kiki:local .
```

Expected: `Successfully built` でエラーなし

- [ ] **Step 3: 環境変数なしで起動確認（KeyError が出ることを確認する）**

```bash
docker run --rm mochi-kiki:local 2>&1 | head -5
```

Expected: `KeyError: 'MICROSOFT_APP_ID'`（環境変数未設定のため正常）

- [ ] **Step 4: コミット**

```bash
git add Dockerfile
git commit -m "chore(c01): add Dockerfile for containerized deployment"
```

---

## C-01 完成チェックリスト（自己レビュー）

要件への対応確認：

| 要件 | 対応タスク | 実装済みか |
|------|-----------|-----------|
| FR-01: Teams 会議音声の文字起こし | Task 4/5 | Graph API + Live Transcription |
| FR-08: 会議開始イベントの取得 | Task 5 | `on_teams_meeting_start_activity` |
| utterances を Cosmos DB に保存 | Task 3/5 | `CosmosClient.save_utterance` |
| ダウンストリームへの発話通知 | Task 5/6 | `on_utterance` コールバック |
| テスト可能な抽象レイヤー | Task 4 | `UtteranceSource`, `MockUtteranceSource` |

**注意事項：**
- Graph API の変更通知を受けるには、Bot のエンドポイントが外部公開されている必要がある。ローカル開発では [ngrok](https://ngrok.com) を使う。
- Teams Live Transcription を使うには Microsoft 365 E3 以上または Teams Premium が必要。デモ時はモックソースで代替可能。
