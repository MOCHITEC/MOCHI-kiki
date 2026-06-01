# モックデータ — 議事録ビュー (Demo B 用)

GPT-4o による「議題 / 決定事項 / TODO / 質疑応答」の構造化 Markdown 全文再生成。
90 秒間隔で全文を毎回作り直す仕様。

会議: MOCHI-kiki 仕様詰めミーティング
日時: 2026-06-02 14:00–14:30
参加者: Ueda, Nakagawa

---

## 議題

1. Recall.ai レイテンシ実測値の共有と「会議中即答」の現実性
2. STT 置き換え候補の比較と方針
3. 補完投稿の重複防止 (cooldown 仕様)
4. AI Search 差分インデックスの自動更新化
5. 議事録 90 秒生成の本番想定検証
6. Teams App manifest 提出スケジュール

## 決定事項

- 「会議中に即答」の文言は「後追い補足」に修正し、補完投稿を現実的な位置づけに改める
- STT 置き換え先は Azure AI Speech に決定 (Azure 縛り)。Recall.ai の `audio_mixed_raw` を流し込む構成
- 補完投稿の重複防止は キーワードハッシュ + 30 分 cooldown で運用
- AI Search 差分インデックス更新を Container Apps Jobs の cron に移行 (月・木 03:00 JST)
- 議事録 90 秒生成の本番検証は来週水曜の定例ミーティング (1 時間想定) で実施
- Teams App manifest はプレビュー権限版でハッカソン提出。提出物に動作確認方法の注釈を付記

## TODO

- [ ] Nakagawa: Azure AI Speech + Recall.ai `audio_mixed_raw` の POC を来週着手
- [ ] Nakagawa: posted_completions cooldown ロジックの実装 (本日中)
- [ ] Nakagawa: AI Search 差分インデックス更新を Terraform / Container Apps Jobs cron に移行
- [ ] Ueda: 来週水曜の定例ミーティング録音同意を参加者から取得
- [ ] Ueda: ハッカソン提出物に「プレビュー権限で動作確認可能」の注釈を追記

## 質疑応答

**Q: STT を Azure AI Speech に置き換えても、Recall.ai の音声取得経路は残るのでは?**
A: Recall.ai の `audio_mixed_raw` を Azure Speech に流し込めば、Recall.ai は音声取得層として残しつつ STT のみ置換できる。POC を来週着手して実証する。

**Q: 議事録 90 秒生成のコストはどの程度になるか?**
A: 1 時間会議を 90 秒間隔で生成する場合、GPT-4o 呼び出しは約 40 回。試算では 1 万円以内に収まる見込み。

**Q: Teams App manifest の stable 取得はハッカソン提出に間に合うか?**
A: proof-of-team-installation のロールアウトに 2 週間掛かるため間に合わない。プレビュー権限版で提出し、注釈で「プレビュー権限で動作確認可能」と明示する方針。
