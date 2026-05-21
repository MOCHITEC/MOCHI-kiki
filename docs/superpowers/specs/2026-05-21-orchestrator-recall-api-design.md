# Orchestrator API Server — Recall.ai Webhook Receiver

**Date:** 2026-05-21
**Author:** Hendra Guntur
**Status:** Approved

---

## 1. Goal

Add a webhook endpoint to the existing aiohttp server so that a Recall.ai bot (running inside a Teams meeting and transcribing audio via Azure AI Speech SDK) can POST speech-to-text results directly to the Orchestrator — complementing the existing Teams Live Transcription + Graph API path.

---

## 2. Architecture

```
Recall.ai bot (joined in Teams meeting)
  │  captures audio → Azure AI Speech SDK → transcribes text
  │
  ▼  POST /api/recall/transcript  (JSON webhook)
[aiohttp server — port 3978]
  │
  ▼
RecallWebhookRouter._handle()        ← src/api/recall_router.py
  │  1. ignore non-transcript.data events → 200 OK
  │  2. extract bot_id → meeting_id
  │  3. extract speaker → speaker_name, join words[*].text → text
  │  4. skip if assembled text is empty → 200 OK
  │  5. speaker_id = speaker_name.replace(" ", "-")
  │  6. Utterance.new(meeting_id, speaker_id, speaker_name, text)
  │  7. cosmos.save_utterance(utterance)   [if cosmos is not None]
  │  8. orchestrator.process(utterance)
  └─→ 202 Accepted
```

---

## 3. Recall.ai Webhook Payload

Recall.ai sends `transcript.data` events for finalised transcript chunks. Only this event type triggers processing; all others are acknowledged with `200 OK` and ignored.

```json
{
  "event": "transcript.data",
  "data": {
    "bot_id": "bot_xxx",
    "data": {
      "speaker": "田中 太郎",
      "words": ["この", "仕様は"]
    }
  }
}
```

**Field mapping to `Utterance`:**

| Recall.ai field | Utterance field | Notes |
|---|---|---|
| `data.bot_id` | `meeting_id` | Stable per Recall.ai bot session |
| `data.data.speaker` | `speaker_name` | Display name from meeting |
| `data.data.words[*]` joined with `" "` | `text` | Final transcript text; words is a flat string array |
| `speaker_name.replace(" ", "-")` | `speaker_id` | Derived; Recall.ai has no stable speaker ID. Simple space→hyphen replacement preserves non-ASCII characters (e.g. `"田中 太郎"` → `"田中-太郎"`). |

---

## 4. Components

### New files

| File | Purpose |
|---|---|
| `src/api/__init__.py` | Package marker |
| `src/api/recall_router.py` | `RecallWebhookRouter` class — owns route + handler |
| `tests/test_recall_router.py` | Unit tests for the router |

### Modified files

| File | Change |
|---|---|
| `src/main.py` | Adds top-level import of `RecallWebhookRouter` and registers the route after orchestrator is fully wired (step 9), before `runner.setup()`. `src/bot/app.py` is unchanged — the route is registered directly in `main.py` because the orchestrator depends on the adapter created inside `create_app_with_adapter()`, so it cannot be passed into that function without restructuring. |

### `RecallWebhookRouter` interface

```python
class RecallWebhookRouter:
    def __init__(self, orchestrator: Orchestrator, cosmos=None) -> None: ...
    def register(self, app: web.Application) -> None: ...  # mounts POST /api/recall/transcript
    async def _handle(self, req: web.Request) -> web.Response: ...
```

---

## 5. Error Handling

| Case | Behaviour |
|---|---|
| Event is not `transcript.data` | `200 OK`, no processing |
| `data.data.words` missing or empty | `200 OK`, no processing |
| Assembled `text` is blank after strip | `200 OK`, no processing |
| Malformed JSON body | aiohttp raises `400 Bad Request` automatically |
| `orchestrator.process()` raises | Log exception, return `202 Accepted` (prevents Recall.ai retry storm) |
| `cosmos` is `None` | Skip save, continue to orchestrator |

---

## 6. Authentication

No webhook signature verification for now (hackathon demo scope). The endpoint is open. A future `RECALL_WEBHOOK_SECRET` env var can gate HMAC verification without changing the router's public interface.

---

## 7. Tests

`tests/test_recall_router.py` covers:

1. **Valid payload** — `transcript.data` with words → `orchestrator.process()` called with correct `Utterance` fields (`meeting_id == bot_id`, `speaker_name`, assembled `text`)
2. **Non-target event** — `bot.status_change` or `transcript.partial_data` → `orchestrator.process()` not called, returns `200`
3. **Empty words list** — payload has `words: []` → skipped, returns `200`
4. **`cosmos` is `None`** — no `AttributeError`, orchestrator still called
5. **`orchestrator.process()` raises** — handler returns `202`, exception is logged not propagated

---

## 8. Impact on Existing Code

- `src/bot/app.py`: `create_app_with_adapter()` signature gains two **optional** keyword arguments (`orchestrator=None`, `cosmos=None`). Existing call sites without these args continue to work unchanged — the Recall.ai route is simply not mounted.
- `src/main.py`: Updated to pass `orchestrator` and `cosmos`; no structural change.
- No changes to `Orchestrator`, `Utterance`, or any plugin.
