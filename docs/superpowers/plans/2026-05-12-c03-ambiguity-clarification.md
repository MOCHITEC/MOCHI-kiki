# C-03 曖昧発言の対話的明確化 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**前提条件:** C-01 と C-02 が完成していること。特に `Orchestrator`（`src/kernel/orchestrator.py`）、`IntentAnalysisPlugin`（`IntentLabel.AMBIGUOUS`）、`ChatPosterPlugin`、`CosmosClient` が動作していること。

**Goal:** 会議中の曖昧発言を検出し、発言者にプライベートメッセージで確認を求め、回答を受信したあと整理した文章を会議チャットに投稿する。

**Architecture:** `AmbiguityPlugin` が曖昧発言を検出したら Cosmos DB に `ClarificationSession` を作成する。Bot が発言者に対してプロアクティブメッセージ（アダプティブカード）で確認を送る。発言者が返信したら `ClarificationSession` を更新し、`ClarificationSummaryPlugin` が整理した文章を生成して会議チャットに投稿する。タイムアウト（60 秒）で未回答の場合はセッションを破棄する。

**Tech Stack:** Python 3.11+, semantic-kernel（C-02 から継承）, botbuilder-core（C-01 から継承）, azure-cosmos（C-01 から継承）, pytest, pytest-asyncio

---

## ファイル構成

```
src/
├── (C-01/C-02 で作成済み)
├── plugins/
│   ├── (C-02 で作成済み)
│   ├── ambiguity_detector.py        # 曖昧発言の検出と確認プロンプト生成
│   └── clarification_summary.py     # 回答を受けて整理文を生成
├── kernel/
│   ├── (C-02 で作成済み)
│   └── clarification_session.py     # ClarificationSession データクラス + Cosmos DB 管理
└── bot/
    └── teams_bot.py                 # 1:1 返信ハンドラを追加（on_message_activity）
tests/
├── (C-01/C-02 で作成済み)
├── test_ambiguity_detector.py
├── test_clarification_session.py
├── test_clarification_summary.py
└── test_clarification_flow.py       # 会話フロー全体の統合テスト
```

**Cosmos DB への追加コンテナ（CosmosClient に追加）:**
- `clarification_sessions` / パーティションキー: `/meeting_id`

---

### Task 1: ClarificationSession モデルと Cosmos DB 管理

**Files:**
- Create: `src/kernel/clarification_session.py`
- Modify: `src/storage/cosmos_client.py`（clarification_sessions コンテナ追加）
- Create: `tests/test_clarification_session.py`

- [ ] **Step 1: テストを書く**

```python
# tests/test_clarification_session.py
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from src.kernel.clarification_session import ClarificationSession, SessionStatus
from src.storage.cosmos_client import CosmosClient


def test_session_creation():
    session = ClarificationSession.new(
        meeting_id="meet-001",
        utterance_id="utt-001",
        speaker_id="user-111",
        speaker_name="田中 太郎",
        original_text="あれをやっておいて",
        clarification_question="「あれ」とは具体的に何を指しますか？担当タスクの名前か番号を教えてください。",
    )
    assert session.status == SessionStatus.PENDING
    assert session.reply is None
    assert session.meeting_id == "meet-001"


def test_session_to_dict():
    session = ClarificationSession.new(
        meeting_id="meet-001",
        utterance_id="utt-001",
        speaker_id="user-111",
        speaker_name="田中 太郎",
        original_text="あれをやっておいて",
        clarification_question="「あれ」とは何ですか？",
    )
    d = session.to_dict()
    assert d["id"] == session.session_id
    assert d["status"] == "pending"
    assert d["reply"] is None


@pytest.fixture
def mock_cosmos_container():
    container = MagicMock()
    container.upsert_item = AsyncMock(return_value={})
    container.read_item = AsyncMock()
    container.query_items = MagicMock(return_value=iter([]))
    return container


@pytest.mark.asyncio
async def test_cosmos_save_clarification_session(mock_cosmos_container):
    cosmos = CosmosClient.__new__(CosmosClient)
    cosmos._clarification_sessions = mock_cosmos_container

    session = ClarificationSession.new(
        meeting_id="meet-001",
        utterance_id="utt-002",
        speaker_id="user-222",
        speaker_name="鈴木 花子",
        original_text="その辺はいい感じで",
        clarification_question="「その辺」とは具体的にどの範囲を指しますか？",
    )
    await cosmos.save_clarification_session(session)
    mock_cosmos_container.upsert_item.assert_called_once()
    call_args = mock_cosmos_container.upsert_item.call_args[0][0]
    assert call_args["id"] == session.session_id
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
pytest tests/test_clarification_session.py -v
```

Expected: `ImportError: cannot import name 'ClarificationSession'`

- [ ] **Step 3: src/kernel/clarification_session.py を実装する**

```python
# src/kernel/clarification_session.py
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class SessionStatus(str, Enum):
    PENDING = "pending"         # 確認メッセージを送信済み、返信待ち
    REPLIED = "replied"         # 発言者が返信した
    SUMMARIZED = "summarized"   # 整理文を会議チャットに投稿した
    TIMED_OUT = "timed_out"     # タイムアウト（60 秒以内に返信なし）


@dataclass
class ClarificationSession:
    session_id: str
    meeting_id: str
    utterance_id: str
    speaker_id: str
    speaker_name: str
    original_text: str
    clarification_question: str
    status: SessionStatus
    created_at: datetime
    reply: Optional[str] = None
    summary: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.session_id,
            "meeting_id": self.meeting_id,
            "utterance_id": self.utterance_id,
            "speaker_id": self.speaker_id,
            "speaker_name": self.speaker_name,
            "original_text": self.original_text,
            "clarification_question": self.clarification_question,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "reply": self.reply,
            "summary": self.summary,
        }

    @classmethod
    def new(
        cls,
        meeting_id: str,
        utterance_id: str,
        speaker_id: str,
        speaker_name: str,
        original_text: str,
        clarification_question: str,
    ) -> "ClarificationSession":
        return cls(
            session_id=str(uuid.uuid4()),
            meeting_id=meeting_id,
            utterance_id=utterance_id,
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            original_text=original_text,
            clarification_question=clarification_question,
            status=SessionStatus.PENDING,
            created_at=datetime.now(tz=timezone.utc),
        )
```

- [ ] **Step 4: src/storage/cosmos_client.py を編集して clarification_sessions コンテナを追加する**

`CosmosClient.initialize` メソッドに以下を追加する：

```python
        self._clarification_sessions = await db.create_container_if_not_exists(
            id="clarification_sessions",
            partition_key=PartitionKey(path="/meeting_id"),
        )
```

`CosmosClient` クラスに以下のメソッドを追加する：

```python
    async def save_clarification_session(self, session: "ClarificationSession") -> None:
        from src.kernel.clarification_session import ClarificationSession
        await self._clarification_sessions.upsert_item(session.to_dict())

    async def get_clarification_session(
        self, session_id: str, meeting_id: str
    ) -> Optional[dict]:
        try:
            item = await self._clarification_sessions.read_item(
                item=session_id, partition_key=meeting_id
            )
            return item
        except Exception:
            return None
```

- [ ] **Step 5: テストが通ることを確認する**

```bash
pytest tests/test_clarification_session.py -v
```

Expected: `3 passed`

- [ ] **Step 6: コミット**

```bash
git add src/kernel/clarification_session.py src/storage/cosmos_client.py \
        tests/test_clarification_session.py
git commit -m "feat(c03): add ClarificationSession model and Cosmos DB storage"
```

---

### Task 2: 曖昧発言検出プラグインの実装

**Files:**
- Create: `src/plugins/ambiguity_detector.py`
- Create: `tests/test_ambiguity_detector.py`

- [ ] **Step 1: テストを書く**

```python
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
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
pytest tests/test_ambiguity_detector.py -v
```

Expected: `ImportError: cannot import name 'AmbiguityDetectorPlugin'`

- [ ] **Step 3: src/plugins/ambiguity_detector.py を実装する**

```python
# src/plugins/ambiguity_detector.py
import json
from dataclasses import dataclass

import semantic_kernel as sk
from semantic_kernel.functions import KernelArguments


AMBIGUITY_PROMPT = """
あなたは会議の発話を分析する AI です。
以下の発話が曖昧かどうかを判定し、JSON で返してください。

発話: {{$utterance}}

曖昧な発話の例:
- 主語が不明確: 「あれをやっておいて」「それで進めて」
- 目的語が不明確: 「その辺はいい感じで」「適当にやって」
- 代名詞の指示対象が不明: 「これ」「あれ」「そこ」が何を指すか不明

JSON のみを返す（説明不要）:
{
  "is_ambiguous": true | false,
  "reason": "曖昧と判断した理由（30文字以内）",
  "question": "発言者への確認質問（曖昧でない場合は空文字）"
}
"""


@dataclass
class AmbiguityResult:
    is_ambiguous: bool
    reason: str
    question: str


class AmbiguityDetectorPlugin:
    def __init__(self, kernel: sk.Kernel) -> None:
        self._kernel = kernel
        self._function = kernel.add_function(
            plugin_name="AmbiguityDetector",
            function_name="detect",
            prompt=AMBIGUITY_PROMPT,
        )

    async def detect(self, utterance: str) -> AmbiguityResult:
        result = await self._kernel.invoke(
            self._function,
            KernelArguments(utterance=utterance),
        )
        try:
            raw = json.loads(str(result))
            return AmbiguityResult(
                is_ambiguous=bool(raw.get("is_ambiguous", False)),
                reason=raw.get("reason", ""),
                question=raw.get("question", ""),
            )
        except (json.JSONDecodeError, ValueError):
            return AmbiguityResult(is_ambiguous=False, reason="", question="")
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
pytest tests/test_ambiguity_detector.py -v
```

Expected: `2 passed`

- [ ] **Step 5: コミット**

```bash
git add src/plugins/ambiguity_detector.py tests/test_ambiguity_detector.py
git commit -m "feat(c03): add ambiguity detector plugin"
```

---

### Task 3: 整理文生成プラグインの実装

**Files:**
- Create: `src/plugins/clarification_summary.py`
- Create: `tests/test_clarification_summary.py`

- [ ] **Step 1: テストを書く**

```python
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
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
pytest tests/test_clarification_summary.py -v
```

Expected: `ImportError: cannot import name 'ClarificationSummaryPlugin'`

- [ ] **Step 3: src/plugins/clarification_summary.py を実装する**

```python
# src/plugins/clarification_summary.py
import semantic_kernel as sk
from semantic_kernel.functions import KernelArguments


SUMMARY_PROMPT = """
会議で曖昧だった発言が明確になりました。以下の情報をもとに、
会議参加者全員に向けて 100 文字以内で状況を整理してください。

発言者: {{$speaker_name}}
元の発言: {{$original_text}}
確認した質問: {{$question}}
発言者の回答: {{$reply}}

整理文は「発言者名 + の発言 + 明確化した内容」の形式で書いてください。
例: 「田中さんの「あれ」は認証フローのレビュー（PR #42）を指していました。」
"""


class ClarificationSummaryPlugin:
    def __init__(self, kernel: sk.Kernel) -> None:
        self._kernel = kernel
        self._function = kernel.add_function(
            plugin_name="ClarificationSummary",
            function_name="summarize",
            prompt=SUMMARY_PROMPT,
        )

    async def summarize(
        self,
        speaker_name: str,
        original_text: str,
        clarification_question: str,
        reply: str,
    ) -> str:
        result = await self._kernel.invoke(
            self._function,
            KernelArguments(
                speaker_name=speaker_name,
                original_text=original_text,
                question=clarification_question,
                reply=reply,
            ),
        )
        text = str(result).strip()
        return text[:200] if len(text) > 200 else text
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
pytest tests/test_clarification_summary.py -v
```

Expected: `1 passed`

- [ ] **Step 5: コミット**

```bash
git add src/plugins/clarification_summary.py tests/test_clarification_summary.py
git commit -m "feat(c03): add clarification summary plugin"
```

---

### Task 4: Orchestrator への C-03 パイプライン追加

**Files:**
- Modify: `src/kernel/orchestrator.py`（C-03 パイプラインを追加）
- Create: `tests/test_clarification_flow.py`

- [ ] **Step 1: テストを書く**

```python
# tests/test_clarification_flow.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from src.models import Utterance
from src.kernel.orchestrator import Orchestrator
from src.plugins.intent_analysis import IntentResult, IntentLabel
from src.plugins.ambiguity_detector import AmbiguityResult
from src.kernel.clarification_session import SessionStatus


@pytest.fixture
def mock_components():
    intent = MagicMock()
    intent.analyze = AsyncMock(
        return_value=IntentResult(intent=IntentLabel.AMBIGUOUS, confidence=0.88, keywords=[])
    )

    ambiguity = MagicMock()
    ambiguity.detect = AsyncMock(
        return_value=AmbiguityResult(
            is_ambiguous=True,
            reason="主語が不明確",
            question="「あれ」とは何を指しますか？",
        )
    )

    cosmos = MagicMock()
    cosmos.save_clarification_session = AsyncMock()
    cosmos.get_clarification_session = AsyncMock(return_value=None)
    cosmos.save_utterance = AsyncMock()

    poster = MagicMock()
    poster.post = AsyncMock()

    summary = MagicMock()
    summary.summarize = AsyncMock(
        return_value="田中さんの「あれ」は PR #42 のレビューを指していました。"
    )

    return intent, ambiguity, cosmos, poster, summary


@pytest.fixture
def orchestrator_c03(mock_components):
    intent, ambiguity, cosmos, poster, summary = mock_components
    orc = Orchestrator.__new__(Orchestrator)
    orc._intent = intent
    orc._rag = MagicMock()
    orc._answer = MagicMock()
    orc._poster = poster
    orc._ambiguity = ambiguity
    orc._summary = summary
    orc._cosmos = cosmos
    orc._conversation_references = {"meet-001": MagicMock()}
    orc._speaker_references = {"user-111": MagicMock()}
    orc._pending_sessions = {}
    return orc


@pytest.mark.asyncio
async def test_ambiguous_utterance_sends_private_message(orchestrator_c03, mock_components):
    _, _, _, poster, _ = mock_components
    utterance = Utterance.new(
        meeting_id="meet-001",
        speaker_id="user-111",
        speaker_name="田中 太郎",
        text="あれをやっておいて",
    )
    await orchestrator_c03.process(utterance)

    # 発言者へのプライベートメッセージが送られたことを確認
    poster.post.assert_called_once()
    call_kwargs = poster.post.call_args[1]
    assert "あれ" in call_kwargs["text"] or "確認" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_reply_triggers_summary_and_meeting_post(orchestrator_c03, mock_components):
    _, _, cosmos, poster, summary = mock_components

    # セッションをセットアップ
    from src.kernel.clarification_session import ClarificationSession, SessionStatus
    session = ClarificationSession.new(
        meeting_id="meet-001",
        utterance_id="utt-001",
        speaker_id="user-111",
        speaker_name="田中 太郎",
        original_text="あれをやっておいて",
        clarification_question="「あれ」とは何ですか？",
    )
    cosmos.get_clarification_session = AsyncMock(return_value=session.to_dict())
    orchestrator_c03._pending_sessions["user-111"] = session.session_id

    await orchestrator_c03.handle_clarification_reply(
        speaker_id="user-111",
        meeting_id="meet-001",
        reply_text="認証フローのレビュー（PR #42）です",
    )

    # 整理文生成が呼ばれたことを確認
    summary.summarize.assert_called_once()
    # 会議チャットへの投稿が呼ばれたことを確認
    assert poster.post.call_count >= 1
    last_call = poster.post.call_args_list[-1]
    post_text = last_call[1]["text"]
    assert "**[明確化]**" in post_text
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
pytest tests/test_clarification_flow.py -v
```

Expected: テストは import に成功するが、`Orchestrator` に `_ambiguity` 属性がないためエラー

- [ ] **Step 3: src/kernel/orchestrator.py を編集して C-03 を追加する**

`Orchestrator.__init__` に追加する（既存の `__init__` の引数と初期化ブロックの末尾に追加）：

```python
        # C-03 用プラグイン
        from src.plugins.ambiguity_detector import AmbiguityDetectorPlugin
        from src.plugins.clarification_summary import ClarificationSummaryPlugin
        self._ambiguity = AmbiguityDetectorPlugin(kernel)
        self._summary = ClarificationSummaryPlugin(kernel)
        self._cosmos = None  # CosmosClient（外部から set_cosmos() で注入する）
        # speaker_id -> ConversationReference（1:1 チャット用）
        self._speaker_references: Dict[str, ConversationReference] = {}
        # speaker_id -> session_id（返信待ちセッション）
        self._pending_sessions: Dict[str, str] = {}
```

`Orchestrator` クラスに以下のメソッドを追加する：

```python
    def set_cosmos(self, cosmos: "CosmosClient") -> None:
        """C-03 で Cosmos DB に ClarificationSession を保存するために注入する。"""
        self._cosmos = cosmos

    def register_speaker(self, speaker_id: str, ref: ConversationReference) -> None:
        """発言者の 1:1 会話参照を登録する（会議参加者が Bot と会話開始したとき）。"""
        self._speaker_references[speaker_id] = ref
```

`Orchestrator.process` メソッドに C-03 分岐を追加する（`IntentLabel.SPEC_INQUIRY` の `if` 文の後）：

```python
        if intent_result.intent == IntentLabel.AMBIGUOUS:
            await self._handle_ambiguous(utterance)
            return
```

`Orchestrator` クラスに以下のプライベートメソッドを追加する：

```python
    async def _handle_ambiguous(self, utterance: Utterance) -> None:
        """曖昧発言を処理する。検出 → セッション作成 → 発言者に確認メッセージ送信。"""
        from src.kernel.clarification_session import ClarificationSession

        ambiguity = await self._ambiguity.detect(utterance.text)
        if not ambiguity.is_ambiguous:
            return

        session = ClarificationSession.new(
            meeting_id=utterance.meeting_id,
            utterance_id=utterance.utterance_id,
            speaker_id=utterance.speaker_id,
            speaker_name=utterance.speaker_name,
            original_text=utterance.text,
            clarification_question=ambiguity.question,
        )

        if self._cosmos:
            await self._cosmos.save_clarification_session(session)

        self._pending_sessions[utterance.speaker_id] = session.session_id

        speaker_ref = self._speaker_references.get(utterance.speaker_id)
        if speaker_ref is None:
            return

        # 発言者に 1:1 で確認メッセージを送る
        message = (
            f"確認させてください: {ambiguity.question}\n"
            f"（会議での発言「{utterance.text}」に関して）"
        )
        await self._poster.post(
            conversation_reference=speaker_ref,
            text=message,
        )

        # タイムアウト処理（60 秒後にセッションを破棄）
        import asyncio
        asyncio.create_task(self._timeout_session(utterance.speaker_id, session.session_id))

    async def _timeout_session(self, speaker_id: str, session_id: str) -> None:
        import asyncio
        from src.kernel.clarification_session import SessionStatus
        await asyncio.sleep(60)
        if self._pending_sessions.get(speaker_id) == session_id:
            self._pending_sessions.pop(speaker_id, None)

    async def handle_clarification_reply(
        self, speaker_id: str, meeting_id: str, reply_text: str
    ) -> None:
        """
        発言者が返信したときの処理。
        整理文を生成して会議チャットに投稿し、セッションを完了させる。
        """
        from src.kernel.clarification_session import SessionStatus

        session_id = self._pending_sessions.pop(speaker_id, None)
        if session_id is None:
            return

        session_dict = None
        if self._cosmos:
            session_dict = await self._cosmos.get_clarification_session(session_id, meeting_id)

        if session_dict is None:
            return

        summary = await self._summary.summarize(
            speaker_name=session_dict["speaker_name"],
            original_text=session_dict["original_text"],
            clarification_question=session_dict["clarification_question"],
            reply=reply_text,
        )

        ref = self._conversation_references.get(meeting_id)
        if ref is None:
            return

        await self._poster.post(
            conversation_reference=ref,
            text=f"**[明確化]** {summary}",
        )

        if self._cosmos:
            from src.kernel.clarification_session import ClarificationSession, SessionStatus
            updated = ClarificationSession(
                session_id=session_dict["id"],
                meeting_id=session_dict["meeting_id"],
                utterance_id=session_dict["utterance_id"],
                speaker_id=session_dict["speaker_id"],
                speaker_name=session_dict["speaker_name"],
                original_text=session_dict["original_text"],
                clarification_question=session_dict["clarification_question"],
                status=SessionStatus.SUMMARIZED,
                created_at=session_dict["created_at"]
                if isinstance(session_dict["created_at"], type(None))
                else __import__("datetime").datetime.fromisoformat(session_dict["created_at"]),
                reply=reply_text,
                summary=summary,
            )
            await self._cosmos.save_clarification_session(updated)
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
pytest tests/test_clarification_flow.py -v
```

Expected: `2 passed`

- [ ] **Step 5: 全テストが通ることを確認する**

```bash
pytest -v
```

Expected: 全テスト PASSED（C-01/C-02 テストを含む）

- [ ] **Step 6: コミット**

```bash
git add src/kernel/orchestrator.py tests/test_clarification_flow.py
git commit -m "feat(c03): add ambiguous utterance detection and clarification pipeline to orchestrator"
```

---

### Task 5: Teams Bot への返信ハンドラ追加

**Files:**
- Modify: `src/bot/teams_bot.py`（1:1 メッセージの受信処理を追加）

- [ ] **Step 1: テストを書く（既存 test_teams_bot.py に追記）**

`tests/test_teams_bot.py` に以下のテストを追加する：

```python
@pytest.mark.asyncio
async def test_1on1_message_triggers_clarification_reply(mock_cosmos, mock_subscription):
    from unittest.mock import AsyncMock, MagicMock
    mock_orchestrator = MagicMock()
    mock_orchestrator.handle_clarification_reply = AsyncMock()

    from src.bot.teams_bot import MeetingBot
    bot = MeetingBot(
        cosmos_client=mock_cosmos,
        graph_subscription=mock_subscription,
        on_utterance=AsyncMock(),
        orchestrator=mock_orchestrator,
    )

    # 会議の mapping を登録
    bot._active_meeting_by_speaker = {"user-111": "meet-001"}

    activity = MagicMock()
    activity.type = "message"
    activity.text = "認証フローのレビュー（PR #42）です"
    activity.conversation = MagicMock(conversation_type="personal")
    activity.from_property = MagicMock(id="user-111")

    turn_context = MagicMock()
    turn_context.activity = activity
    turn_context.send_activity = AsyncMock()

    await bot.on_message_activity(turn_context)

    mock_orchestrator.handle_clarification_reply.assert_called_once_with(
        speaker_id="user-111",
        meeting_id="meet-001",
        reply_text="認証フローのレビュー（PR #42）です",
    )
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
pytest tests/test_teams_bot.py::test_1on1_message_triggers_clarification_reply -v
```

Expected: `AssertionError` または AttributeError（`handle_clarification_reply` が呼ばれない）

- [ ] **Step 3: src/bot/teams_bot.py を編集して on_message_activity を追加する**

`MeetingBot.__init__` に以下を追加する：

```python
        # speaker_id -> meeting_id（どの会議中に曖昧発言したかの追跡）
        self._active_meeting_by_speaker: dict[str, str] = {}
```

`on_teams_meeting_start_activity` の `save_meeting` 呼び出し後に以下を追加する：

```python
        # 全参加者の speaker → meeting マッピングを事前登録（簡易版）
        # 実際は参加者リストを Graph API から取得するが、デモ用に発言時に登録する
```

`MeetingBot` クラスに以下のメソッドを追加する：

```python
    async def on_message_activity(self, turn_context: TurnContext) -> None:
        """
        1:1 チャットでのメッセージ受信（発言者からの確認返信）を処理する。
        会議チャット（conversation_type = "channel" or "groupChat"）は無視する。
        """
        conversation_type = getattr(turn_context.activity.conversation, "conversation_type", "")
        if conversation_type != "personal":
            return

        speaker_id = turn_context.activity.from_property.id
        reply_text = (turn_context.activity.text or "").strip()
        meeting_id = self._active_meeting_by_speaker.get(speaker_id)

        if not meeting_id or not reply_text:
            return

        if self._orchestrator:
            await self._orchestrator.handle_clarification_reply(
                speaker_id=speaker_id,
                meeting_id=meeting_id,
                reply_text=reply_text,
            )
            await turn_context.send_activity("ありがとうございます。会議チャットに反映しました。")

    def track_speaker_meeting(self, speaker_id: str, meeting_id: str) -> None:
        """発言者が曖昧発言をした際に、どの会議中かを記録する（Orchestrator から呼ぶ）。"""
        self._active_meeting_by_speaker[speaker_id] = meeting_id
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
pytest tests/test_teams_bot.py -v
```

Expected: 全テスト PASSED（既存 2 件 + 新規 1 件）

- [ ] **Step 5: コミット**

```bash
git add src/bot/teams_bot.py tests/test_teams_bot.py
git commit -m "feat(c03): add 1:1 reply handler to Teams bot for clarification responses"
```

---

### Task 6: main.py の更新（C-03 コンポーネント統合）

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: src/main.py を編集して C-03 コンポーネントを接続する**

`main()` 関数内の `orchestrator` 初期化の後に以下を追加する：

```python
    # C-03: Cosmos DB を Orchestrator に注入する
    orchestrator.set_cosmos(cosmos)

    # C-03: Bot が発言者の speaker_reference を Orchestrator に登録できるようにする
    # on_conversation_update_activity で会議参加者の 1:1 チャット参照を取得する
    # （Bot と事前に 1:1 で会話したユーザーの参照を登録）
```

`MeetingBot` の初期化時に `orchestrator` を渡す（既存コードを修正）：

```python
    bot = MeetingBot(
        cosmos_client=cosmos,
        graph_subscription=graph_sub,
        on_utterance=on_utterance,
        orchestrator=orchestrator,   # C-03 追加
    )
```

- [ ] **Step 2: 全テストが通ることを確認する**

```bash
pytest -v
```

Expected: 全テスト PASSED

- [ ] **Step 3: コミット**

```bash
git add src/main.py
git commit -m "feat(c03): wire clarification components into main entry point"
```

---

### Task 7: エンドツーエンド動作確認（C-03 を含む）

**Files:**
- Create: `scripts/local_e2e_c03_test.py`

- [ ] **Step 1: E2E テストスクリプトを作成する**

```python
# scripts/local_e2e_c03_test.py
"""
C-03 のローカル E2E テスト。
曖昧発言 → 確認メッセージ → 返信 → 整理文投稿 の一連フローを確認する。
Azure OpenAI への実際の接続が必要。
"""
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock
from src.config import Config
from src.models import Utterance
from src.kernel.orchestrator import Orchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main():
    config = Config()

    mock_adapter = MagicMock()
    posted_messages = []

    async def mock_continue_conversation(ref, callback, app_id):
        mock_turn = MagicMock()
        captured = []

        async def mock_send(activity):
            captured.append(activity.text if hasattr(activity, "text") else str(activity))

        mock_turn.send_activity = mock_send
        await callback(mock_turn)
        for msg in captured:
            posted_messages.append({"ref": ref, "text": msg})

    mock_adapter.continue_conversation = mock_continue_conversation

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

    meeting_ref = MagicMock()
    speaker_ref = MagicMock()
    orchestrator.register_meeting("meet-local-001", meeting_ref)
    orchestrator.register_speaker("user-111", speaker_ref)

    # Step 1: 曖昧発言
    logger.info("=== Step 1: 曖昧発言 ===")
    utterance = Utterance.new(
        meeting_id="meet-local-001",
        speaker_id="user-111",
        speaker_name="田中 太郎",
        text="あれをやっておいて",
    )
    await orchestrator.process(utterance)
    await asyncio.sleep(0.5)

    logger.info(f"投稿数（確認メッセージ）: {len(posted_messages)}")
    for m in posted_messages:
        logger.info(f"  投稿先: {'speaker(1:1)' if m['ref'] is speaker_ref else 'meeting'}")
        logger.info(f"  内容: {m['text']}")

    # Step 2: 発言者が返信
    logger.info("\n=== Step 2: 発言者が返信 ===")
    before_count = len(posted_messages)
    await orchestrator.handle_clarification_reply(
        speaker_id="user-111",
        meeting_id="meet-local-001",
        reply_text="認証フローのレビュー（PR #42）のことです",
    )
    await asyncio.sleep(0.5)

    new_posts = posted_messages[before_count:]
    logger.info(f"新規投稿数（整理文）: {len(new_posts)}")
    for m in new_posts:
        logger.info(f"  投稿先: {'speaker(1:1)' if m['ref'] is speaker_ref else 'meeting'}")
        logger.info(f"  内容: {m['text']}")

    assert any("明確化" in m["text"] for m in new_posts), "整理文が会議チャットに投稿されていません"
    logger.info("\n✅ C-03 フロー確認完了")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: E2E テストを実行する（Azure 接続必要）**

```bash
python scripts/local_e2e_c03_test.py
```

Expected:
```
=== Step 1: 曖昧発言 ===
投稿数（確認メッセージ）: 1
  投稿先: speaker(1:1)
  内容: 確認させてください: 「あれ」とは何を指しますか？...

=== Step 2: 発言者が返信 ===
新規投稿数（整理文）: 1
  投稿先: meeting
  内容: **[明確化]** 田中さんの「あれ」は認証フローのレビュー（PR #42）を指していました。

✅ C-03 フロー確認完了
```

- [ ] **Step 3: コミット**

```bash
git add scripts/local_e2e_c03_test.py
git commit -m "test(c03): add local E2E test for ambiguity clarification flow"
```

---

### Task 8: 全テスト確認と最終コミット

- [ ] **Step 1: 全テストを実行する**

```bash
pytest -v --tb=short
```

Expected: 全テスト PASSED（C-01/C-02/C-03 合計 12 件以上）

- [ ] **Step 2: Docker ビルドが成功することを確認する**

```bash
docker build -t mochi-kiki:c03 .
```

Expected: `Successfully built` でエラーなし

- [ ] **Step 3: 最終コミット**

```bash
git add -A
git commit -m "feat: complete C-03 ambiguity clarification - detect ambiguous utterances, ask speaker, post summary"
```

---

## C-03 完成チェックリスト（自己レビュー）

| 要件 | 対応タスク | 実装済みか |
|------|-----------|-----------|
| FR-05: 曖昧発言検知 | Task 2 | `AmbiguityDetectorPlugin` |
| FR-05: 発言者にプライベート確認 | Task 4 | `_handle_ambiguous` → `poster.post(speaker_ref)` |
| FR-05: 回答受信 | Task 5 | `MeetingBot.on_message_activity` |
| FR-05: 整理文を会議チャットに投稿 | Task 3/4 | `ClarificationSummaryPlugin` + `poster.post(meeting_ref)` |
| タイムアウト処理 | Task 4 | `_timeout_session`（60 秒） |
| Cosmos DB への会話ログ保存 | Task 1/4 | `ClarificationSession` → Cosmos DB |

**注意事項：**
- 発言者に 1:1 メッセージを送るには、事前に Bot と個人チャットを開始している必要がある（Teams の制約）。デモ時は参加者全員が事前に Bot を追加しておく。
- `register_speaker` の呼び出しタイミングは、Bot が参加者から 1:1 メッセージを受け取ったときに自動的に行う実装が理想。デモ用には手動で `conversation_update` イベントから取得する。
