# モックデータ — 会議チャットの仕様補完投稿 (Demo A 用)

会議中に MOCHI-kiki が会議チャットへ自動投稿した補足の例。
Recall.ai 経由の発話から `spec_inquiry` を検知 → AI Search ハイブリッド検索 →
GPT-4o で 200 字以内整形 → Bot Framework から proactive 投稿、という流れの結果。

文字起こしビューの同時間帯の発話と対応しています (`mock-transcript.md` 参照)。

---

**MOCHI-kiki**　·　14:01 PM

[仕様補完] Recall.ai の日本語 STT は `prioritize_accuracy` モード固定で、英語専用の `prioritize_low_latency` は選択不可。発話から `transcript.data` 取得まで実測 18 秒前後、長い発話で 30 秒超のため、会議中の即答用途には現状向いていない。

> 出典: `docs/recall-latency-notes.md` (社内)

---

**MOCHI-kiki**　·　14:06 PM

[仕様補完] Azure AI Speech のリアルタイム転写は WebSocket で `audio/pcm` 16kHz 16bit を受け取り、`SpeechRecognitionResult` を 200〜400ms 程度のレイテンシで返す。Recall.ai の `audio_mixed_raw` から抽出した PCM を中継すれば STT のみ置換可能。

> 出典: `docs/azure-speech-realtime.md` (社内)

---

**MOCHI-kiki**　·　14:11 PM

[仕様補完] `posted_completions` コンテナは partition key が `meeting_id`、`keyword_hash` フィールドで重複判定可能。`SELECT TOP 1 * FROM c WHERE c.meeting_id=@id AND c.keyword_hash=@hash AND c.posted_at>@threshold` の 1 クエリで 30 分 cooldown を判定できる。

> 出典: `src/persistence/posted_completions.py` (実装)
