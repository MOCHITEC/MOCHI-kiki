# MOCHI-kiki Teams App パッケージ

Teams 会議に MOCHI-kiki bot を「参加者」として呼ぶための Teams App パッケージ。

## ファイル

| ファイル | 用途 |
|---|---|
| `manifest.json` | Teams App マニフェスト (Microsoft App ID `c831aad8-5160-4b2b-aaf5-24534a1e0d1a` を `bots[0].botId` として参照) |
| `icons/color.png` | 192x192 フルカラーアイコン |
| `icons/outline.png` | 32x32 透明背景アイコン |
| `mochi-kiki.zip` | 上の 3 ファイルをまとめた sideload 用 zip |

## sideload 手順 (組織 Teams 必須)

1. https://teams.microsoft.com にアクセス (Microsoft 365 組織アカウント)
2. 左メニュー **「アプリ」** をクリック
3. 左下 **「アプリの管理」** → **「アプリのアップロード」**
4. **「自分のためにアップロード」** を選択
5. `teams-app/mochi-kiki.zip` を選択 → **追加**

→ 個人スペースに **MOCHI-kiki** が現れます。

> 個人用 Teams Live (`teams.live.com`) では custom app の sideload はできません。

## 会議への追加

1. Teams で会議を作成 (または既存会議の編集)
2. 会議画面右上の **「+」** アイコン → アプリ → **MOCHI-kiki** を追加
3. 会議開始時に backend (`src/bot/teams_bot.py:on_teams_meeting_start_activity`) が発火し、
   `_orchestrator.register_meeting(meeting_id, conversation_reference)` で会議の発言場所が保存される
4. Recall.ai から transcript が届くと `orchestrator.process(utterance)` が動き、
   AI 応答が `chat_poster` 経由で会議チャットに投稿される

## zip 再生成 (manifest 等を編集した場合)

```bash
cd teams-app
cp icons/color.png .
cp icons/outline.png .
zip -j mochi-kiki.zip manifest.json color.png outline.png
rm color.png outline.png
```

## アイコン差し替え

`icons/color.png` (192x192) と `icons/outline.png` (32x32) を入れ替えてから上記コマンドで zip 再作成。Mochi の Mascot 画像など差し替えるのがおすすめ。
