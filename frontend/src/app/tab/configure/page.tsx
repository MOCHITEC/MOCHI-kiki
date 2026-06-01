"use client";

import { useEffect, useState } from "react";
import Script from "next/script";

declare global {
  interface Window {
    microsoftTeams?: {
      app: {
        initialize: () => Promise<void>;
      };
      pages: {
        config: {
          setValidityState: (valid: boolean) => void;
          registerOnSaveHandler: (
            handler: (saveEvent: { notifySuccess: () => void; notifyFailure: (reason?: string) => void }) => void,
          ) => void;
          setConfig: (config: {
            contentUrl: string;
            websiteUrl?: string;
            suggestedDisplayName?: string;
            entityId?: string;
          }) => Promise<void>;
        };
      };
    };
  }
}

export default function TabConfigurePage() {
  const [status, setStatus] = useState<"loading" | "ready" | "outside_teams">(
    "loading",
  );

  useEffect(() => {
    const initTeams = async () => {
      if (typeof window === "undefined") return;
      // Microsoft Teams SDK が読み込まれるまで待つ
      let attempts = 0;
      const wait = () =>
        new Promise<void>((resolve) => setTimeout(resolve, 100));
      while (!window.microsoftTeams && attempts < 50) {
        await wait();
        attempts++;
      }
      const teams = window.microsoftTeams;
      if (!teams) {
        setStatus("outside_teams");
        return;
      }
      try {
        await teams.app.initialize();
        teams.pages.config.setValidityState(true);
        teams.pages.config.registerOnSaveHandler((saveEvent) => {
          const origin =
            typeof window !== "undefined" ? window.location.origin : "";
          teams.pages.config
            .setConfig({
              contentUrl: `${origin}/tab/content/`,
              websiteUrl: `${origin}/tab/content/`,
              suggestedDisplayName: "MOCHI-kiki",
              entityId: "mochi-kiki-tab",
            })
            .then(() => saveEvent.notifySuccess())
            .catch((e: unknown) =>
              saveEvent.notifyFailure(String(e ?? "unknown error")),
            );
        });
        setStatus("ready");
      } catch {
        setStatus("outside_teams");
      }
    };
    initTeams();
  }, []);

  return (
    <>
      <Script
        src="https://res.cdn.office.net/teams-js/2.19.0/js/MicrosoftTeams.min.js"
        strategy="afterInteractive"
      />
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
        <h1 style={{ fontSize: 22, margin: "0 0 12px" }}>MOCHI-kiki セットアップ</h1>
        <p style={{ color: "#444", margin: "0 0 16px" }}>
          この会議で発生する発話を自動で文字起こしし、AI が応答を会議チャットに投稿します。
          「保存」を押すと有効化されます。
        </p>
        <div
          style={{
            padding: "12px 16px",
            borderRadius: 8,
            background:
              status === "ready"
                ? "#e8f5e9"
                : status === "outside_teams"
                  ? "#fff3e0"
                  : "#f5f5f5",
            color: "#333",
            fontSize: 13,
          }}
        >
          {status === "loading" && "Teams SDK を初期化中..."}
          {status === "ready" &&
            "✓ 準備完了。右下の「保存」を押すと会議で有効化されます。"}
          {status === "outside_teams" &&
            "Teams クライアント外でこのページを開いています。Teams 会議の「アプリ追加」からアクセスしてください。"}
        </div>
      </main>
    </>
  );
}
