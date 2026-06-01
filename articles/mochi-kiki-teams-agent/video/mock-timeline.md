# モックデータ — タイムラインビュー (Demo B 用)

5 分ブロックごとに 150 字以内で要約。確定済みブロックは触らず、末尾ブロックのみ
90 秒間隔で再要約する仕様。

会議: MOCHI-kiki 仕様詰めミーティング (2026-06-02 14:00–14:30)

---

**14:00–14:05　Recall.ai レイテンシの実測共有**　*(確定済み)*

Recall.ai の日本語精度モードで発話から transcript.data 取得まで平均 18 秒、長い発話で 30 秒超。実測値は scripts/measure_recall_latency.py の runs/2026-05-28 に残置。「会議中に即答」は未達と認め、後追い補足の位置づけで合意。

---

**14:05–14:10　STT 置き換えの方針**　*(確定済み)*

代替候補 (Azure AI Speech / Deepgram Nova-3 / AssemblyAI Universal-2) のうち、Azure 縛りのため Azure AI Speech に決定。Recall.ai の audio_mixed_raw を Azure Speech へ中継する構成で POC は来週着手。

---

**14:10–14:15　補完投稿の重複防止**　*(確定済み)*

キーワードハッシュ + 30 分 cooldown で運用することで合意。Cosmos の posted_completions コンテナに timestamp が既存のためクエリ 1 本で実装可能。本日中の TODO に追加した。

---

**14:15–14:20　AI Search 差分更新の自動化**　*(確定済み)*

手動週次の index_refresh.sh を Container Apps Jobs の cron に移行。実行は月・木 03:00 JST、Cosmos throughput alarm の帯を外す配慮あり。Terraform で記述する方針。

---

**14:20–14:25　議事録 90 秒生成の本番検証計画**　*(確定済み)*

来週水曜の定例ミーティング (1 時間想定) を録音し本番検証する。GPT-4o 呼び出し 40 回、コストは 1 万円以内見込み。録音同意の取得は Ueda 担当。

---

**14:25–14:30　Teams App manifest 提出戦略**　*(末尾ブロック / 90 秒ごとに再要約中)*

proof-of-team-installation の stable 取得は 2 週間掛かるため、プレビュー権限版でハッカソン提出する方針に決定。提出物に「プレビュー権限で動作確認可」の注釈を添え、動画は proactive 投稿の挙動のみ提示する。
