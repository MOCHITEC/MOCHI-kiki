# Orchestrator Recall.ai Webhook API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `POST /api/recall/transcript` to the existing aiohttp server so a Recall.ai bot can send speech-to-text results directly to the Orchestrator.

**Architecture:** A new `RecallWebhookRouter` class in `src/api/recall_router.py` owns the route and handler. It is registered on the existing aiohttp `app` in `main.py` after the orchestrator is fully wired — before `runner.setup()`. No changes to `src/bot/app.py` are needed because the orchestrator depends on the adapter created inside `create_app_with_adapter`, so the route is registered in `main.py` after both are ready.

**Tech Stack:** Python 3.11+, aiohttp, pytest, pytest-asyncio, `unittest.mock` (AsyncMock/MagicMock)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/api/__init__.py` | Create | Package marker |
| `src/api/recall_router.py` | Create | `RecallWebhookRouter` — route + handler |
| `tests/test_recall_router.py` | Create | 6 unit tests for the router |
| `src/main.py` | Modify | Register `RecallWebhookRouter` after orchestrator is wired |

---

## Recall.ai Webhook Payload Reference

The handler only processes `transcript.data` events. All other events get `200 OK` with no side effects.

```json
{
  "event": "transcript.data",
  "data": {
    "bot_id": "bot_abc123",
    "data": {
      "speaker": "田中 太郎",
      "words": [
        {"text": "この"},
        {"text": "仕様は"}
      ]
    }
  }
}
```

Field mapping:
- `data.bot_id` → `Utterance.meeting_id`
- `data.data.speaker` → `Utterance.speaker_name`
- `data.data.speaker.replace(" ", "-")` → `Utterance.speaker_id`
- `" ".join(w["text"] for w in data.data.words).strip()` → `Utterance.text`

---

### Task 1: Create `src/api` package

**Files:**
- Create: `src/api/__init__.py`

- [ ] **Step 1: Create the package marker**

Create `src/api/__init__.py` with empty content.

- [ ] **Step 2: Verify import works**

Run:
```bash
python -c "import src.api; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/api/__init__.py
git commit -m "chore: add src/api package"
```

---

### Task 2: Write failing tests for `RecallWebhookRouter`

**Files:**
- Create: `tests/test_recall_router.py`

- [ ] **Step 1: Create the test file**

Create `tests/test_recall_router.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.api.recall_router import RecallWebhookRouter


def make_request(body: dict) -> MagicMock:
    req = MagicMock()
    req.json = AsyncMock(return_value=body)
    return req


VALID_PAYLOAD = {
    "event": "transcript.data",
    "data": {
        "bot_id": "bot_abc123",
        "data": {
            "speaker": "田中 太郎",
            "words": [
                {"text": "この"},
                {"text": "仕様は"},
            ],
        },
    },
}


@pytest.fixture
def orchestrator():
    mock = MagicMock()
    mock.process = AsyncMock()
    return mock


@pytest.fixture
def cosmos():
    mock = MagicMock()
    mock.save_utterance = AsyncMock()
    return mock


@pytest.fixture
def router(orchestrator):
    return RecallWebhookRouter(orchestrator=orchestrator)


@pytest.fixture
def router_with_cosmos(orchestrator, cosmos):
    return RecallWebhookRouter(orchestrator=orchestrator, cosmos=cosmos)


@pytest.mark.asyncio
async def test_valid_payload_calls_orchestrator(router, orchestrator):
    req = make_request(VALID_PAYLOAD)
    resp = await router._handle(req)
    assert resp.status == 202
    orchestrator.process.assert_called_once()
    utterance = orchestrator.process.call_args[0][0]
    assert utterance.meeting_id == "bot_abc123"
    assert utterance.speaker_name == "田中 太郎"
    assert utterance.speaker_id == "田中-太郎"
    assert utterance.text == "この 仕様は"


@pytest.mark.asyncio
async def test_non_target_event_is_ignored(router, orchestrator):
    req = make_request({"event": "bot.status_change", "data": {}})
    resp = await router._handle(req)
    assert resp.status == 200
    orchestrator.process.assert_not_called()


@pytest.mark.asyncio
async def test_empty_words_is_ignored(router, orchestrator):
    payload = {
        "event": "transcript.data",
        "data": {
            "bot_id": "bot_abc123",
            "data": {"speaker": "田中 太郎", "words": []},
        },
    }
    req = make_request(payload)
    resp = await router._handle(req)
    assert resp.status == 200
    orchestrator.process.assert_not_called()


@pytest.mark.asyncio
async def test_cosmos_none_does_not_error(router, orchestrator):
    # router fixture has cosmos=None — must not raise
    req = make_request(VALID_PAYLOAD)
    resp = await router._handle(req)
    assert resp.status == 202
    orchestrator.process.assert_called_once()


@pytest.mark.asyncio
async def test_orchestrator_exception_returns_202(router, orchestrator):
    orchestrator.process.side_effect = RuntimeError("boom")
    req = make_request(VALID_PAYLOAD)
    resp = await router._handle(req)
    assert resp.status == 202


@pytest.mark.asyncio
async def test_cosmos_save_called_when_provided(router_with_cosmos, orchestrator, cosmos):
    req = make_request(VALID_PAYLOAD)
    resp = await router_with_cosmos._handle(req)
    assert resp.status == 202
    cosmos.save_utterance.assert_called_once()
    utterance = cosmos.save_utterance.call_args[0][0]
    assert utterance.meeting_id == "bot_abc123"
    assert utterance.speaker_name == "田中 太郎"
```

- [ ] **Step 2: Run tests to confirm they fail with ImportError**

```bash
pytest tests/test_recall_router.py -v
```

Expected: `ImportError: cannot import name 'RecallWebhookRouter' from 'src.api.recall_router'`

---

### Task 3: Implement `RecallWebhookRouter`

**Files:**
- Create: `src/api/recall_router.py`

- [ ] **Step 1: Create the implementation**

Create `src/api/recall_router.py`:

```python
import logging
from aiohttp import web
from src.models import Utterance

logger = logging.getLogger(__name__)


class RecallWebhookRouter:
    def __init__(self, orchestrator, cosmos=None) -> None:
        self._orchestrator = orchestrator
        self._cosmos = cosmos

    def register(self, app: web.Application) -> None:
        app.router.add_post("/api/recall/transcript", self._handle)

    async def _handle(self, req: web.Request) -> web.Response:
        body = await req.json()

        if body.get("event") != "transcript.data":
            return web.Response(status=200)

        data = body.get("data", {})
        inner = data.get("data", {})
        words = inner.get("words", [])

        if not words:
            return web.Response(status=200)

        text = " ".join(w.get("text", "") for w in words).strip()
        if not text:
            return web.Response(status=200)

        bot_id = data.get("bot_id", "unknown")
        speaker_name = inner.get("speaker", "不明")
        speaker_id = speaker_name.replace(" ", "-")

        utterance = Utterance.new(
            meeting_id=bot_id,
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            text=text,
        )

        if self._cosmos is not None:
            await self._cosmos.save_utterance(utterance)

        try:
            await self._orchestrator.process(utterance)
        except Exception:
            logger.exception("orchestrator.process() failed for utterance %s", utterance.utterance_id)

        return web.Response(status=202)
```

- [ ] **Step 2: Run tests — all 6 must pass**

```bash
pytest tests/test_recall_router.py -v
```

Expected:
```
test_valid_payload_calls_orchestrator PASSED
test_non_target_event_is_ignored PASSED
test_empty_words_is_ignored PASSED
test_cosmos_none_does_not_error PASSED
test_orchestrator_exception_returns_202 PASSED
test_cosmos_save_called_when_provided PASSED
6 passed
```

- [ ] **Step 3: Run the full test suite to confirm no regressions**

```bash
pytest -v
```

Expected: all existing tests still pass, 6 new tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/api/recall_router.py tests/test_recall_router.py
git commit -m "feat: add RecallWebhookRouter for Recall.ai speech-to-text webhook"
```

---

### Task 4: Wire `RecallWebhookRouter` into `main.py`

**Files:**
- Modify: `src/main.py`

> **Note:** The orchestrator is created after `create_app_with_adapter()` because it requires the `adapter` that function creates internally. Registering the Recall route after the orchestrator is wired — but before `runner.setup()` — is correct aiohttp usage (routes can be added any time before the app starts).

- [ ] **Step 1: Open `src/main.py` and locate the section after orchestrator wiring**

The relevant section (lines 58–70) currently looks like:

```python
    # 5. set orchestrator.set_cosmos(cosmos)
    orchestrator.set_cosmos(cosmos)

    # 6. set bot._orchestrator = orchestrator
    bot._orchestrator = orchestrator

    # 7. define on_utterance closure using orchestrator
    async def on_utterance(utterance: Utterance) -> None:
        logger.info(f"[発話受信] {utterance.speaker_name}: {utterance.text}")
        await orchestrator.process(utterance)

    # 8. set bot._on_utterance = on_utterance
    bot._on_utterance = on_utterance

    runner = web.AppRunner(app)
```

- [ ] **Step 2: Add the import and route registration**

Replace the block above with:

```python
    # 5. set orchestrator.set_cosmos(cosmos)
    orchestrator.set_cosmos(cosmos)

    # 6. set bot._orchestrator = orchestrator
    bot._orchestrator = orchestrator

    # 7. define on_utterance closure using orchestrator
    async def on_utterance(utterance: Utterance) -> None:
        logger.info(f"[発話受信] {utterance.speaker_name}: {utterance.text}")
        await orchestrator.process(utterance)

    # 8. set bot._on_utterance = on_utterance
    bot._on_utterance = on_utterance

    # 9. mount Recall.ai webhook route
    from src.api.recall_router import RecallWebhookRouter
    RecallWebhookRouter(orchestrator=orchestrator, cosmos=cosmos).register(app)

    runner = web.AppRunner(app)
```

- [ ] **Step 3: Run the full test suite to confirm nothing broke**

```bash
pytest -v
```

Expected: all tests pass (the `main.py` change has no unit test because it is integration wiring — the unit behaviour is covered by `test_recall_router.py`).

- [ ] **Step 4: Smoke-check the import chain**

```bash
python -c "from src.api.recall_router import RecallWebhookRouter; print('import ok')"
```

Expected: `import ok`

- [ ] **Step 5: Commit**

```bash
git add src/main.py
git commit -m "feat: register RecallWebhookRouter in main — Recall.ai webhook live on /api/recall/transcript"
```

---

## Completion Checklist

| Spec requirement | Covered by |
|---|---|
| `POST /api/recall/transcript` endpoint exists | Task 3 — `RecallWebhookRouter.register()` |
| `transcript.data` event → `orchestrator.process()` | Task 3 — handler logic |
| Non-`transcript.data` events → 200, no processing | Task 2 test + Task 3 impl |
| `bot_id` → `meeting_id` | Task 3 — `data.get("bot_id")` |
| `speaker` → `speaker_name`, space→hyphen → `speaker_id` | Task 3 |
| words joined → `text` | Task 3 |
| Empty text → skip | Task 3 |
| `cosmos.save_utterance()` called when cosmos provided | Task 2 test + Task 3 impl |
| `orchestrator.process()` exception → 202, no propagation | Task 2 test + Task 3 impl |
| No auth (open endpoint) | No middleware added |
| Wired into running server | Task 4 |
