// MOCHI-kiki ハッカソン提出用 デモ動画スライド
// 16:9 / 12 枚 / 約 180 秒のナレーション付き
// 画面録画は Slide 7 (補完デモ) と Slide 9 (議事録デモ) に差し込む。

const path = require("path");
const pptxgen = require("pptxgenjs");

const COLOR = {
  navyDeep: "0F2A44",
  navy: "1C3D5A",
  oceanDeep: "065A82",
  oceanMid: "1C7293",
  ice: "D6E6F0",
  paper: "F6F8FA",
  ink: "0B1B2B",
  inkMuted: "55667A",
  amber: "D97706",
  amberSoft: "FEF3C7",
  white: "FFFFFF",
};

const FONT_HEAD = "Helvetica Neue";
const FONT_BODY = "Helvetica Neue";
const FONT_JP = "Hiragino Sans";

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10" x 5.625"
pres.author = "MOCHI-tec / Ruuuhs";
pres.title = "MOCHI-kiki デモ動画スライド";

function addFooter(slide, page, total) {
  slide.addText(
    [
      { text: "MOCHI-kiki", options: { color: COLOR.inkMuted, fontFace: FONT_BODY, bold: true } },
      { text: "  /  Microsoft Agent Hackathon 2026", options: { color: COLOR.inkMuted, fontFace: FONT_BODY } },
    ],
    { x: 0.4, y: 5.25, w: 6, h: 0.3, fontSize: 9, margin: 0 }
  );
  slide.addText(`${page} / ${total}`, {
    x: 9.0, y: 5.25, w: 0.6, h: 0.3,
    fontSize: 9, color: COLOR.inkMuted, fontFace: FONT_BODY, align: "right", margin: 0,
  });
}

function addEyebrow(slide, text, color = COLOR.oceanDeep) {
  slide.addText(text, {
    x: 0.4, y: 0.3, w: 6, h: 0.3,
    fontSize: 11, color, fontFace: FONT_HEAD, bold: true, charSpacing: 4, margin: 0,
  });
}

const TOTAL = 12;

/* Slide 1: タイトル */
{
  const s = pres.addSlide();
  s.background = { color: COLOR.navyDeep };

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.0, y: 0.0, w: 0.18, h: 5.625, fill: { color: COLOR.oceanMid }, line: { color: COLOR.oceanMid },
  });

  s.addText("MICROSOFT AGENT HACKATHON 2026", {
    x: 0.7, y: 0.7, w: 9, h: 0.4,
    fontSize: 12, color: COLOR.ice, fontFace: FONT_HEAD, bold: true, charSpacing: 6, margin: 0,
  });

  s.addText("MOCHI-kiki", {
    x: 0.7, y: 1.3, w: 9, h: 1.1,
    fontSize: 60, color: COLOR.white, fontFace: FONT_HEAD, bold: true, margin: 0,
  });

  s.addText("Teams 会議に常駐する Agentic AI", {
    x: 0.7, y: 2.45, w: 9, h: 0.6,
    fontSize: 26, color: COLOR.ice, fontFace: FONT_JP, margin: 0,
  });

  s.addText("会議中に動くボット — 仕様補完と、ライブ議事録ビュー", {
    x: 0.7, y: 3.15, w: 9, h: 0.5,
    fontSize: 16, color: COLOR.ice, fontFace: FONT_JP, margin: 0,
  });

  s.addShape(pres.shapes.LINE, {
    x: 0.7, y: 4.1, w: 1.5, h: 0,
    line: { color: COLOR.oceanMid, width: 2 },
  });

  s.addText("Azure  /  Semantic Kernel  /  Recall.ai  /  Bot Framework", {
    x: 0.7, y: 4.25, w: 9, h: 0.4,
    fontSize: 13, color: COLOR.ice, fontFace: FONT_HEAD, margin: 0,
  });

  s.addText("Ruuuhs (@mochitec)", {
    x: 0.7, y: 4.75, w: 9, h: 0.3,
    fontSize: 11, color: COLOR.ice, fontFace: FONT_HEAD, margin: 0,
  });

  s.addNotes(
    [
      "[0:00–0:15 / 15 秒]",
      "",
      "Teams 会議で、こんなことありませんか。",
      "仕様の確認のために、誰かが画面共有で資料を探し始めて、会議が止まる。",
      "「あれをやっておいて」のまま終わって、あとで認識が食い違う。",
      "",
      "[撮影メモ] 静止 5 秒 → 次スライドへフェード。",
    ].join("\n")
  );
}

/* Slide 2: 痛み */
{
  const s = pres.addSlide();
  s.background = { color: COLOR.paper };
  addEyebrow(s, "01  /  PROBLEM");

  s.addText("会議が止まる、認識が食い違う", {
    x: 0.4, y: 0.75, w: 9.2, h: 0.8,
    fontSize: 34, color: COLOR.ink, fontFace: FONT_JP, bold: true, margin: 0,
  });

  const cardY = 1.85, cardH = 2.9;

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.4, y: cardY, w: 4.5, h: cardH, fill: { color: COLOR.white }, line: { color: COLOR.ice, width: 1 },
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.4, y: cardY, w: 0.08, h: cardH, fill: { color: COLOR.oceanDeep }, line: { color: COLOR.oceanDeep },
  });
  s.addText("会議中に起きていること", {
    x: 0.7, y: cardY + 0.2, w: 4.1, h: 0.35,
    fontSize: 12, color: COLOR.oceanDeep, fontFace: FONT_HEAD, bold: true, margin: 0,
  });
  s.addText(
    [
      { text: "用語・仕様を確認するために、誰かが画面共有でドキュメントを探し始める", options: { bullet: true, breakLine: true, paraSpaceAfter: 12 } },
      { text: "「〇〇って何でしたっけ」に答えられず、議論が止まる", options: { bullet: true, breakLine: true, paraSpaceAfter: 12 } },
      { text: "「あれをやっておいて」のまま終わり、あとで認識が食い違う", options: { bullet: true } },
    ],
    { x: 0.7, y: cardY + 0.65, w: 4.1, h: cardH - 0.8, fontSize: 14, color: COLOR.ink, fontFace: FONT_JP, valign: "top" }
  );

  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.1, y: cardY, w: 4.5, h: cardH, fill: { color: COLOR.white }, line: { color: COLOR.ice, width: 1 },
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.1, y: cardY, w: 0.08, h: cardH, fill: { color: COLOR.amber }, line: { color: COLOR.amber },
  });
  s.addText("Microsoft 365 Copilot Recap", {
    x: 5.4, y: cardY + 0.2, w: 4.1, h: 0.35,
    fontSize: 12, color: COLOR.amber, fontFace: FONT_HEAD, bold: true, margin: 0,
  });
  s.addText(
    [
      { text: "会議後の要約・アクション抽出は十分まかなえる", options: { bullet: true, breakLine: true, paraSpaceAfter: 12 } },
      { text: "ただし「会議が終わってから」動く設計", options: { bullet: true, breakLine: true, paraSpaceAfter: 12 } },
      { text: "用語不明や仕様確認の場面では、会議中に助けてくれない", options: { bullet: true } },
    ],
    { x: 5.4, y: cardY + 0.65, w: 4.1, h: cardH - 0.8, fontSize: 14, color: COLOR.ink, fontFace: FONT_JP, valign: "top" }
  );

  addFooter(s, 2, TOTAL);

  s.addNotes(
    [
      "[0:15–0:30 / 15 秒]",
      "",
      "Microsoft 365 Copilot Recap は、会議後の要約や Action 抽出は十分まかなえます。",
      "ただ、会議の最中には動きません。",
      "会議中の用語確認や、認識合わせは、別の仕組みが要ります。",
    ].join("\n")
  );
}

/* Slide 3: 2 機能 */
{
  const s = pres.addSlide();
  s.background = { color: COLOR.paper };
  addEyebrow(s, "02  /  WHAT WE BUILT");

  s.addText("MOCHI-kiki — 会議中に動くボット", {
    x: 0.4, y: 0.75, w: 9.2, h: 0.8,
    fontSize: 34, color: COLOR.ink, fontFace: FONT_JP, bold: true, margin: 0,
  });

  s.addText("MVP は 2 機能で構成しています。", {
    x: 0.4, y: 1.5, w: 9.2, h: 0.4,
    fontSize: 14, color: COLOR.inkMuted, fontFace: FONT_JP, margin: 0,
  });

  const y = 2.1, h = 2.8;

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.4, y, w: 4.5, h, fill: { color: COLOR.oceanDeep }, line: { color: COLOR.oceanDeep },
  });
  s.addText("C-02", {
    x: 0.7, y: y + 0.25, w: 1.5, h: 0.4,
    fontSize: 11, color: COLOR.ice, fontFace: FONT_HEAD, bold: true, charSpacing: 4, margin: 0,
  });
  s.addText("ドキュメント参照補完", {
    x: 0.7, y: y + 0.7, w: 4.1, h: 0.6,
    fontSize: 22, color: COLOR.white, fontFace: FONT_JP, bold: true, margin: 0,
  });
  s.addText("用語・仕様などドキュメント参照が必要な発言を検知し、社内ドキュメントを引いて 200 字の回答を会議チャットへ自動投稿する。", {
    x: 0.7, y: y + 1.4, w: 4.1, h: 1.3,
    fontSize: 13, color: COLOR.ice, fontFace: FONT_JP, valign: "top", margin: 0,
  });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.1, y, w: 4.5, h, fill: { color: COLOR.oceanMid }, line: { color: COLOR.oceanMid },
  });
  s.addText("C-04", {
    x: 5.4, y: y + 0.25, w: 1.5, h: 0.4,
    fontSize: 11, color: COLOR.ice, fontFace: FONT_HEAD, bold: true, charSpacing: 4, margin: 0,
  });
  s.addText("ライブ議事録ビュー", {
    x: 5.4, y: y + 0.7, w: 4.1, h: 0.6,
    fontSize: 22, color: COLOR.white, fontFace: FONT_JP, bold: true, margin: 0,
  });
  s.addText("会議の発話から議事録とタイムラインをライブ生成し、管理コンソールで閲覧できる。会議チャットには投稿しない。", {
    x: 5.4, y: y + 1.4, w: 4.1, h: 1.3,
    fontSize: 13, color: COLOR.ice, fontFace: FONT_JP, valign: "top", margin: 0,
  });

  addFooter(s, 3, TOTAL);

  s.addNotes(
    [
      "[0:30–0:45 / 15 秒]",
      "",
      "そこで作ったのが MOCHI-kiki です。",
      "会議中に動くボットで、MVP は 2 機能。",
      "ドキュメント参照補完と、ライブ議事録ビューです。",
    ].join("\n")
  );
}

/* Slide 4: アーキテクチャ */
{
  const s = pres.addSlide();
  s.background = { color: COLOR.paper };
  addEyebrow(s, "03  /  ARCHITECTURE");

  s.addText("アーキテクチャ全体像", {
    x: 0.4, y: 0.75, w: 9.2, h: 0.7,
    fontSize: 30, color: COLOR.ink, fontFace: FONT_JP, bold: true, margin: 0,
  });

  s.addText("Recall.ai が音声と文字起こしを返し、Semantic Kernel オーケストレータが意図検知と RAG を回す。", {
    x: 0.4, y: 1.4, w: 9.2, h: 0.4,
    fontSize: 13, color: COLOR.inkMuted, fontFace: FONT_JP, margin: 0,
  });

  const nodes = [
    { x: 0.4, y: 2.2, w: 1.7, h: 1.0, label: "Microsoft\nTeams", sub: "会議", color: COLOR.oceanDeep },
    { x: 2.4, y: 2.2, w: 1.7, h: 1.0, label: "Recall.ai\nボット", sub: "音声 / 文字起こし", color: COLOR.oceanMid },
    { x: 4.4, y: 2.2, w: 1.7, h: 1.0, label: "Bot プロセス", sub: "Container Apps", color: COLOR.oceanDeep },
    { x: 6.4, y: 2.2, w: 1.7, h: 1.0, label: "Semantic\nKernel", sub: "Intent / RAG", color: COLOR.oceanMid },
    { x: 8.4, y: 2.2, w: 1.4, h: 1.0, label: "Teams\nチャット投稿", sub: "Bot Framework", color: COLOR.oceanDeep },
  ];
  nodes.forEach((n) => {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: n.x, y: n.y, w: n.w, h: n.h, fill: { color: n.color }, line: { color: n.color }, rectRadius: 0.08,
    });
    s.addText(n.label, {
      x: n.x, y: n.y + 0.1, w: n.w, h: 0.55,
      fontSize: 13, color: COLOR.white, fontFace: FONT_JP, bold: true, align: "center", valign: "middle", margin: 0,
    });
    s.addText(n.sub, {
      x: n.x, y: n.y + 0.65, w: n.w, h: 0.3,
      fontSize: 10, color: COLOR.ice, fontFace: FONT_JP, align: "center", margin: 0,
    });
  });

  const arrowYs = 2.7;
  [[2.17, 2.33], [4.17, 4.33], [6.17, 6.33], [8.17, 8.33]].forEach(([x1, x2]) => {
    s.addShape(pres.shapes.LINE, {
      x: x1, y: arrowYs, w: x2 - x1, h: 0,
      line: { color: COLOR.inkMuted, width: 1.5, endArrowType: "triangle" },
    });
  });

  s.addText("バックエンドサービス", {
    x: 0.4, y: 3.55, w: 9.2, h: 0.3,
    fontSize: 11, color: COLOR.oceanDeep, fontFace: FONT_HEAD, bold: true, margin: 0,
  });
  const azureNodes = [
    { x: 0.4, label: "Azure OpenAI", sub: "GPT-4o / Embedding" },
    { x: 3.4, label: "Azure AI Search", sub: "ハイブリッド検索" },
    { x: 6.4, label: "Cosmos DB", sub: "セッション / 議事録" },
  ];
  azureNodes.forEach((n) => {
    s.addShape(pres.shapes.RECTANGLE, {
      x: n.x, y: 3.95, w: 2.9, h: 0.75, fill: { color: COLOR.white }, line: { color: COLOR.oceanMid, width: 1 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x: n.x, y: 3.95, w: 0.08, h: 0.75, fill: { color: COLOR.oceanMid }, line: { color: COLOR.oceanMid },
    });
    s.addText(n.label, {
      x: n.x + 0.2, y: 4.0, w: 2.6, h: 0.35,
      fontSize: 13, color: COLOR.ink, fontFace: FONT_JP, bold: true, margin: 0,
    });
    s.addText(n.sub, {
      x: n.x + 0.2, y: 4.35, w: 2.6, h: 0.3,
      fontSize: 10, color: COLOR.inkMuted, fontFace: FONT_JP, margin: 0,
    });
  });

  addFooter(s, 4, TOTAL);

  s.addNotes(
    [
      "[0:45–1:10 / 25 秒]",
      "",
      "構成はこうです。",
      "Teams の音声と文字起こしを Recall.ai のボットから WebSocket で受け取り、",
      "Semantic Kernel のオーケストレータが意図検知と RAG を回します。",
      "検索は Azure AI Search のハイブリッド検索、回答生成は GPT-4o。",
      "投稿は Bot Framework から会議チャットに返します。",
    ].join("\n")
  );
}

/* Slide 5: 5 ステップ */
{
  const s = pres.addSlide();
  s.background = { color: COLOR.paper };
  addEyebrow(s, "04  /  PIPELINE");

  s.addText("ドキュメント参照補完  —  5 ステップ", {
    x: 0.4, y: 0.75, w: 9.2, h: 0.7,
    fontSize: 30, color: COLOR.ink, fontFace: FONT_JP, bold: true, margin: 0,
  });

  const steps = [
    { n: "01", t: "IntentAnalysis", d: "発話を分類 (spec_inquiry / ambiguous / normal) し、キーワードを JSON で返す" },
    { n: "02", t: "RAGSearch", d: "spec_inquiry のキーワードで Azure AI Search のハイブリッド検索 (上位 3 件)" },
    { n: "03", t: "AnswerGeneration", d: "GPT-4o で 3 件をコンテキストに 200 字以内へ整形" },
    { n: "04", t: "Guard", d: "Python 側で text[:200] と [仕様補完] プレフィックスを二重ガード" },
    { n: "05", t: "ChatPoster", d: "Bot Framework で proactive メッセージとして会議チャットへ投稿" },
  ];
  const top = 1.7, rowH = 0.62, gap = 0.05;
  steps.forEach((st, i) => {
    const y = top + i * (rowH + gap);
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.4, y, w: 9.2, h: rowH, fill: { color: COLOR.white }, line: { color: COLOR.ice, width: 1 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.4, y, w: 0.08, h: rowH, fill: { color: COLOR.oceanDeep }, line: { color: COLOR.oceanDeep },
    });
    s.addText(st.n, {
      x: 0.6, y: y + 0.08, w: 0.7, h: rowH - 0.16,
      fontSize: 16, color: COLOR.oceanDeep, fontFace: FONT_HEAD, bold: true, valign: "middle", margin: 0,
    });
    s.addText(st.t, {
      x: 1.4, y: y + 0.08, w: 2.4, h: rowH - 0.16,
      fontSize: 14, color: COLOR.ink, fontFace: FONT_HEAD, bold: true, valign: "middle", margin: 0,
    });
    s.addText(st.d, {
      x: 3.9, y: y + 0.08, w: 5.6, h: rowH - 0.16,
      fontSize: 12, color: COLOR.inkMuted, fontFace: FONT_JP, valign: "middle", margin: 0,
    });
  });

  addFooter(s, 5, TOTAL);

  s.addNotes(
    [
      "[1:10–1:25 / 15 秒]",
      "",
      "補完機能の中身は、5 つのステップです。",
      "意図検知、検索、回答整形、ガード、投稿。",
      "Semantic Kernel のプラグインとして組んでいます。",
    ].join("\n")
  );
}

/* Slide 6: デモ A タイトル */
{
  const s = pres.addSlide();
  s.background = { color: COLOR.navy };
  addEyebrow(s, "DEMO A", COLOR.ice);

  s.addText("ドキュメント参照補完", {
    x: 0.4, y: 1.6, w: 9.2, h: 1.0,
    fontSize: 48, color: COLOR.white, fontFace: FONT_JP, bold: true, align: "center", margin: 0,
  });

  s.addText("「RU 上限は」と発話 → 数十秒後にチャットへ自動補足", {
    x: 0.4, y: 2.7, w: 9.2, h: 0.6,
    fontSize: 20, color: COLOR.ice, fontFace: FONT_JP, align: "center", margin: 0,
  });

  s.addText("次のスライドで実画面 (4–6 倍速)", {
    x: 0.4, y: 4.2, w: 9.2, h: 0.4,
    fontSize: 14, color: COLOR.ice, fontFace: FONT_HEAD, align: "center", margin: 0,
  });

  s.addNotes(
    [
      "[1:25–1:30 / 5 秒]",
      "",
      "まずは、補完デモから。",
      "",
      "[撮影メモ] このタイトルカードは 3–5 秒だけ表示してすぐ次の画面録画スライドへ。",
    ].join("\n")
  );
}

/* Slide 7: 画面録画 A スロット */
{
  const s = pres.addSlide();
  s.background = { color: "0A0A0A" };

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 0.4, w: 9.0, h: 4.4, fill: { color: "1A1A1A" }, line: { color: "303030", width: 1 },
  });

  s.addText("[ 画面録画 A を差し込む ]", {
    x: 0.5, y: 2.2, w: 9.0, h: 0.6,
    fontSize: 22, color: "8A8A8A", fontFace: FONT_HEAD, bold: true, align: "center", margin: 0,
  });

  s.addText("Teams 会議 (左) + チャット欄 (右) のスプリット。発話 → 数十秒で [仕様補完] 自動投稿。\n実時間 ~25 秒は 4–6x 倍速 + テロップ「実測 ~25 秒」を重ねる。", {
    x: 0.5, y: 3.0, w: 9.0, h: 1.0,
    fontSize: 13, color: "8A8A8A", fontFace: FONT_JP, align: "center", valign: "top", margin: 0,
  });

  s.addText("DEMO A  /  ~40 秒", {
    x: 0.5, y: 5.0, w: 9.0, h: 0.3,
    fontSize: 10, color: "6A6A6A", fontFace: FONT_HEAD, align: "center", margin: 0,
  });

  s.addNotes(
    [
      "[1:30–2:10 / 40 秒]",
      "",
      "会議で「マスター切替の RU 上限ってどれくらいでしたっけ」と話します。",
      "意図検知が spec_inquiry と判定し、キーワードでハイブリッド検索が走ります。",
      "GPT-4o が 200 字以内に整形し、会議チャットへ [仕様補完] プレフィックス付きで自動投稿します。",
      "発言者はドキュメントを開かなくて済みます。",
      "",
      "[撮影メモ]",
      "・素材: Teams 会議 5–10 分を Cmd+Shift+5 でフル録画。チャット欄が見える分割。",
      "・編集: 待機時間は 4–6x 倍速、テロップ「実測 ~25 秒」を画面下に重ねる。",
      "・字幕は必須 (DaVinci の音声→字幕 or CapCut)。",
    ].join("\n")
  );
}

/* Slide 8: 議事録ビュー 3 種 */
{
  const s = pres.addSlide();
  s.background = { color: COLOR.paper };
  addEyebrow(s, "05  /  LIVE MINUTES");

  s.addText("ライブ議事録ビュー  —  別 UI に切り出し", {
    x: 0.4, y: 0.75, w: 9.2, h: 0.7,
    fontSize: 28, color: COLOR.ink, fontFace: FONT_JP, bold: true, margin: 0,
  });

  s.addText("管理コンソール /meeting?id=... に 3 つのビューを並べている。", {
    x: 0.4, y: 1.4, w: 9.2, h: 0.4,
    fontSize: 13, color: COLOR.inkMuted, fontFace: FONT_JP, margin: 0,
  });

  const y = 1.95, w = 2.95, h = 2.85;
  const cards = [
    { x: 0.4, t: "議事録", d: "GPT-4o で「議題 / 決定事項 / TODO / 質疑応答」を構造化 Markdown で全文再生成", tempo: "90 秒", color: COLOR.oceanDeep },
    { x: 3.55, t: "タイムライン", d: "5 分ブロックごとに 150 字要約。末尾ブロックのみ再要約し、確定済みには触らない", tempo: "90 秒", color: COLOR.oceanMid },
    { x: 6.7, t: "文字起こし", d: "発話データをそのまま表示。最新の発話を即座に追いかけられる", tempo: "5 秒", color: COLOR.navy },
  ];
  cards.forEach((c) => {
    s.addShape(pres.shapes.RECTANGLE, {
      x: c.x, y, w, h, fill: { color: COLOR.white }, line: { color: COLOR.ice, width: 1 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x: c.x, y, w, h: 0.5, fill: { color: c.color }, line: { color: c.color },
    });
    s.addText(c.t, {
      x: c.x + 0.2, y: y + 0.08, w: w - 0.4, h: 0.4,
      fontSize: 16, color: COLOR.white, fontFace: FONT_JP, bold: true, valign: "middle", margin: 0,
    });
    s.addText(c.d, {
      x: c.x + 0.2, y: y + 0.7, w: w - 0.4, h: h - 1.35,
      fontSize: 12, color: COLOR.ink, fontFace: FONT_JP, valign: "top", margin: 0,
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x: c.x + 0.2, y: y + h - 0.55, w: 1.4, h: 0.35, fill: { color: COLOR.ice }, line: { color: COLOR.ice },
    });
    s.addText(`更新  ${c.tempo}`, {
      x: c.x + 0.2, y: y + h - 0.55, w: 1.4, h: 0.35,
      fontSize: 10, color: COLOR.oceanDeep, fontFace: FONT_HEAD, bold: true, align: "center", valign: "middle", margin: 0,
    });
  });

  addFooter(s, 8, TOTAL);

  s.addNotes(
    [
      "[2:10–2:25 / 15 秒]",
      "",
      "議事録ビューは別 UI に切り出しています。",
      "会議チャットには投稿せず、あとから振り返る用途です。",
      "1 画面に 3 つのビューがあります。",
      "議事録は 90 秒、タイムラインは 5 分、文字起こしは 5 秒で更新します。",
    ].join("\n")
  );
}

/* Slide 9: 画面録画 B スロット */
{
  const s = pres.addSlide();
  s.background = { color: "0A0A0A" };

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 0.4, w: 9.0, h: 4.4, fill: { color: "1A1A1A" }, line: { color: "303030", width: 1 },
  });

  s.addText("[ 画面録画 B を差し込む ]", {
    x: 0.5, y: 2.2, w: 9.0, h: 0.6,
    fontSize: 22, color: "8A8A8A", fontFace: FONT_HEAD, bold: true, align: "center", margin: 0,
  });

  s.addText("管理コンソール /meeting?id=... の 3 ビューを順に映す。\n議事録 → タイムライン → 文字起こし。更新間隔の差をテロップで補足。", {
    x: 0.5, y: 3.0, w: 9.0, h: 1.0,
    fontSize: 13, color: "8A8A8A", fontFace: FONT_JP, align: "center", valign: "top", margin: 0,
  });

  s.addText("DEMO B  /  ~25 秒", {
    x: 0.5, y: 5.0, w: 9.0, h: 0.3,
    fontSize: 10, color: "6A6A6A", fontFace: FONT_HEAD, align: "center", margin: 0,
  });

  s.addNotes(
    [
      "[2:25–2:50 / 25 秒]",
      "",
      "議事録ビューに切り替えます。",
      "会議の発話から、議題・決定事項・TODO・質疑応答が 90 秒ごとに構造化 Markdown で再生成されます。",
      "タイムラインは 5 分ブロックごとに 150 字要約。確定済みブロックには触らず、末尾のみ再要約します。",
      "文字起こしは 5 秒ポーリングで最新発話まで追えます。",
      "",
      "[撮影メモ]",
      "・/meeting?id=... を別ウィンドウで開いた状態の録画。タブ切替を 3 回。",
      "・更新がよく見えるよう、会議終盤の発話が積もった素材を選ぶ。",
    ].join("\n")
  );
}

/* Slide 10: 弱点 */
{
  const s = pres.addSlide();
  s.background = { color: COLOR.paper };
  addEyebrow(s, "06  /  KNOWN ISSUE", COLOR.amber);

  s.addText("現状の課題  —  補完投稿のレイテンシ", {
    x: 0.4, y: 0.75, w: 9.2, h: 0.7,
    fontSize: 28, color: COLOR.ink, fontFace: FONT_JP, bold: true, margin: 0,
  });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.4, y: 1.55, w: 9.2, h: 0.85, fill: { color: COLOR.amberSoft }, line: { color: COLOR.amber, width: 1 },
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.4, y: 1.55, w: 0.08, h: 0.85, fill: { color: COLOR.amber }, line: { color: COLOR.amber },
  });
  s.addText("発話から投稿まで数十秒かかり、即答は MVP では未達。後追いの補足にとどまっている。", {
    x: 0.7, y: 1.55, w: 8.8, h: 0.85,
    fontSize: 14, color: COLOR.ink, fontFace: FONT_JP, bold: true, valign: "middle", margin: 0,
  });

  const cy = 2.65, ch = 2.3;
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.4, y: cy, w: 4.5, h: ch, fill: { color: COLOR.white }, line: { color: COLOR.ice, width: 1 },
  });
  s.addText("原因", {
    x: 0.7, y: cy + 0.2, w: 4.1, h: 0.35,
    fontSize: 12, color: COLOR.amber, fontFace: FONT_HEAD, bold: true, margin: 0,
  });
  s.addText(
    [
      { text: "Recall.ai の日本語 STT は精度モード固定 (prioritize_accuracy)", options: { bullet: true, breakLine: true, paraSpaceAfter: 10 } },
      { text: "発話塊が一区切りつくまで貯めてから返すため、STT だけで十数〜数十秒", options: { bullet: true, breakLine: true, paraSpaceAfter: 10 } },
      { text: "日本語では prioritize_low_latency が選べない (英語専用)", options: { bullet: true } },
    ],
    { x: 0.7, y: cy + 0.6, w: 4.1, h: ch - 0.7, fontSize: 12, color: COLOR.ink, fontFace: FONT_JP, valign: "top" }
  );

  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.1, y: cy, w: 4.5, h: ch, fill: { color: COLOR.white }, line: { color: COLOR.ice, width: 1 },
  });
  s.addText("残課題", {
    x: 5.4, y: cy + 0.2, w: 4.1, h: 0.35,
    fontSize: 12, color: COLOR.oceanDeep, fontFace: FONT_HEAD, bold: true, margin: 0,
  });
  s.addText(
    [
      { text: "Recall.ai を外し、低遅延な STT に置き換える検証", options: { bullet: true, breakLine: true, paraSpaceAfter: 10 } },
      { text: "Recall.ai 単体では、現実的な Teams 音声取得と即答が両立しない", options: { bullet: true } },
    ],
    { x: 5.4, y: cy + 0.6, w: 4.1, h: ch - 0.7, fontSize: 12, color: COLOR.ink, fontFace: FONT_JP, valign: "top" }
  );

  addFooter(s, 10, TOTAL);

  s.addNotes(
    [
      "[2:50–3:05 / 15 秒]",
      "",
      "課題もあります。補完投稿のレイテンシです。",
      "Recall.ai の日本語 STT は精度モード固定で、発話から投稿まで数十秒かかります。",
      "即答は未達で、後追いの補足にとどまっています。",
      "STT の置き換えが今後の課題です。",
    ].join("\n")
  );
}

/* Slide 11: スタック */
{
  const s = pres.addSlide();
  s.background = { color: COLOR.paper };
  addEyebrow(s, "07  /  STACK");

  s.addText("使用した Microsoft 技術", {
    x: 0.4, y: 0.75, w: 9.2, h: 0.7,
    fontSize: 30, color: COLOR.ink, fontFace: FONT_JP, bold: true, margin: 0,
  });

  const items = [
    { t: "Azure Container Apps", d: "Bot プロセス実行基盤 (必須要件 ①)" },
    { t: "Azure OpenAI", d: "GPT-4o + Embedding (必須要件 ②)" },
    { t: "Azure AI Search", d: "RAG ハイブリッド検索" },
    { t: "Azure AI Speech", d: "音声処理 (補助)" },
    { t: "Azure Cosmos DB", d: "セッション / 議事録の永続化 (autoscale)" },
    { t: "Azure Key Vault", d: "シークレット管理" },
    { t: "Semantic Kernel", d: "Intent / RAG / Answer プラグイン構成" },
    { t: "Bot Framework + Teams", d: "会議チャットへの proactive 投稿" },
  ];
  const colW = 4.55, rowH = 0.75, gap = 0.1;
  const startX = 0.4, startY = 1.55;
  items.forEach((it, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = startX + col * (colW + gap);
    const y = startY + row * (rowH + gap);
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: colW, h: rowH, fill: { color: COLOR.white }, line: { color: COLOR.ice, width: 1 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 0.08, h: rowH, fill: { color: COLOR.oceanDeep }, line: { color: COLOR.oceanDeep },
    });
    s.addText(it.t, {
      x: x + 0.2, y: y + 0.08, w: colW - 0.3, h: 0.35,
      fontSize: 13, color: COLOR.ink, fontFace: FONT_HEAD, bold: true, margin: 0,
    });
    s.addText(it.d, {
      x: x + 0.2, y: y + 0.42, w: colW - 0.3, h: 0.3,
      fontSize: 11, color: COLOR.inkMuted, fontFace: FONT_JP, margin: 0,
    });
  });

  addFooter(s, 11, TOTAL);

  s.addNotes(
    [
      "[BGM のみ / 補助スライド]",
      "",
      "ナレーションは入れず、5 秒前後で素早く流す。",
      "尺が押した場合はスキップしても OK。",
    ].join("\n")
  );
}

/* Slide 12: エンドカード */
{
  const s = pres.addSlide();
  s.background = { color: COLOR.navyDeep };

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.0, y: 0.0, w: 0.18, h: 5.625, fill: { color: COLOR.oceanMid }, line: { color: COLOR.oceanMid },
  });

  s.addText("THANK YOU", {
    x: 0.7, y: 0.6, w: 9, h: 0.5,
    fontSize: 14, color: COLOR.ice, fontFace: FONT_HEAD, bold: true, charSpacing: 6, margin: 0,
  });

  s.addText("ここまでが、MOCHI-kiki の現状です。", {
    x: 0.7, y: 1.2, w: 9, h: 0.8,
    fontSize: 32, color: COLOR.white, fontFace: FONT_JP, bold: true, margin: 0,
  });

  s.addText("詳細は Zenn の記事をご覧ください。", {
    x: 0.7, y: 2.0, w: 9, h: 0.5,
    fontSize: 16, color: COLOR.ice, fontFace: FONT_JP, margin: 0,
  });

  const linkY = 3.0;
  const links = [
    { label: "ARTICLE", value: "zenn.dev/ruuuhs/articles/mochi-kiki-teams-agent" },
    { label: "HACKATHON", value: "Microsoft Agent Hackathon 2026" },
    { label: "GITHUB", value: "github.com/mochitec/MOCHI-kiki  (公開予定)" },
  ];
  links.forEach((l, i) => {
    const y = linkY + i * 0.5;
    s.addText(l.label, {
      x: 0.7, y, w: 1.6, h: 0.4,
      fontSize: 10, color: COLOR.oceanMid, fontFace: FONT_HEAD, bold: true, charSpacing: 4, valign: "middle", margin: 0,
    });
    s.addText(l.value, {
      x: 2.3, y, w: 7.5, h: 0.4,
      fontSize: 14, color: COLOR.white, fontFace: FONT_HEAD, valign: "middle", margin: 0,
    });
  });

  s.addText("Ruuuhs (@mochitec)  /  MOCHI-tec", {
    x: 0.7, y: 4.85, w: 9, h: 0.3,
    fontSize: 11, color: COLOR.ice, fontFace: FONT_HEAD, margin: 0,
  });

  s.addNotes(
    [
      "[3:05–3:15 / 10 秒]",
      "",
      "詳細は Zenn の記事にまとめています。",
      "Microsoft Agent Hackathon 2026 への提出作品です。",
      "ご視聴ありがとうございました。",
      "",
      "[撮影メモ] 5 秒静止 → ゆっくりフェードアウト。BGM のフェードに合わせる。",
    ].join("\n")
  );
}

const outPath = path.resolve(__dirname, "mochi-kiki-demo-deck.pptx");
pres.writeFile({ fileName: outPath }).then((f) => {
  console.log("Wrote:", f);
});
