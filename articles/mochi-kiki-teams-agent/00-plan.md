# mochi-kiki-teams-agent — 企画書

- 作成日: 2026-05-31
- ステージ: planned
- 主筆: Ruuuhs (@mochitec)
- canonical platform: Zenn
- 提出先: Microsoft Agent Hackathon 2026 (powered by Tokyo Electron Device)

## 方針

- **文体: ですます調** (`guidelines/brand-guidelines.md` の Zenn / 外部技術ブログ default に準拠)
- **ハッカソン提出記事**。実装の選択理由・ハマりどころ・コスト最適化まで含めた hands-on レポート
- 「Copilot で既に出来る要約」とは差別化された「会議中にリアルタイム介入する Agentic AI」を主軸に置く

## thesis (一文)

Teams 会議に常駐し、仕様不明な発言を RAG で即答し、曖昧発言には発言者に問い返してから整理文を投稿する Agentic AI を、Azure + Semantic Kernel + Recall.ai WS で 2 週間で組んだ実装記録。

## audience

- 前提知識: Python / Azure リソース 1 つでも触ったことがある / RAG という単語が分かる
- 現状の不満: Microsoft 365 Copilot Recap は便利だが「会議中に介入してくれない」/ Teams Bot の音声取得は Call Records API のハードルが高い
- 読み終わったあと: Recall.ai WS で音声と文字起こしを取り、Semantic Kernel で意図 → RAG → 投稿の Agentic ループを組む型が分かる

## angle / hook

**痛み (フック冒頭)**: Teams 会議の「仕様確認のために誰かが画面共有して資料を探す → 流れが止まる」「あれをやっておいて、で半年後にすれ違いが顕在化する」を, Copilot は会議後に要約してくれるだけ。会議中に介入してほしい。
**入れたもの**: Teams 会議に常駐する Bot (MOCHI-kiki) — 仕様補完 (C-02) と曖昧発言の対話的明確化 (C-03)
**スコープ**:
- 扱う: アーキテクチャ選定の意思決定 / Recall.ai WebSocket 経由の音声取得 / Semantic Kernel プラグイン構成 / Azure AI Search ハイブリッド検索 / Container Apps + Terraform / 実装中に踏んだ落とし穴 3 件
- 扱わない: Bot Framework Manifest の細部, Entra ID On-Behalf-Of の詳細, デモ動画スクリプト

## H2 skeleton (7 本)

1. **はじめに** — Microsoft Agent Hackathon 2026 に参加する。Copilot Recap の隙間「会議中に介入する Agentic AI」を 2 週間で MVP にする宣言。MOCHI-kiki という名前の由来とコア機能 3 つを最初に提示。
2. **なぜ Copilot Studio ではなく Azure + Semantic Kernel を選んだか** — アプローチ A (Copilot Studio) と B (Azure + SK) を比較して、Agentic AI らしさで B を採用した意思決定の話。Claude を開発支援に置くことで B の最大弱点「2 週間で完成しにくい」を埋める設計。
3. **アーキテクチャ全体像** — Teams → Recall.ai → aiohttp WS handler → Semantic Kernel orchestrator → (Intent / RAG / Answer / Poster) → Bot Framework → Teams chat。Cosmos と AI Search の役割分担、Container Apps + Terraform。Mermaid 1 枚。
4. **C-02 仕様補完パイプライン** — IntentAnalysisPlugin → RAGSearchPlugin (ハイブリッド検索) → AnswerGenerationPlugin → ChatPosterPlugin の流れと、各プラグインの責務分割設計。実コードを 2 ブロック貼る。
5. **C-03 曖昧発言の対話的明確化** — AmbiguityDetectorPlugin で検知 → 発言者に 1:1 で問い返し → 返信を ClarificationSummaryPlugin で整理して会議チャットに投稿、というセッション機構。`pending_sessions` + 60 秒タイムアウトの設計。Copilot にない差別化点。
6. **実装中に踏んだ落とし穴 3 つ** — (a) Recall.ai 日本語は `prioritize_low_latency` 不可 (英語専用) → `prioritize_accuracy` に強制、(b) WS realtime の `transcript.data` は webhook 形式と違い `is_final` を含まない、(c) Cosmos manual 400 RU 固定だとアイドル時もコストが乗るので autoscale に切り替え 5 コンテナで月 ~$73 削減。それぞれ実コミットメッセージから根拠。
7. **まとめと提出物** — MVP 範囲 (C-01/C-02/C-03 + F-01/F-06)、提出する Microsoft 技術一覧、GitHub URL、ハッカソン審査基準への対応マッピング。今後の展望 (F-02 認識齟齬検知)。

## Zenn 構造 essentials マッピング

| Essential | 配置 |
|---|---|
| 1. `## はじめに` で開く | H2-1 |
| 2. 冒頭フック (痛み + 入れたもの + スコープ) | H2-1 内 |
| 3. 対象読者ボックス `:::message` | H2-1 末尾 |
| 4. 全体像の早期提示 | H2-1 でコア機能 3 つを箇条書き + H2-3 で Mermaid |
| 5. まとめ表 | H2-7 (審査基準対応マッピング表) |

## platform

- canonical: Zenn (`zenn.dev/ruuuhs/articles/mochi-kiki-teams-agent`) ※ slug は publish 時に最終化
- type: `tech`
- emoji: 🎙️
- topics: `["azure", "semantickernel", "teams", "botframework", "生成ai"]` (5 個, 各 ≤16 字, 全 Zenn 既存トピック)
- ハッカソン提出時は別途エントリーフォームに記事 URL を貼る運用 (専用 topic タグ `msagenthackathon2026` は 2026-05-31 時点で Zenn 上に未作成のため明記しない)
- published: false (Stage 9 後に true)

## target length

- 目安: 4500〜6000 字 (実装解説 + 意思決定の理由を含むため通常より長め)
- 図表数: Mermaid 1 枚 (H2-3 アーキテクチャ図)
- スクショ: 任意 (Phase 後半で追加検討、最低 0 枚で公開可能)
- コード例: 4 ブロック (intent_analysis 抜粋 / rag_search 抜粋 / orchestrator `_handle_ambiguous` 抜粋 / Terraform autoscale block)

## sources (seed)

- <https://zenn.dev/hackathons/microsoft-agent-hackathon-2026> — Microsoft Agent Hackathon 2026 公式ページ (アクセス 2026-05-31、テーマ「業務改革につながるAgentic AIを作ろう」「2026-04-07〜06-18」「賞金120万円」)
- <https://learn.microsoft.com/semantic-kernel/overview/> — Semantic Kernel 公式 overview (アクセス 2026-05-31、プラグイン / Function Calling / Planner の概念ソース)
- <https://docs.recall.ai/docs/real-time-websocket-endpoint> — Recall.ai Real-time WebSocket Endpoint 仕様 (アクセス 2026-05-31、`audio_mixed_raw.data` / `transcript.data` event スキーマ)
- <https://learn.microsoft.com/azure/search/hybrid-search-overview> — Azure AI Search ハイブリッド検索 (ベクトル + キーワード) 公式 (アクセス 2026-05-31)
- <https://learn.microsoft.com/azure/cosmos-db/provision-throughput-autoscale> — Cosmos DB autoscale provisioned throughput 公式 (アクセス 2026-05-31、コスト最適化の根拠)
- <https://learn.microsoft.com/azure/container-apps/overview> — Azure Container Apps 公式 (アクセス 2026-05-31)

## 提出物チェックリスト (記事内に明記する)

- [ ] 成果物 URL: Container App ingress FQDN (デモ用、認証付き)
- [ ] GitHub URL: https://github.com/mochitec/MOCHI-kiki (公開タグ運用)
- [ ] デモ動画 URL: Loom or YouTube (Stage 9 時点で挿入)
- [ ] 利用 Microsoft 技術一覧: Azure Container Apps / Azure OpenAI / Azure AI Speech / Azure AI Search / Azure Cosmos DB / Azure Key Vault / Microsoft Graph (Teams 投稿) / Entra ID / Semantic Kernel
- [ ] ルール必須要件 ① Azure 実行基盤: Azure Container Apps を採用
- [ ] ルール必須要件 ② Microsoft AI: Azure OpenAI (GPT-4o) + Semantic Kernel + Azure AI Search + Azure AI Speech

## 過去履歴

- 初版 (2026-05-31): 本企画。MOCHI-kiki MVP 実装直後の段階で執筆。

## 注意事項

- Claude の話は「開発支援アシスタント」(GitHub Copilot 相当の位置づけ) として軽く触れる程度。エージェント本体に組み込んでいないことを明示し、ハッカソンルール「Microsoft AI 必須」を満たすのは Azure OpenAI である点を強調する。
- 「Copilot Recap で既に出来ること」と「本作品が会議中にやること」の対比は必ず入れる (差別化軸の核)。
- 性能数値や金額の主張は実コミット (`0f9e321 chore(infra): switch all Cosmos containers to autoscale (idle cost ~$73/mo down)`) など、リポジトリ内で検証可能な根拠のみ。推測の数値は書かない。
