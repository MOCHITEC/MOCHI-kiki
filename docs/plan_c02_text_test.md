# C02 テキスト入力テスト計画

会議音声の代わりにテキスト入力で C02 パイプライン（意図解析 → RAG 検索 → 回答生成）を検証する。

---

## 背景と目的

現在の C02 フローは Teams 会議の文字起こしを Graph API 経由で受信するため、ローカルテストには実際の Teams 会議が必要。  
これを回避し、**テキストを直接入力して C02 の各ステージの動作を確認できる** 仕組みを構築する。

### テスト対象のパイプライン

```
テキスト入力
    ↓
Utterance.new() — モック発話オブジェクト生成
    ↓
IntentAnalysisPlugin.analyze(text) → IntentResult (SPEC_INQUIRY / AMBIGUOUS / NORMAL)
    ↓ [SPEC_INQUIRY の場合]
RAGSearchPlugin.search(keywords) → List[SearchResult]
    ↓
AnswerGenerationPlugin.generate(utterance, results) → answer_text
    ↓
コンソール出力 / REST レスポンス（Teams には投稿しない）
```

---

## 実装フェーズ

### Phase 1 — ローカル CLI インタラクティブスクリプト

**ファイル**: `scripts/test_c02_interactive.py`

**目的**: ループで何度でもテキストを入力し、各ステージの出力をコンソールで確認する。

**変更点**:
- `scripts/local_e2e_test.py` をベースに、固定発話リストの代わりに `input()` ループを追加
- `ChatPosterPlugin` をモックし、投稿内容をコンソールに表示
- 各ステージ（意図・キーワード・検索結果・回答）を `print` で明示的に出力

**実行方法**:
```bash
cd C:\Users\hendr\Programming\MOCHI-kiki
python -m scripts.test_c02_interactive
```

**期待する出力例**:
```
テキストを入力（終了: quit）: 認証フローの仕様はどうなっていましたっけ？

[1] 意図解析
  intent   : SPEC_INQUIRY
  confidence: 0.95
  keywords : ['認証フロー', '仕様']

[2] RAG 検索（ヒット数: 2）
  - [0.87] 認証フロー設計書 v1.2 — OAuth2.0 の認可コードフローを使用...
  - [0.81] API セキュリティガイドライン — トークン有効期限は 3600 秒...

[3] 回答生成
  → 認証フローは OAuth2.0 の認可コードフロー。トークン有効期限は 3600 秒。

[4] Teams 投稿（モック）
  テキスト: **[仕様補完]** 認証フローは OAuth2.0 の認可コードフロー。トークン有効期限は 3600 秒。
```

---

### Phase 2 — REST API テストエンドポイント

**ファイル**: `src/bot/app.py` に `/api/test/utterance` エンドポイントを追加

**目的**: curl や Postman からテキストを POST して C02 結果を JSON で受け取る。ローカルおよびデプロイ済み Container App の両方で使える。

**リクエスト**:
```http
POST /api/test/utterance
Content-Type: application/json

{
  "text": "認証フローの仕様はどうなっていましたっけ？",
  "speaker_name": "テスト太郎"
}
```

**レスポンス**:
```json
{
  "intent": "SPEC_INQUIRY",
  "confidence": 0.95,
  "keywords": ["認証フロー", "仕様"],
  "search_results": [
    { "title": "認証フロー設計書 v1.2", "score": 0.87, "content": "..." }
  ],
  "answer": "認証フローは OAuth2.0 の認可コードフロー。トークン有効期限は 3600 秒。",
  "posted_text": "**[仕様補完]** 認証フローは OAuth2.0 の認可コードフロー。トークン有効期限は 3600 秒。"
}
```

**実装方針**:
- `app.py` に `orchestrator` の参照を渡す（`app["orchestrator"]` に格納）
- エンドポイントハンドラ内で `Utterance.new()` を生成し `orchestrator.process()` を呼ぶ
- `ChatPosterPlugin` の `post()` を「実際には送らず結果を返す」モードに切り替える仕組みを追加
  - `ChatPosterPlugin.__init__` に `dry_run: bool = False` フラグを追加
  - `dry_run=True` のときは `continue_conversation` を呼ばずに投稿内容を返す

---

## 実装ステップ（作業順）

| # | 作業 | ファイル | 概要 |
|---|------|---------|------|
| 1 | `ChatPosterPlugin` に `dry_run` モード追加 | `src/plugins/chat_poster.py` | `dry_run=True` のとき投稿せず内容を返す |
| 2 | CLI スクリプト作成 | `scripts/test_c02_interactive.py` | インタラクティブ入力ループ、各ステージ表示 |
| 3 | オーケストレータに dry_run 対応 | `src/kernel/orchestrator.py` | `process_dry_run(utterance)` メソッドを追加し各ステージ結果を dict で返す |
| 4 | REST エンドポイント追加 | `src/bot/app.py` | `/api/test/utterance` ルート追加 |
| 5 | main.py でエンドポイントにオーケストレータを渡す | `src/main.py` | `app["orchestrator"] = orchestrator` を設定 |
| 6 | 動作確認 | — | CLI で 3 パターン入力、curl でエンドポイントを叩く |

---

## テストシナリオ

### パターン A: SPEC_INQUIRY（正常系）
```
入力: 認証フローの仕様はどうなっていましたっけ？
期待: SPEC_INQUIRY → 検索ヒット → 回答生成 → 出力
```

### パターン B: NORMAL（スキップ確認）
```
入力: ありがとうございます。
期待: NORMAL → 処理スキップ → 何も出力しない
```

### パターン C: 検索ヒットなし
```
入力: 量子コンピュータの仕様を教えてください
期待: SPEC_INQUIRY → 検索ヒット 0 件 → 回答生成スキップ
```

### パターン D: AMBIGUOUS（C03 確認）
```
入力: あれ、どうなってましたっけ？
期待: AMBIGUOUS → 問い返し文が生成される
```

---

## 前提条件

- `.env` または環境変数に以下が設定済みであること:
  - `AZURE_OPENAI_ENDPOINT`
  - `AZURE_OPENAI_KEY`
  - `AZURE_OPENAI_DEPLOYMENT` (gpt-4o)
  - `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` (text-embedding-3-small)
  - `AZURE_SEARCH_ENDPOINT`
  - `AZURE_SEARCH_KEY`
  - `AZURE_SEARCH_INDEX`
- AI Search インデックスにサンプルドキュメントが登録済み（`scripts/setup_search_index.py` を実行済み）
- `MICROSOFT_APP_ID` は空文字でも動作可（dry_run モードではポスト不要）

---

## 完了基準

- [ ] CLI スクリプトでパターン A〜D の全入力が正しく動作する
- [ ] `/api/test/utterance` が SPEC_INQUIRY に対して JSON レスポンスを返す
- [ ] Teams への実際の投稿が行われないことを確認（dry_run 動作）
