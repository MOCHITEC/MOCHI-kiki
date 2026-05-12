# Teams 会議サポートエージェント 要件定義書

**Microsoft Agent Hackathon powered by Tokyo Electron Device 応募作品**

| 項目 | 内容 |
|------|------|
| 作成日 | 2026-05-12 |
| 作成者 | Hendra Guntur |
| 提出締切 | 2026-05-24（審査期間：2026-05-25 〜 2026-06-18） |
| 開発体制 | 個人開発 |
| 開発期間 | 約 2 週間 |

---

## 1. プロジェクト概要

### 1.1 背景・課題
Teams 会議では、以下のような「すれ違い」「会議後の確認作業」が頻発する。

- 仕様や用語の認識が人によって異なり、議論が空転する。
- 発言者が「うまく言語化できない」「専門用語を曖昧に使っている」ため、聞き手が解釈に困る。
- 仕様確認のために誰かが画面共有して資料を探す → 会議の流れが止まる。
- 会議後に「議事録を書く」「アクションアイテムを抽出する」作業が属人化している。

### 1.2 ソリューション（コアコンセプト）
**「会議の議論を常に聞き、不明点を即座に補完し、曖昧な発言を明確化する AI エージェント」** を Teams 会議に常駐させる。

会議中に必要な情報（仕様書、ソースコード、過去議事録）を能動的に検索・提示し、会議の生産性を最大化する。

### 1.3 ユーザーが提示したコア機能（再掲）
1. **会議内容の常時リスニング**：エージェントが会議の音声をリアルタイムで聞いている。
2. **仕様補完**：会話の中で仕様が不明な時に、ドキュメントから検索し会議のチャットに流す。
3. **発言の明確化**：曖昧な発言に対して、発言者に確認 → ドキュメント/ソースコードを調査 → 整理した文章をチャットに流す。

### 1.4 開発前提：Claude を「開発支援アシスタント」として利用

**前提の定義**：
本プロジェクトにおいて、**Claude（Anthropic）は開発時の支援アシスタントとしてのみ利用**する。エージェント本体に組み込む LLM は **Azure OpenAI（Azure AI Foundry 経由）を利用する**。

| 区分 | 利用するモデル | 用途 |
|------|----------------|------|
| 🛠 開発支援（オフライン） | **Claude** | Python コーディング、デバッグ、Semantic Kernel プラグイン設計、アーキテクチャ検討、Zenn 記事下書き、デモシナリオ作成、Terraform / Dockerfile 生成 など |
| 🚀 エージェント本体（ランタイム） | **Azure OpenAI（GPT-4o 系）** | 会議リスニング・意図解析・回答生成・曖昧発言検知・認識齟齬検知など、すべてのランタイム推論 |

**ハッカソンルールへの適合性**：
エージェント本体が Azure OpenAI（Microsoft Foundry に含まれる）を使うため、ルールが定める「Microsoft AI 技術 1 つ以上」の必須要件を満たす。Claude は成果物に含まれず、あくまで開発者の生産性向上ツールとして使用する（GitHub Copilot と同じ立ち位置）。提出時の申告は不要。

**意思決定への影響**：
Claude を開発アシスタントとして使えることが、**アプローチ B（Azure + Semantic Kernel 中心）採用を後押しする決定的要因**となる。

| 観点 | Claude なし | Claude あり（本前提） |
|------|-------------|----------------------|
| Semantic Kernel のコード実装速度 | 遅い（学習しながら書く） | 速い（Claude が雛形・サンプル・修正案を即提示） |
| Bot Framework / Teams Manifest 設定 | ハマりやすい | Claude にエラーログを貼って解決可能 |
| Terraform | 書ける人少ない | Claude がテンプレ自動生成 |
| デバッグ | 個人開発で詰みやすい | Claude にスタックトレースを渡して原因特定 |
| Zenn 記事執筆 | 時間がかかる | Claude が下書きを作り、人間が監修する形で時短 |

→ アプローチ B の最大の弱点「2 週間で完成しにくい」が、Claude のコーディング支援によって緩和される。よって**アプローチ B（Azure + Semantic Kernel + Azure OpenAI）を採用する**。

---

## 2. 追加機能の提案（タスク ①）

ユーザーが挙げた 3 機能に加え、ハッカソンの「ビジネスインパクト」「アプローチの有効性」を高めるために機能を提案する。

### 2.0 Microsoft 365 Copilot との重複機能の整理（重要）

Microsoft 365 Copilot は既に Teams 会議で以下の機能を提供しているため、これらは **本プロジェクトのスコープから除外する**。提出時の審査でも「Copilot で既にできることを再実装している」と評価されると不利になる。

| Copilot 既存機能 | 本プロジェクトでの扱い |
|------------------|---------------------|
| Intelligent Meeting Recap（議事録・要約） | ❌ 削除（Copilot 標準） |
| Action Item Suggestions（アクション提案） | ❌ 削除（Copilot 標準） |
| Decision Tracking（決定事項記録） | ❌ 削除（Copilot 標準） |
| Audio Recap（音声要約） | ❌ 削除（Copilot 標準） |
| Catch-up（途中参加者向け要約） | ❌ 削除（Copilot 標準） |
| Interpreter Agent（リアルタイム通訳） | ❌ 削除（Copilot 標準、10 言語対応済） |
| Multilingual Speech Recognition | ❌ 削除（Teams 標準機能） |
| Post-Meeting Summary Email | △ 完全削除はせず、Copilot にない独自情報（RAG ヒット履歴等）を含む形に限定 |
| 発言者ごとの発言量集計 | ❌ 削除（Copilot Recap 内に類似） |

**本プロジェクトの差別化軸**：
Copilot は **会議後（post-meeting）に要約する** ことが主眼。本プロジェクトは **会議中（in-meeting）にリアルタイムで能動介入する** ことに価値を置く。
- 会議中に **社内ドキュメントを RAG 検索して即座に投稿**（Copilot は Microsoft Graph 範囲の検索）
- **曖昧発言に対する問い返し → 発話者本人に確認 → 結論を投稿** という対話型の Agentic 振る舞い（Copilot は要約に留まる）
- **認識齟齬の検知**（Copilot にない独自機能）
- **コード片解析**（GitHub リポジトリ参照、Copilot にない）

### 2.1 採用する機能（Copilot 重複削除後）

#### 2.1.1 コア機能（ユーザー提示）

| # | 機能 | 内容 | 優先度 |
|---|------|------|--------|
| C-01 | 会議内容の常時リスニング | Bot が会議に参加し、音声/文字起こしストリームを継続受信 | ★★★ |
| C-02 | 仕様補完（リアルタイム RAG 投稿） | 仕様不明発言を検知 → Azure AI Search でドキュメント横断検索 → チャットに投稿 | ★★★ |
| C-03 | 曖昧発言の対話的明確化 | 曖昧発言を検知 → 発言者にプライベート確認 → 整理した文章をチャットに投稿 | ★★★ |

#### 2.1.2 差別化機能（Copilot との差別化軸を強化）

| # | 機能 | 内容 | 優先度 |
|---|------|------|--------|
| F-01 | 専門用語・略語の即時 RAG 解説 | 社内用語・略語が出たら、社内用語集ドキュメントから定義をチャットに投稿（Copilot はテナント内ファイルを横断検索しない場合がある） | ★★★ |
| F-02 | 認識齟齬の検知 | A さんと B さんが同じ単語を違う意味で使っている可能性を検出し、確認を促す | ★★★ |
| F-03 | 過去会議との横断検索 | 「前回の打合せでどう決まった？」に答えるため、過去会議メタデータ（Cosmos DB）+ ベクトル検索（Azure AI Search）で検索 | ★★ |
| F-04 | コード片の自動解析 | GitHub リポジトリ内のコードを参照し、「あの関数の引数は？」に答える | ★★ |
| F-05 | 沈黙・脱線検知 | 一定時間沈黙が続いた／本題から離れた話題が続いた場合に、議題を促す | ★ |

#### 2.1.3 運用・セキュリティ系（実務導入で必須）

| # | 機能 | 内容 | 優先度 |
|---|------|------|--------|
| F-06 | エージェント参加のオプトイン制御 | 会議開始時に「エージェント参加に同意」を取る | ★★★ |
| F-07 | 機密情報のマスキング | 個人情報・パスワード等が発話されたら投稿前に自動除外 | ★★ |
| F-08 | アクセス権ベースの情報フィルタ | RAG で参照するドキュメントは発言者の権限内に限る（Entra ID 連携） | ★★ |

### 2.2 2 週間で実装するなら選ぶべき機能セット（推奨 MVP）

個人開発・短期間という制約下では、**C-01 + C-02 + C-03 + F-01 + F-06** を MVP として推奨する。
- コア 3 機能（C-01/C-02/C-03）が「審査基準＝Agentic AI らしさ」のキモになるので絶対実装。
- F-01（用語解説）は C-02 とほぼ同じ RAG パイプラインで実装でき低コスト。
- F-06（オプトイン）は実務導入アピールで「完成度・実現性」評価に効く。

Day 8 以降の余裕で F-02（認識齟齬）→ F-03（過去会議横断）→ F-08（権限フィルタ）の順で積み増す。

---

## 3. 要件定義（タスク ②）

### 3.1 機能要件（全体・Copilot 重複削除後）

| ID | 機能名 | 入力 | 処理 | 出力 | 対応機能 |
|----|--------|------|------|------|---------|
| FR-01 | 音声リアルタイム文字起こし | Teams 会議音声 | Azure AI Speech（日本語 STT） | テキストストリーム | C-01 |
| FR-02 | 発話意図解析 | 文字起こし結果 | Semantic Kernel プラグイン経由で Azure OpenAI が意図分類（仕様確認 / 曖昧 / 通常会話） | 意図ラベル付きテキスト | C-02/C-03 |
| FR-03 | RAG 検索 | 不明用語・仕様キーワード | Azure AI Search（ハイブリッド検索：ベクトル + キーワード）から類似ドキュメント取得 | 関連ドキュメント片 | C-02/F-01/F-03 |
| FR-04 | 回答生成 | RAG 結果 + 発話文脈 | Azure OpenAI（GPT-4o）が会議向け要約を生成 | 200 文字以内の回答文 | C-02/F-01 |
| FR-05 | 曖昧発言の対話的問い返し | 曖昧発言検知 | 発言者宛にプライベートチャット（or メンション）で確認 → 回答を受信 → 整理して投稿 | 確認 → 確定文章 | C-03 |
| FR-06 | チャット投稿 | 生成済み回答 | Bot Framework SDK で会議チャットへ投稿 | チャットメッセージ | 全機能共通 |
| FR-07 | 認識齟齬検知 | 直近 N 発話 | LLM が「同一単語で異なる意味」のパターンを検出 | 確認プロンプト | F-02 |
| FR-08 | オプトイン制御 | 会議開始イベント | 同意取得 UI を表示 → 同意者リストを Cosmos DB に保存 | 同意状態 | F-06 |
| FR-09 | 機密マスキング | 投稿予定の文章 | 正規表現 + LLM で PII / シークレットを検出して除外 | マスキング済テキスト | F-07 |
| FR-10 | アクセス権フィルタ | 発言者 ID + 検索結果 | Entra ID から発言者の権限を確認 → 結果を絞り込み | 権限内ドキュメントのみ | F-08 |

> ※ 議事録生成 / アクション抽出 / サマリーメール等は Microsoft 365 Copilot と機能が重複するため本プロジェクトのスコープ外とする。

### 3.2 非機能要件

| 区分 | 要件 |
|------|------|
| 性能 | 文字起こしから回答投稿まで 10 秒以内（会議の流れを止めない） |
| 可用性 | デモ用途、SLA は問わない（審査期間は連続稼働必須） |
| セキュリティ | Entra ID 認証、参照ドキュメントは閲覧権限内に限定 |
| プライバシー | 会議冒頭で参加者の同意を得る、文字起こし・発話ログの保管期間を明示 |
| 拡張性 | ドキュメントソース（SharePoint / GitHub / Notion 等）を追加可能 |
| 監査性 | エージェント発言ログを残し、誰の質問に何を答えたか追跡可能 |
| 開発容易性 | 2 週間で MVP 完成、デプロイ手順がドキュメント化されていること |

### 3.3 システム構成（採用構成）

```
[Teams 会議]
   ├─ 音声 ─→ [Azure AI Speech (STT)] ─→ 文字起こしストリーム
   │                                          │
   │                                          ▼
   │                         [Semantic Kernel オーケストレーター]
   │                                          │
   │              ┌───────────────────────┼───────────────────────┐
   │              ▼                       ▼                       ▼
   │     [意図解析プラグイン]       [仕様補完プラグイン]    [曖昧明確化プラグイン]
   │              │                       │                       │
   │              ▼                       ▼                       ▼
   │                            [RAG 検索プラグイン]    [発言者へ問い返し]
   │                                      │                       │
   │                                      ▼                       │
   │                       ┌── Azure AI Search ──┐                │
   │                       │  （ベクトル +       │                │
   │                       │   キーワードのハイブリッド）         │
   │                       └─────────┬───────────┘                │
   │                                ▼                              │
   │                          [Azure OpenAI]                       │
   │                          （GPT-4o 系）                        │
   │                                │                              │
   │                                ▼                              │
   └──────────────[Bot Framework SDK → Teams チャット投稿] ◀──────┘

       ┌─ Azure Cosmos DB（NoSQL API） ────────────────┐
       │   ├─ meetings           … 会議メタデータ      │
       │   ├─ participants       … 参加者情報          │
       │   ├─ utterances         … 文字起こしログ      │
       │   ├─ consents           … オプトイン状態      │
       │   └─ agent_logs         … エージェント発言証跡 │
       └────────────────────────────────────────────────┘
       ↑ Semantic Kernel プラグイン群から azure-cosmos SDK 経由でアクセス

【ランタイム実行基盤】
  Docker コンテナ → Azure Container Apps（Container Registry 経由）

【インフラ構築】
  Terraform → Azure リソース（Container Apps / OpenAI / Speech / AI Search / Cosmos DB / Key Vault / Entra ID 等）

【開発フェーズのみ】
  Claude（Cowork / Claude Code） … コード生成・デバッグ・記事執筆を支援。ランタイム非関与。
```

---

### 3.4 アプローチ A：Copilot Studio 中心（ローコード）

**構成**
- フロント：Copilot Studio で構築したエージェントを Teams にデプロイ。
- 文字起こし：Teams 標準の Live Transcription を活用、または Power Automate 経由で取得。
- 知識ベース：Copilot Studio の「ナレッジ」機能（SharePoint / Web / ファイル）。
- アクション：Power Automate フロー経由で Planner / メール送信。
- LLM：Copilot Studio 内蔵の Azure OpenAI。

**メリット**
- 開発が圧倒的に速い。ノーコード／ローコードで GUI で組める。
- Teams へのデプロイが標準機能で完結（独自ボット登録の手間が少ない）。
- 認証・権限が Entra ID と自動連携。
- 「ビジネスインパクト＝導入容易性」を審査でアピールしやすい。
- インフラ運用が不要（マネージド）。

**デメリット**
- 細かいエージェント挙動（割り込み、能動的発言、会話の流れに応じた動的判断）の制御が難しい。
- リアルタイム音声ストリーミング処理を Copilot Studio 単体で組むのは限定的。
- 「沈黙検知」「発言バランス可視化」など、能動的な機能の実装に制約。
- カスタムロジックを書きたい場合、結局 Azure Functions などを呼ぶ必要が出る。
- 審査基準の「アプローチの有効性（Agentic AI らしさ）」で差別化しにくい。

**2 週間での想定スコープ**
- F-01（用語解説）/ F-03（過去会議横断検索）程度は実装可能。
- F-02（認識齟齬検知）/ F-05（沈黙検知）は厳しい。
- C-03（曖昧発言の対話的明確化）も能動的振る舞いが難しく、不採用要因の 1 つ。

---

### 3.5 アプローチ B：Azure + Semantic Kernel 中心（コード中心）【採用】

**構成（採用）**
- 言語：**Python 3.11+**（Semantic Kernel Python SDK を使用）
- フロント：**Bot Framework SDK（Python）** で Teams Bot を作成
- 音声：**Azure AI Speech**（リアルタイム文字起こし、`azure-cognitiveservices-speech`）
- オーケストレーション：**Semantic Kernel**（プラグイン / Function Calling / Planner）
- 知識ベース（RAG）：**Azure AI Search**（ハイブリッド検索：ベクトル + キーワード、`azure-search-documents` SDK）
- LLM：**Azure OpenAI（GPT-4o 系）** を Azure AI Foundry でデプロイ
- DB：**Azure Cosmos DB（NoSQL API）** で会議メタデータ・文字起こしログ・エージェント発言証跡を保管（`azure-cosmos` SDK）
- コンテナ：**Docker**（マルチステージビルドで軽量化）
- 実行基盤：**Azure Container Apps**（コンテナイメージは Azure Container Registry に push）
- IaC：**Terraform**（Azure リソース全てを HCL で定義）
- CI/CD：**GitHub Actions**（Docker build → ACR push → Container Apps デプロイ）

**メリット**
- エージェントの振る舞いを完全制御可能（能動発言、文脈判断、複数ツール協調）。
- 「Agentic AI らしさ」で審査基準にアピールしやすい。
- Semantic Kernel の Planner / Function Calling で「曖昧発言を検知 → 確認 → 検索 → 投稿」のような複合フローが組める。
- 後から機能拡張・カスタマイズしやすい。

**デメリット**
- 2 週間で MVP まで持っていくのが厳しい（Teams Bot 登録、Manifest、認証、デプロイなど工程が多い）。
- インフラ運用知識が必要（Container Apps / Cosmos DB / AI Search / Key Vault の設定、シークレット管理）。
- Teams のリアルタイム音声を取るには Call Records API / Media Bot などハードルが高い → 現実的には「Teams Live Transcription を購読」する妥協が必要。
- バグ修正に時間がかかると締切リスク大。

**2 週間での想定スコープ（Claude 開発支援前提）**
- コア機能（C-01 + C-02 + C-03）+ F-01 + F-06 を MVP として実装可能。
- Day 8 以降の余裕で F-02 / F-03 / F-08 を積み増す。

---

### 3.6 比較サマリーと推奨判断

| 観点 | A: Copilot Studio | B: Azure + Semantic Kernel（Claude 開発支援あり） |
|------|--------------------|--------------------------------------------------|
| 開発速度（2週間で完成可能か） | ◎ 非常に速い | ○ Claude 支援で現実的に到達可能 |
| Agentic AI らしさ（審査基準） | △ 制約あり | ◎ 自由度高い |
| Teams 連携の容易さ | ◎ 標準機能 | △ Bot 登録など必要（Claude にコード生成させて短縮） |
| カスタマイズ性 | △ | ◎ |
| 運用コスト | ◎ マネージド | ○ 自前運用 |
| デモのインパクト | ○ 「触れる」感が出しやすい | ◎ 高度な機能で差別化可能 |
| 個人開発との相性 | ◎ | ○ Claude が「もう一人の開発者」として機能 |
| 学習コスト | 低 | 中〜高（Claude が学習を肩代わり） |
| Claude 開発支援との相性 | △ ローコード GUI 操作中心で Claude の出番が少ない | ◎ 全工程で Claude を活用可能 |

**🎯 最終推奨：アプローチ B（Azure + Semantic Kernel 中心、エージェント LLM は Azure OpenAI）**

**推奨理由**
- Claude を開発支援アシスタントとして利用できるため、アプローチ B の最大の弱点「2 週間で完成しにくい」が克服可能。
- 審査基準「アプローチの有効性（Agentic AI らしさ）」をストレートに満たせる。Semantic Kernel の Function Calling / Planner でエージェント的振る舞いを設計可能。
- カスタマイズ性が高く、「曖昧発言の検知 → 確認 → 検索 → 投稿」の能動的フローを自由に構築できる。
- Copilot Studio のテナント / ライセンス権限に依存しない（個人開発で詰みにくい）。
- ハッカソンのルール「Azure 実行基盤 + Microsoft AI 1 つ以上」を Azure Container Apps + Azure OpenAI で確実に満たす。
- 推奨技術として「Entra ID」「GitHub Copilot」も自然に組み込めるため、申告でプラス評価が狙える。

**アプローチ B 構成図（採用）**
```
[Teams 会議]
    │
    ▼
[Teams Bot（Bot Framework SDK Python）]
    │
    ▼
[Docker Container]
    │  └─ Python 3.11 + Semantic Kernel + Bot Framework SDK
    │
    ▼
[Azure Container Apps] ← デプロイ先（ハッカソン必須要件①）
    │  ※ イメージは Azure Container Registry (ACR) に push
    │
    ▼
[Semantic Kernel オーケストレーター]
    ├─ プラグイン①：意図解析（仕様確認 / 曖昧 / 通常）
    ├─ プラグイン②：RAG 検索（用語・仕様）
    ├─ プラグイン③：曖昧発言検知 → 発言者へ問い返し
    ├─ プラグイン④：認識齟齬検知
    ├─ プラグイン⑤：機密マスキング
    └─ プラグイン⑥：チャット投稿（Bot Framework 経由）
            │
            ├─→ [Azure OpenAI（GPT-4o）] ← 必須要件②: Microsoft AI
            ├─→ [Azure AI Speech]        ← リアルタイム文字起こし
            ├─→ [Azure AI Search]        ← RAG ハイブリッド検索（ベクトル + キーワード）
            └─→ [Azure Cosmos DB]        ← 会議メタデータ / 文字起こし / エージェント発言ログ

[Microsoft Graph API]        ← Teams 投稿（補助的）
[Entra ID 認証]              ← アクセス権フィルタ
[Azure Key Vault]            ← シークレット保管

【インフラ構築】
  Terraform（HCL）→ Azure サブスクリプション
    ├─ azurerm_container_app
    ├─ azurerm_container_registry
    ├─ azurerm_cognitive_account（OpenAI / Speech）
    ├─ azurerm_search_service（Azure AI Search）
    ├─ azurerm_cosmosdb_account / azurerm_cosmosdb_sql_database
    ├─ azurerm_key_vault
    └─ azurerm_log_analytics_workspace（Application Insights 用）

【CI/CD】
  GitHub Actions
    ├─ docker build & push to ACR
    ├─ terraform plan / apply
    └─ az containerapp update

【開発フェーズのみ】
[開発者]
    └─→ [Claude（Cowork / Claude Code）] ← 開発支援（Python コード生成・デバッグ・記事執筆）
              ↑
              ※ ランタイムには関与しない。成果物に含まれない。
```

---

## 4. 必要技術スキル（タスク ③）

### 4.1 ハッカソン必須要件から導出される技術

ルールから抽出した「必ず使う必要があるもの」：

| 必須カテゴリ | 候補 | 推奨選択（本プロジェクト） |
|------|------|--------------------------|
| Azure 実行基盤（1 つ以上） | App Service / VM / AKS / **Container Apps** / Functions / GPU VM | **Azure Container Apps**（Docker イメージを ACR から pull、Bot のホスト先として柔軟） |
| Microsoft AI 技術（1 つ以上） | Foundry / Copilot Studio / **Semantic Kernel** / **Azure OpenAI** / **AI Speech** / **AI Search** / AI Vision / AI Language / AI Translator / Fabric | **Azure OpenAI + Semantic Kernel + AI Speech + AI Search** |
| 推奨技術（申告でプラス評価） | **Cosmos DB** / GitHub Copilot / Power Platform / Entra ID | **Cosmos DB、Entra ID、GitHub Copilot** |

> ⚠️ **Claude について**：Claude は開発時の支援アシスタント（コード生成・デバッグ・記事執筆）として利用するが、エージェントのランタイムには組み込まない。提出物には含まれないため、ハッカソンの必須要件・推奨技術の対象外。GitHub Copilot と同じ位置づけ。

### 4.2 必要となる技術スキル一覧

#### 共通（どちらのアプローチでも必須）

| カテゴリ | スキル | レベル目安 |
|----------|--------|-----------|
| 基礎 | Azure ポータル操作、リソースグループ管理 | 初級 |
| 基礎 | Entra ID（旧 Azure AD）でのアプリ登録、認証フロー | 中級 |
| 基礎 | Microsoft 365 テナント管理者権限の取り扱い | 初級 |
| 基礎 | Git / GitHub（リポジトリ公開、タグ運用） | 初級 |
| AI | プロンプトエンジニアリング（System / Few-shot） | 中級 |
| AI | RAG（Retrieval-Augmented Generation）の概念 | 中級 |
| Teams | Teams アプリの仕組み、マニフェスト、配布方法 | 初級 |
| 文書化 | Zenn 記事執筆、アーキテクチャ図作成（draw.io / Excalidraw / Mermaid） | 初級 |

#### アプローチ A（Copilot Studio 中心）

| カテゴリ | スキル | 学習コスト |
|----------|--------|-----------|
| Copilot Studio | エージェント作成、トピック設計、ナレッジ追加 | 低（GUI 操作中心） |
| Copilot Studio | カスタムアクション、コネクタ呼び出し | 中 |
| Power Automate | フロー設計、Teams / Outlook / Planner コネクタ | 低〜中 |
| SharePoint | ドキュメントライブラリ管理、権限設定 | 低 |
| Teams 管理 | Teams への Copilot Studio エージェント発行 | 低 |

#### アプローチ B（採用：Python + Docker + Terraform + Cosmos DB + Azure AI Search）

| カテゴリ | スキル | 学習コスト |
|----------|--------|-----------|
| 言語 | **Python 3.11+**（型ヒント、async/await） | 中 |
| パッケージ管理 | **uv** または **poetry**、`pyproject.toml` での依存管理 | 低〜中 |
| Semantic Kernel | `semantic-kernel` Python SDK、プラグイン作成、Function Calling、Planner | 中〜高 |
| Azure OpenAI | Azure AI Foundry でモデルデプロイ、`openai` SDK の Azure 構成 | 中 |
| Azure AI Speech | `azure-cognitiveservices-speech` SDK、リアルタイム文字起こし | 中 |
| Bot Framework | `botbuilder-core` / `botbuilder-integration-aiohttp`、Teams Manifest 設定 | 中〜高 |
| **Docker** | Dockerfile 作成（マルチステージ）、ローカルでのコンテナ起動・デバッグ | 中 |
| **Azure Container Apps** | ACR 連携、環境変数 / シークレット注入、リビジョン管理、スケール | 中 |
| **Azure AI Search** | インデックス設計、ベクトルフィールド + キーワードのハイブリッド検索、`azure-search-documents` SDK | 中 |
| **Azure Cosmos DB**（NoSQL API） | コンテナ設計、パーティションキー設計、`azure-cosmos` SDK での CRUD | 中 |
| **Terraform** | `terraform` CLI、`azurerm` プロバイダ、ステートファイル管理（リモート state は Azure Storage） | 中 |
| GitHub Actions | docker build/push、terraform apply、Container Apps への deploy | 中 |
| Entra ID | アプリ登録、シークレット管理、On-Behalf-Of フロー | 中 |
| Microsoft Graph API | `msgraph-sdk`、Teams 投稿スコープ | 中 |
| Azure Key Vault | シークレット保管、Managed Identity 経由のアクセス | 中 |
| Application Insights | `opentelemetry` でログ・トレース送信 | 低 |

#### 採用構成で必須となるスキル一覧（優先度付き）

| 優先度 | スキル | 学習方針（Claude 支援前提） |
|--------|--------|-----------------------------|
| 🔴 必須 | **Python 3.11+**（async/await、型ヒント） | 既知の場合は不要、Claude にひな型生成依頼 |
| 🔴 必須 | **Semantic Kernel Python**（プラグイン / Function Calling） | 公式サンプル + Claude でカスタム実装 |
| 🔴 必須 | **Azure OpenAI**（Foundry でモデルデプロイ） | Foundry ポータルで GPT-4o をデプロイ |
| 🔴 必須 | **Bot Framework SDK (Python)** + Teams Toolkit | Manifest 設定で詰まりやすい → Claude にエラー貼って解決 |
| 🔴 必須 | **Docker**（Dockerfile、マルチステージビルド） | Claude に最適化済みテンプレを生成依頼 |
| 🔴 必須 | **Azure Container Apps** + ACR | デプロイは GitHub Actions で自動化 |
| 🔴 必須 | **Azure AI Speech**（Speech SDK） | リアルタイム文字起こしのストリーミング処理 |
| 🔴 必須 | **Azure AI Search**（ベクトル + キーワードのハイブリッド検索） | RAG のキモ。Day 6 でインデックス + 文書投入を完了 |
| 🔴 必須 | **Azure Cosmos DB**（NoSQL API） | 会議メタデータ / 文字起こし / エージェント発言ログを保管 |
| 🔴 必須 | **Terraform**（azurerm プロバイダ） | 全インフラを HCL で記述。state は Azure Storage に保存 |
| 🟡 強推奨 | **GitHub Actions**（CI/CD） | docker build → ACR push → Container Apps deploy を自動化 |
| 🟡 強推奨 | **Entra ID**（アプリ登録、On-Behalf-Of フロー） | 個人開発で最も詰まりやすいので最初に通す |
| 🟡 強推奨 | **Azure Key Vault** + Managed Identity | シークレットを Container Apps から安全に参照 |
| 🟢 推奨 | **Microsoft Graph API**（Teams 投稿） | `msgraph-sdk` |
| 🟢 推奨 | **Application Insights / OpenTelemetry** | デモ中の挙動証跡として有用 |

#### 開発支援としての Claude 活用スキル

Claude を効果的に使うために身につけておくと良いスキル：

| スキル | 内容 |
|--------|------|
| プロンプト設計 | エラーログを添えて聞く、コード全体の文脈を渡す、設計意図を先に伝える |
| 段階分割 | 「まず Speech 取得だけ」「次に Bot 投稿だけ」と細かく区切って Claude に頼む |
| 検証習慣 | Claude が出したコードを必ず手元で動かし、ハルシネーション（実在しない API 等）を排除 |
| Cowork / Claude Code 活用 | ファイル読み書き・bash 実行を任せ、開発者は設計判断に集中 |

### 4.3 提出物の作成スキル

ルールで定められた提出物に対応するスキル：

| 提出物 | 必要スキル |
|--------|-----------|
| 成果物 URL | デプロイ運用、認証付きでも審査員が試せる準備 |
| Zenn 記事 | テクニカルライティング、Mermaid 図、デモ動画作成（Loom / Camtasia など） |
| デモ動画 | 画面録画、編集、ナレーション |
| GitHub リポジトリ（任意） | README 整備、タグ運用、ライセンス設定 |

---

## 5. 2 週間スケジュール案（採用：アプローチ B + Claude 開発支援）

| 週 | 日数 | タスク | Claude 活用ポイント |
|----|------|--------|---------------------|
| Week 1 | Day 1 | リポジトリ初期化、Python プロジェクト構成（`pyproject.toml`）、Dockerfile 雛形作成 | プロジェクトひな型を Claude に生成依頼 |
| Week 1 | Day 2 | **Terraform** で Azure リソースをプロビジョニング（Container Apps / ACR / OpenAI / Speech / AI Search / Cosmos DB / Key Vault） | Claude に `main.tf` を書かせる |
| Week 1 | Day 3 | Bot Framework アプリ登録、Teams Toolkit でマニフェスト生成、ローカル Docker で「Hello World」Bot を起動 | Manifest トラブルを Claude で解決 |
| Week 1 | Day 4 | Docker イメージを ACR へ push、Container Apps にデプロイし Teams から疎通確認、GitHub Actions で自動化 | YAML を Claude に生成 |
| Week 1 | Day 5 | Azure AI Speech をBotに統合し、リアルタイム文字起こしストリームを取得（C-01）、Cosmos DB に発話ログを保存 | Speech SDK と Cosmos SDK の Python サンプルを Claude にカスタマイズ |
| Week 1 | Day 6 | Azure AI Search のインデックス設計（ベクトル + キーワード）、サンプル仕様書を埋め込み生成して投入 | インデックススキーマを Claude に設計させる |
| Week 1 | Day 7 | Semantic Kernel 接続、意図解析プラグイン + RAG 検索（AI Search） + チャット投稿が一連で動く（**MVP = C-01 + C-02 完成**） | プロンプト設計を Claude と壁打ち |
| Week 2 | Day 8 | C-03「曖昧発言の対話的明確化」プラグインを実装、Agentic AI らしさのデモポイントを作る | エージェント設計を Claude に相談 |
| Week 2 | Day 9 | F-01「専門用語・略語の即時 RAG 解説」+ F-06「オプトイン制御」 | UI フロー を Claude と設計 |
| Week 2 | Day 10 | F-02「認識齟齬検知」プラグインを実装 | プロンプトエンジニアリングを Claude と練る |
| Week 2 | Day 11 | F-03「過去会議横断検索」（Cosmos DB + AI Search）+ F-08「Entra ID 権限フィルタ」 | 認可周りは慎重に。Claude にレビューさせる |
| Week 2 | Day 12 | E2E テスト、デモシナリオ作成（5 分の模擬会議）、不具合修正 | バグレポートを Claude に投げて原因切り分け |
| Week 2 | Day 13 | デモ動画録画、Zenn 記事執筆、アーキテクチャ図（Mermaid）作成 | Claude に記事下書きと図の Mermaid 構文を書かせる |
| Week 2 | Day 14 | バグ修正、最終確認、提出 | 提出前チェックリストを Claude に作らせる |

**バッファ戦略**：
- **Day 7 時点で MVP（C-01 + C-02：仕様補完）が動くこと**を絶対死守。これだけで提出可能な状態にしておく。
- Day 8 以降の機能はすべて「あれば加点」扱い。詰まったら順番に切り捨てる。
- 切り捨て優先順位（低いほうから捨てる）：F-05 沈黙検知 → F-04 コード片解析 → F-08 権限フィルタ → F-07 機密マスキング → F-03 過去会議横断 → F-02 認識齟齬検知 → F-01 用語解説 → F-06 オプトイン → **C-03 曖昧発言明確化（差別化の要、なるべく死守）** → **C-02 仕様補完（絶対死守）**

---

## 6. リスクと対策

| リスク | 対策 |
|--------|------|
| Teams のリアルタイム音声取得が難しい | 初期版は Teams Live Transcription（標準機能）の出力を取得する形で妥協。リアルタイム性が落ちる分、デモではナレーションで補足。 |
| Azure クレジット不足 | Azure for Students / 無料枠 / ハッカソン提供枠を事前に確認。GPT-4o-mini を中心に使いコスト抑制。 |
| Bot Framework / Teams Manifest の登録ハマり | Day 2 で必ず突破する。詰まったらすぐ Claude にエラー全文を貼って原因特定。 |
| Entra ID 認証フローの複雑さ | Day 11 まで先送りせず、Day 1-2 で「最小限の認証付き呼び出し」を通しておく。 |
| Claude の出力ハルシネーション | Claude が示した API・パッケージ・コマンドは必ず公式ドキュメントで存在確認してから採用する。 |
| 提出物の動作確認用ログイン | デモ用ゲストアカウントを作成し、Zenn 記事に記載できるよう準備。 |
| デモ動画作成の時間 | Day 13 にまとめてではなく、Day 7 と Day 12 で 2 回録画する想定で予備時間を確保。 |

---

## 7. 審査基準への対応マッピング

| 審査基準 | 本プロジェクトでのアピールポイント |
|---------|------------------------------------|
| ビジネスインパクト | 会議のすれ違いを **会議中にリアルタイム** で解消する点が Microsoft 365 Copilot にない独自価値。社内ドキュメント検索・コード参照との連携も差別化要素。 |
| アプローチの有効性 | エージェントが「聞く → 不明点を能動検出 → 検索 → 投稿」「曖昧発言を発話者に問い返し → 整理して投稿」という Agentic な振る舞いを Semantic Kernel で実装。 |
| 完成度・実現性 | Docker + Terraform + GitHub Actions による IaC・自動デプロイで実務導入を想定。Azure AI Search でハイブリッド検索、Cosmos DB でスケール可能なデータ層。Entra ID 権限フィルタで企業導入の必須要件にも対応。 |

---

## 8. 次のアクション（決定したら開始）

1. Azure サブスクリプション / M365 テナントの権限確認、Azure OpenAI の利用申請（リージョン確認）
2. Bot Framework 用アプリ登録（Entra ID）
3. 開発環境構築：Python 3.11 + uv（or poetry） + Docker Desktop + Terraform CLI + Azure CLI
4. デモシナリオの台本作成（5 分程度の会議想定）
5. RAG 用ドキュメントセットの準備（仕様書サンプル数件）
6. GitHub リポジトリ作成（公開設定、提出用タグ運用ルールを README に記載）
7. Terraform 用の Azure Storage（state バックエンド）を手動で作成、Service Principal も作成して GitHub Secrets に登録

---

**参考リンク**
- Microsoft Agent Hackathon: https://zenn.dev/hackathons/microsoft-agent-hackathon-2026
- Copilot Studio: https://www.microsoft.com/microsoft-copilot/microsoft-copilot-studio
- Semantic Kernel: https://learn.microsoft.com/semantic-kernel/
- Azure AI Agent Service: https://learn.microsoft.com/azure/ai-services/agents/
