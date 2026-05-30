// dev-only in-memory store for /api/console/* mock route handlers.
// HMR で消える可能性あり (Next.js dev) — 開発確認用なので許容。

import type { Meeting, Utterance } from "@/lib/types";

interface DevMeeting extends Meeting {
  // Meeting と同じプロパティ
}

const meetings: DevMeeting[] = [];
const utterances: Record<string, Utterance[]> = {};

const SECRET_PREFIX = "devmock.";

export const devStore = {
  isMockEnabled(): boolean {
    return !process.env.BACKEND_URL;
  },

  expectedUser: process.env.CONSOLE_USERNAME ?? "admin",
  expectedPassword: process.env.CONSOLE_PASSWORD ?? "admin",

  issueToken(username: string): string {
    return SECRET_PREFIX + Buffer.from(username, "utf-8").toString("base64");
  },
  verifyToken(token: string | undefined): string | null {
    if (!token || !token.startsWith(SECRET_PREFIX)) return null;
    try {
      return Buffer.from(token.slice(SECRET_PREFIX.length), "base64").toString(
        "utf-8",
      );
    } catch {
      return null;
    }
  },

  generateMeetingId(): string {
    const ts = Math.floor(Date.now() / 1000);
    const rand = Math.floor(Math.random() * 0xffff)
      .toString(16)
      .padStart(4, "0");
    return `console-${ts}-${rand}`;
  },
  generateBotId(): string {
    return (
      "bot_" +
      Math.random().toString(36).slice(2, 10) +
      Math.random().toString(36).slice(2, 10)
    );
  },

  listMeetings(limit: number, before?: string): DevMeeting[] {
    const sorted = [...meetings].sort((a, b) => {
      const av = a.started_at ?? "";
      const bv = b.started_at ?? "";
      return bv.localeCompare(av);
    });
    const filtered = before
      ? sorted.filter((m) => (m.started_at ?? "") < before)
      : sorted;
    return filtered.slice(0, limit);
  },
  getMeeting(id: string): DevMeeting | undefined {
    return meetings.find((m) => m.meeting_id === id);
  },
  addMeeting(m: DevMeeting): void {
    meetings.unshift(m);
  },
  markEnded(botId: string): DevMeeting | undefined {
    const m = meetings.find((x) => x.recall_bot_id === botId);
    if (m) m.ended_at = new Date().toISOString();
    return m;
  },

  listUtterances(meetingId: string, since?: string): Utterance[] {
    const arr = utterances[meetingId] ?? [];
    const sorted = [...arr].sort((a, b) =>
      (a.timestamp ?? "").localeCompare(b.timestamp ?? ""),
    );
    if (since) return sorted.filter((u) => u.timestamp > since);
    return sorted;
  },
  countUtterances(meetingId: string): number {
    return (utterances[meetingId] ?? []).length;
  },
  seedSampleUtterances(meetingId: string): void {
    const base = Date.now();
    utterances[meetingId] = [
      {
        utterance_id: `${meetingId}-1`,
        speaker: "田中 太郎",
        text: "おはようございます、ミーティングを始めます。",
        timestamp: new Date(base).toISOString(),
      },
      {
        utterance_id: `${meetingId}-2`,
        speaker: "佐藤 花子",
        text: "本日の議題は MOCHI-kiki のフロントエンド確認です。",
        timestamp: new Date(base + 5000).toISOString(),
      },
      {
        utterance_id: `${meetingId}-3`,
        speaker: "田中 太郎",
        text: "(dev mock — 実データではありません)",
        timestamp: new Date(base + 10000).toISOString(),
      },
    ];
  },
};
