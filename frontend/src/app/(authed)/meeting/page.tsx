"use client";

import * as React from "react";
import Link from "next/link";
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Download, ArrowLeft } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  Dialog,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { formatDateTime } from "@/lib/utils";

function MeetingDetailInner() {
  const sp = useSearchParams();
  const meetingId = sp.get("id") ?? "";
  const qc = useQueryClient();

  const meetingQuery = useQuery({
    queryKey: ["meeting", meetingId],
    queryFn: () => api.getMeeting(meetingId),
    refetchInterval: 5000,
    enabled: !!meetingId,
  });

  const utterancesQuery = useQuery({
    queryKey: ["utterances", meetingId],
    queryFn: () => api.listUtterances(meetingId, { limit: 1000 }),
    refetchInterval: 5000,
    enabled: !!meetingId,
  });

  const minutesQuery = useQuery({
    queryKey: ["minutes", meetingId],
    queryFn: () => api.getMinutes(meetingId),
    refetchInterval: 30000,
    enabled: !!meetingId,
  });

  const timelineQuery = useQuery({
    queryKey: ["timeline", meetingId],
    queryFn: () => api.getTimeline(meetingId),
    refetchInterval: 30000,
    enabled: !!meetingId,
  });

  const [confirmLeave, setConfirmLeave] = React.useState(false);
  const [tab, setTab] = React.useState<"transcript" | "minutes" | "timeline">(
    "minutes",
  );

  const leave = useMutation({
    mutationFn: (botId: string) => api.leaveBot(botId),
    onSuccess: () => {
      toast.success("退出を要求しました");
      setConfirmLeave(false);
      qc.invalidateQueries({ queryKey: ["meeting", meetingId] });
      qc.invalidateQueries({ queryKey: ["meetings"] });
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : "退出に失敗しました";
      toast.error(msg);
    },
  });

  if (!meetingId) {
    return (
      <div className="rounded-lg border border-zinc-200 bg-white p-8 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-950">
        meeting_id を指定してください
      </div>
    );
  }

  const meeting = meetingQuery.data;
  const utterances = utterancesQuery.data?.utterances ?? [];
  const active = meeting && !meeting.ended_at;

  return (
    <div className="space-y-6">
      <Link
        href="/meetings"
        className="inline-flex items-center gap-1 text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-50"
      >
        <ArrowLeft className="h-4 w-4" /> 会議一覧へ
      </Link>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="space-y-1">
              <div className="font-mono text-sm break-all">
                meeting_id: {meetingId}
              </div>
              {meeting && (
                <>
                  <div className="text-xs text-zinc-500">
                    recall_bot_id:{" "}
                    <span className="font-mono">
                      {meeting.recall_bot_id ?? "-"}
                    </span>
                  </div>
                  <div className="text-xs text-zinc-500">
                    started_at: {formatDateTime(meeting.started_at)} /
                    ended_at:{" "}
                    {active ? (
                      <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-emerald-700">
                        進行中
                      </span>
                    ) : (
                      formatDateTime(meeting.ended_at)
                    )}
                  </div>
                </>
              )}
            </div>
            <div className="flex items-center gap-2">
              <a
                href={api.transcriptUrl(meetingId)}
                target="_blank"
                rel="noopener noreferrer"
              >
                <Button variant="outline" size="sm">
                  <Download className="h-4 w-4" />
                  Plain text DL
                </Button>
              </a>
              {active && meeting?.recall_bot_id && (
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => setConfirmLeave(true)}
                >
                  退出させる
                </Button>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 gap-4 text-sm">
            <div>
              <div className="text-xs text-zinc-500">utterance 数</div>
              <div className="text-2xl font-semibold tabular-nums">
                {meeting?.utterance_count ?? 0}
              </div>
            </div>
            <div>
              <div className="text-xs text-zinc-500">bot_name</div>
              <div>{meeting?.bot_name ?? "-"}</div>
            </div>
            <div>
              <div className="text-xs text-zinc-500">meeting_url</div>
              <div className="truncate text-xs text-zinc-600 dark:text-zinc-400">
                {meeting?.meeting_url ?? "-"}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex gap-1 rounded-md border border-zinc-200 p-0.5 dark:border-zinc-800">
              <button
                type="button"
                onClick={() => setTab("minutes")}
                className={`rounded px-3 py-1 text-sm transition-colors ${
                  tab === "minutes"
                    ? "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900"
                    : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50"
                }`}
              >
                議事録
              </button>
              <button
                type="button"
                onClick={() => setTab("timeline")}
                className={`rounded px-3 py-1 text-sm transition-colors ${
                  tab === "timeline"
                    ? "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900"
                    : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50"
                }`}
              >
                タイムライン
              </button>
              <button
                type="button"
                onClick={() => setTab("transcript")}
                className={`rounded px-3 py-1 text-sm transition-colors ${
                  tab === "transcript"
                    ? "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900"
                    : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50"
                }`}
              >
                文字起こし
              </button>
            </div>
            <span className="text-xs text-zinc-500">
              {tab === "minutes" &&
                `議事録 (30 秒ごと更新${
                  minutesQuery.data?.updated_at
                    ? ` · 最終 ${formatDateTime(minutesQuery.data.updated_at)}`
                    : ""
                })`}
              {tab === "timeline" &&
                `タイムライン (30 秒ごと更新 · ${
                  timelineQuery.data?.blocks?.length ?? 0
                } ブロック)`}
              {tab === "transcript" &&
                `文字起こし (5 秒ごと更新 · ${utterances.length} 件)`}
            </span>
          </div>
        </CardHeader>
        <CardContent>
          {tab === "minutes" && (
            <MinutesView
              loading={minutesQuery.isLoading}
              markdown={minutesQuery.data?.markdown ?? ""}
            />
          )}
          {tab === "timeline" && (
            <TimelineView
              loading={timelineQuery.isLoading}
              blocks={timelineQuery.data?.blocks ?? []}
            />
          )}
          {tab === "transcript" && (
            <>
              {utterancesQuery.isLoading ? (
                <div className="py-8 text-center text-sm text-zinc-500">
                  読み込み中...
                </div>
              ) : utterances.length === 0 ? (
                <div className="py-8 text-center text-sm text-zinc-500">
                  発話はまだありません
                </div>
              ) : (
                <div className="space-y-4 font-mono text-sm">
                  {utterances.map((u, i) => (
                    <div
                      key={u.utterance_id ?? `${u.timestamp}-${i}`}
                      className="border-l-2 border-zinc-200 pl-3 dark:border-zinc-800"
                    >
                      <div className="text-xs text-zinc-500">
                        [{u.timestamp}] {u.speaker || "(不明)"}:
                      </div>
                      <div className="whitespace-pre-wrap">{u.text}</div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Dialog open={confirmLeave} onOpenChange={setConfirmLeave}>
        <DialogHeader>
          <DialogTitle>会議から退出させますか?</DialogTitle>
          <DialogDescription>
            Recall API で leave_call を実行します。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => setConfirmLeave(false)}
            disabled={leave.isPending}
          >
            キャンセル
          </Button>
          <Button
            variant="destructive"
            onClick={() => {
              if (meeting?.recall_bot_id) {
                leave.mutate(meeting.recall_bot_id);
              }
            }}
            disabled={leave.isPending}
          >
            {leave.isPending ? "退出中..." : "退出させる"}
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}

function MinutesView({
  loading,
  markdown,
}: {
  loading: boolean;
  markdown: string;
}) {
  if (loading) {
    return (
      <div className="py-8 text-center text-sm text-zinc-500">
        議事録を生成中...
      </div>
    );
  }
  if (!markdown) {
    return (
      <div className="py-8 text-center text-sm text-zinc-500">
        議事録はまだ生成されていません。会議で発話があると 1〜2 分で更新されます。
      </div>
    );
  }
  return (
    <pre className="whitespace-pre-wrap rounded-md bg-zinc-50 p-4 font-sans text-sm leading-relaxed text-zinc-900 dark:bg-zinc-900 dark:text-zinc-50">
      {markdown}
    </pre>
  );
}

function TimelineView({
  loading,
  blocks,
}: {
  loading: boolean;
  blocks: import("@/lib/types").TimelineBlock[];
}) {
  if (loading) {
    return (
      <div className="py-8 text-center text-sm text-zinc-500">
        タイムラインを生成中...
      </div>
    );
  }
  if (!blocks.length) {
    return (
      <div className="py-8 text-center text-sm text-zinc-500">
        タイムラインはまだ生成されていません。会議で発話があると 1〜2 分で更新されます。
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {blocks
        .slice()
        .reverse()
        .map((b) => (
          <div
            key={b.start_iso}
            className="rounded-md border border-zinc-200 bg-white p-3 text-sm dark:border-zinc-800 dark:bg-zinc-950"
          >
            <div className="mb-1 flex items-center justify-between">
              <span className="font-mono text-xs text-zinc-500">
                {formatDateTime(b.start_iso)} 〜{" "}
                {b.end_iso.slice(11, 19)}
              </span>
              <span className="text-xs text-zinc-400">
                {b.utterance_count} 件
              </span>
            </div>
            <p className="text-sm leading-relaxed text-zinc-900 dark:text-zinc-50">
              {b.summary}
            </p>
          </div>
        ))}
    </div>
  );
}

export default function MeetingDetailPage() {
  return (
    <Suspense fallback={<div className="py-8 text-center text-sm text-zinc-500">読み込み中...</div>}>
      <MeetingDetailInner />
    </Suspense>
  );
}
