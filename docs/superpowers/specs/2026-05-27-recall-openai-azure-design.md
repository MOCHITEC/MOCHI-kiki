# Recall.ai × Azure OpenAI Whisper × Azure AI Search — Full Pipeline

**Date:** 2026-05-27
**Author:** MOCHI-kiki Team
**Status:** Approved

---

## 0. Executive Summary

Recall.ai の WebSocket 経路はすでに実装済みで、Orchestrator（Azure OpenAI + Azure AI Search）とも配線済み。
本 spec は残る3つのギャップを埋める：

1. **Azure AI Search インデックスが空** — `setup_search_index.py` は存在するが未実行。サンプルドキュメント 11 件をインデックスへ投入する。
2. **音声が破棄されている** — `RECALL_AUDIO_SINK=noop`。Recall.ai WS で受け取った生 PCM を Azure OpenAI Whisper で文字起こしする `WhisperAudioSink` を実装する。
3. **重複発話の防止** — Whisper が有効なとき Recall ネイティブ ASR（`transcript.data`）を抑制し、Orchestrator へ二重投入しない。

---

## 1. Goals / Non-Goals

### Goals
1. `WhisperAudioSink` を実装する（`RECALL_AUDIO_SINK=azure_openai_whisper`）。
   - 無音検出（RMS ベース）でセグメントを分割し Azure OpenAI Whisper へ送信。
   - 得られたテキストを `Utterance` に変換して既存 Orchestrator パイプラインへ投入。
2. `setup_search_index.py` を実行し、Azure AI Search にドキュメントを投入する。
3. `scripts/check_search_index.py` を追加してインデックス状態をスモークテストできるようにする。
4. `RECALL_AUDIO_SINK=azure_openai_whisper` 時に `RecallWsHandler` がネイティブ `transcript.data` を無視するよう修正。
5. `src/api/recall_router.py` の word パース バグを修正（deprecated path だが残存バグを直す）。

### Non-Goals
- Azure AI Speech (Cognitive Services) への接続
- 話者ダイアライゼーション
- Whisper でのリアルタイム部分転写（partial）
- マルチレプリカ対応

---

## 2. Architecture

```
Recall.ai WebSocket
  ├─ transcript.data  ─────────────────────────────── suppressed when Whisper enabled
  │
  └─ audio_mixed_raw.data  (S16LE 16kHz mono PCM)
          │
          ▼
    WhisperAudioSink
      ├─ RMS per 20ms frame (640 bytes)
      ├─ silence ≥ SILENCE_MS  →  flush segment
      ├─ hard flush at MAX_SECS (30s)
      └─ PCM → WAV (RIFF header) → Azure OpenAI Whisper API
              │  text response
              ▼
        Utterance.new(meeting_id, speaker_id="whisper", text=...)
              │
              ▼
        on_utterance()  →  Orchestrator.process()
          ├─ IntentAnalysis       (Azure OpenAI gpt-4o)
          ├─ RAGSearch            (Azure AI Search + text-embedding-3-small)
          └─ AnswerGeneration     (Azure OpenAI gpt-4o)  →  Teams chat
```

---

## 3. WhisperAudioSink 詳細

### 3.1 無音検出

- **PCM フォーマット**: S16LE / 16 kHz / mono → 20ms フレーム = 640 bytes = 320 サンプル
- **RMS** = `sqrt(mean(sample²))` を各フレームで計算
- **無音判定**: RMS < `SILENCE_RMS_THRESHOLD`（デフォルト 300 / 32767 ≈ −40 dB）
- **セグメント終端**: 無音フレームが連続 ≥ `SILENCE_DURATION_MS`（デフォルト 600ms = 30フレーム）

### 3.2 バッファ管理

| パラメータ | デフォルト | 説明 |
|---|---|---|
| `SILENCE_RMS_THRESHOLD` | `300` | 無音判定 RMS 閾値 (0–32767) |
| `SILENCE_DURATION_MS` | `600` | この時間無音が続いたらフラッシュ (ms) |
| `MIN_SEGMENT_SECS` | `1` | これより短いセグメントは送信しない (s) |
| `MAX_SEGMENT_SECS` | `30` | この長さに達したら強制フラッシュ (s) |
| バッファ上限 | 2 MB ≈ 62s | 超過時は古いフレームを drop + WARN |

### 3.3 Whisper API 呼び出し

1. バッファの PCM bytes を RIFF/WAV ヘッダ付きでメモリ上に変換（標準 `wave` モジュール）
2. `openai.AsyncAzureOpenAI.audio.transcriptions.create()` を呼ぶ（`push()` が async のため sync client は不可）
   - `model=RECALL_WHISPER_DEPLOYMENT`
   - `language="ja"`
   - `file=("segment.wav", wav_bytes, "audio/wav")`
3. 返却テキストを `Utterance.new(meeting_id=..., speaker_id="whisper", speaker_name="Whisper ASR", text=...)` に変換
4. `await on_utterance(utterance)` で Orchestrator へ投入

### 3.4 新規 Config（env vars）

| Env | デフォルト | 説明 |
|---|---|---|
| `RECALL_WHISPER_DEPLOYMENT` | `whisper` | Azure OpenAI Whisper デプロイ名 |
| `RECALL_WHISPER_SILENCE_THRESHOLD` | `300` | RMS 無音閾値 |
| `RECALL_WHISPER_SILENCE_MS` | `600` | 無音継続時間 (ms) |
| `RECALL_WHISPER_MIN_SECS` | `1` | 最短セグメント (s) |
| `RECALL_WHISPER_MAX_SECS` | `30` | 最長セグメント / 強制フラッシュ (s) |

既存 `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_KEY` をそのまま流用する（新規 credential 不要）。

---

## 4. ネイティブ ASR 抑制

`RECALL_AUDIO_SINK=azure_openai_whisper` の場合、`RecallWsHandler._handle_transcript` の冒頭で早期 return する。
Whisper と Recall native ASR の両方が `on_utterance` を呼ぶと Orchestrator に二重投入されるため。

```python
# RecallWsHandler._handle_transcript の先頭に追加
if self._suppress_native_transcript:
    return
```

`_suppress_native_transcript` は `RecallWsHandler.__init__` に `suppress_native_transcript: bool = False` パラメータとして渡し、`main.py` が `config.recall_audio_sink == "azure_openai_whisper"` の場合に `True` を指定する。

---

## 5. Search Index セットアップ

### 5.1 実行手順

```bash
# .env を読み込んで実行
python scripts/setup_search_index.py
```

- `documents` インデックスを作成（すでに存在すれば上書き）
- `scripts/sample_docs/spec_sample.json` の 11 件に対して `text-embedding-3-small` でベクトル化
- Azure AI Search へアップロード

### 5.2 check_search_index.py（新規）

```
scripts/check_search_index.py
```

- インデックスが存在するか
- ドキュメント数を報告
- 1 件ベクトル検索を試してレスポンスを確認
- CI のスモークテストとして使用可能

---

## 6. バグ修正: recall_router.py

`src/api/recall_router.py` の `/api/recall/transcript`（deprecated）でワードパースが壊れている：

```python
# 現状（バグ）: words は list[dict]、str でフィルタすると常に空
text = " ".join(w for w in words if isinstance(w, str))

# 修正後: transcript_pipeline.py の _join_words と同じロジックを使う
from src.transcript.transcript_pipeline import extract_utterance_from_transcript_data
utterance = extract_utterance_from_transcript_data(body, meeting_id=bot_id)
```

---

## 7. 変更ファイル一覧

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `src/transcript/audio_sink.py` | 改修 | `WhisperAudioSink` クラス追加、`build_audio_sink` に `azure_openai_whisper` 追加 |
| `src/config.py` | 改修 | Whisper 関連 env 5 件追加、`_ALLOWED_AUDIO_SINKS` に `azure_openai_whisper` 追加 |
| `src/transcript/recall_ws_handler.py` | 改修 | `suppress_native_transcript` パラメータ追加 |
| `src/main.py` | 改修 | Whisper sink 生成時に `suppress_native_transcript=True` を渡す |
| `src/api/recall_router.py` | バグ修正 | word パース修正 |
| `scripts/check_search_index.py` | 新規 | インデックス状態スモークテスト |
| `.env` | 改修 | `RECALL_WHISPER_DEPLOYMENT=whisper`、`RECALL_AUDIO_SINK=azure_openai_whisper` 追加 |

---

## 8. テスト戦略

| レイヤ | 内容 |
|---|---|
| Unit: WhisperAudioSink | RMS 計算、無音検出、MAX_SECS 強制フラッシュ、MIN_SECS スキップ、WAV エンコード |
| Unit: WhisperAudioSink (Whisper API) | `openai` をモックして `transcriptions.create` の引数検証 |
| Unit: suppress_native_transcript | `suppress=True` のとき `_handle_transcript` が on_utterance を呼ばない |
| Unit: recall_router | 修正後の word パースで正しい text が生成される |
| Integration: check_search_index.py | 実際の Azure AI Search に接続して件数確認（CI では skip 可） |

---

## 9. ロールアウト

1. `setup_search_index.py` を実行してインデックスを構築
2. `RECALL_AUDIO_SINK=noop`（現状）のまま `WhisperAudioSink` をデプロイ（コードのみ）
3. dev 環境で `RECALL_AUDIO_SINK=azure_openai_whisper` に切り替えて実会議でテスト
4. 問題なければ prod へ展開
5. ロールバック: `RECALL_AUDIO_SINK=noop` に戻すだけ（Recall native ASR が即座に再有効化）
