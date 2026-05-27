# MOCHI-kiki × Recall.ai — Teams Meeting Manual

How to send the MOCHI-kiki bot into a Teams meeting, what it does, and how to verify it's working.

---

## How it works

```
Teams Meeting
  └─ Recall.ai bot (joins as a participant)
       └─ WebSocket → MOCHI-kiki server
            ├─ Raw PCM audio → WhisperAudioSink → Azure OpenAI Whisper → text
            └─ text → Orchestrator
                 ├─ Intent Analysis   (GPT-4o)
                 ├─ RAG Search        (Azure AI Search)
                 └─ Answer Generation (GPT-4o) → Teams chat message
```

The bot joins as a silent participant, transcribes speech via Whisper (silence-detection segmentation), and posts answers to the Teams chat when it detects a question or ambiguous statement.

---

## Prerequisites (one-time setup)

1. `.env` contains all required keys — run `scripts/fetch_azure_env.sh` or copy from `.env.example`

   Key variables:
   | Variable | Where to get it |
   |---|---|
   | `RECALL_API_KEY` | Recall.ai dashboard → API Keys |
   | `RECALL_WEBHOOK_SECRET` | Recall.ai dashboard → API Keys → Verification secret |
   | `RECALL_REGION` | e.g. `us-west-2` or `ap-northeast-1` |
   | `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_KEY` | Azure Portal → OpenAI resource |
   | `AZURE_SEARCH_ENDPOINT` / `AZURE_SEARCH_KEY` | Azure Portal → AI Search resource |
   | `AZURE_COSMOS_ENDPOINT` / `AZURE_COSMOS_KEY` | Azure Portal → Cosmos DB |

2. `RECALL_AUDIO_SINK=azure_openai_whisper` and `RECALL_WHISPER_DEPLOYMENT=whisper` are set in `.env` (already done if you ran Task 9)

3. Azure AI Search index is populated — verify with:
   ```
   python -c "from dotenv import load_dotenv; load_dotenv(); import runpy; runpy.run_path('scripts/check_search_index.py', run_name='__main__')"
   ```
   Expected: `✓ Documents: 11`

4. `az login` completed (needed for log streaming)

---

## Step 1 — Send the bot into a Teams meeting

Get the Teams meeting URL from the meeting invite or the "Copy link" button in Teams. It looks like:

```
https://teams.live.com/meet/9376323436183?p=Ir4cn611R861uOg6v4
```
or
```
https://teams.microsoft.com/l/meetup-join/...
```

Run the bot injection script (wraps in quotes — the `?p=` parameter is required):

```bash
./scripts/test_recall_ws.sh "https://teams.live.com/meet/<YOUR_MEETING_ID>?p=<TOKEN>"
```

The script:
1. Calls Recall.ai API to create a bot and get a `BOT_ID`
2. Upserts a Cosmos `meetings` record so the server can resolve `meeting_id`
3. Prints the `BOT_ID` and a ready-to-paste leave command

**Save the `BOT_ID` from the output** — you need it to stop the bot later.

---

## Step 2 — Allow the bot in Teams

In the Teams meeting, a waiting room notification appears: **"MOCHI-kiki-test wants to join"**.

Click **Admit**. The bot joins as a participant (no camera/mic — it only listens).

---

## Step 3 — Speak

Speak normally. After a ~600ms pause (silence), WhisperAudioSink flushes the segment to Azure OpenAI Whisper and the transcription enters the orchestrator pipeline.

The bot posts a reply to the Teams chat when it detects:
- A question about specs or requirements
- An ambiguous statement that needs clarification

---

## Step 4 — Monitor (optional)

Open a second terminal and stream the container logs:

```bash
az containerapp logs show -n mochikiki-bot-dev -g rg-mochi-kiki --follow \
  | grep --line-buffered -E "recall_ws_handler|WhisperAudioSink|orchestrator"
```

### Normal log sequence

```
[GET /api/recall/ws HTTP/1.1" 101 0]           ← WebSocket upgrade OK
RecallWsHandler: WS established remote=...     ← Recall connected
WhisperAudioSink: flush 2400 bytes → Whisper   ← Speech segment sent
Whisper response: "認証フローについて教えてください"  ← Transcription
Orchestrator: intent=spec_question             ← Intent detected
Orchestrator: search returned 3 docs           ← RAG search
Orchestrator: answer posted to Teams           ← Reply sent
...
RecallWsHandler: closed bot_id=... msgs=N audio_bytes=N drops=0  ← Session end
```

### Check bot status via API

```bash
source .env
curl -s -H "Authorization: Token $RECALL_API_KEY" \
  "https://${RECALL_REGION}.recall.ai/api/v1/bot/<BOT_ID>/" \
  | python -m json.tool | grep -A3 '"status_changes"'
```

`in_call_recording` = active. `call_ended` / `done` / `fatal` = finished.

---

## Step 5 — Stop the bot

```bash
source .env
curl -X POST \
  -H "Authorization: Token $RECALL_API_KEY" \
  "https://${RECALL_REGION}.recall.ai/api/v1/bot/<BOT_ID>/leave_call/"
```

> **Important:** Always stop the bot when done. A bot left running in a meeting continuously bills Recall.ai usage.

---

## Step 6 — Review the transcript

```bash
# List recent meetings
python scripts/show_transcript.py

# Full transcript for a specific bot session
python scripts/show_transcript.py <BOT_ID>

# Plain text export
python scripts/show_transcript.py <BOT_ID> --plain > transcript.txt
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Bot injection returns `authentication_failed` | Wrong region or revoked API key | Check `RECALL_REGION` and `RECALL_API_KEY` match the Recall.ai dashboard |
| Bot injection returns `Validation Error: meeting_url` | URL broken (newline / missing `?p=`) | Re-copy the URL; always wrap in double quotes |
| Bot stuck in waiting room | Teams did not admit it | Click Admit in the Teams meeting |
| `1008 close` in logs (repeated) | Cosmos `meetings` record missing | Wait up to 90 sec — Recall retries 30× every 3 sec. If it persists, re-inject the bot after the Cosmos upsert completes |
| `401` on WS connections from Recall | HMAC secret mismatch | Confirm `RECALL_WEBHOOK_SECRET` in `.env` matches the Verification secret in the Recall.ai dashboard |
| No Whisper transcription in logs | Audio sink not set to Whisper | Verify `RECALL_AUDIO_SINK=azure_openai_whisper` in `.env`; restart the server |
| Whisper transcription present but no Teams reply | RAG search returning 0 docs | Run `check_search_index.py` — if `Documents: 0`, re-run `setup_search_index.py` |
| Bot joins but Teams chat is silent | GPT-4o intent = not a question | Try asking a direct question like "認証フローについて教えてください" |
| `audio_mixed_raw.data` events not arriving | `recording_config.audio_mixed_raw` missing from bot creation | Check `_RECALL_WS_EVENTS` in `src/main.py` includes `audio_mixed_raw.data` |

---

## Rollback: disable Whisper

To revert to no audio processing without redeploying:

```bash
# In .env — change:
RECALL_AUDIO_SINK=noop
# Then restart the server
```

Recall native ASR (`transcript.data`) resumes immediately.

---

## Quick reference

| What | Command |
|---|---|
| Inject bot | `./scripts/test_recall_ws.sh "<TEAMS_URL>"` |
| Check bot status | `curl -H "Authorization: Token $RECALL_API_KEY" "https://$RECALL_REGION.recall.ai/api/v1/bot/<BOT_ID>/"` |
| Stop bot | `curl -X POST -H "Authorization: Token $RECALL_API_KEY" "https://$RECALL_REGION.recall.ai/api/v1/bot/<BOT_ID>/leave_call/"` |
| Stream logs | `az containerapp logs show -n mochikiki-bot-dev -g rg-mochi-kiki --follow` |
| View transcript | `python scripts/show_transcript.py <BOT_ID>` |
| Check search index | `python scripts/check_search_index.py` |
| Run tests | `pytest tests/ -v` |
