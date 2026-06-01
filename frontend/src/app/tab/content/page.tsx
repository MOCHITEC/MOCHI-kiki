export default function TabContentPage() {
  return (
    <main
      style={{
        fontFamily:
          'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
        padding: "40px",
        maxWidth: "560px",
        margin: "0 auto",
        lineHeight: 1.6,
      }}
    >
      <h1 style={{ fontSize: 22, margin: "0 0 12px" }}>MOCHI-kiki が有効です</h1>
      <p style={{ color: "#444", margin: "0 0 8px" }}>
        この会議の発話を自動で文字起こしし、AI が応答を会議チャットに投稿します。
      </p>
      <p style={{ color: "#666", margin: "0 0 16px", fontSize: 13 }}>
        会議中の発話は Recall.ai が拾い、MOCHI-kiki backend が AI 応答を生成して
        この会議のチャットに自動投稿します。
      </p>
      <div
        style={{
          padding: "12px 16px",
          borderRadius: 8,
          background: "#e8f5e9",
          color: "#333",
          fontSize: 13,
        }}
      >
        ✓ 状態: 有効化済み
      </div>
    </main>
  );
}
