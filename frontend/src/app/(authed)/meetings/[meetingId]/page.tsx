"use client";

import * as React from "react";
import Link from "next/link";
import { use } from "react";
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

interface PageProps {
  params: Promise<{ meetingId: string }>;
}

export default function MeetingDetailPage({ params }: PageProps) {
  const { meetingId } = use(params);
  const qc = useQueryClient();

  const meetingQuery = useQuery({
    queryKey: ["meeting", meetingId],
    queryFn: () => api.getMeeting(meetingId),
    refetchInterval: 5000,
  });

  const utterancesQuery = useQuery({
    queryKey: ["utterances", meetingId],
    queryFn: () => api.listUtterances(meetingId, { limit: 1000 }),
    refetchInterval: 5000,
  });

  const [confirmLeave, setConfirmLeave] = React.useState(false);

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
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">文字起こし</h2>
            <span className="text-xs text-zinc-500">
              5 秒ごとに自動更新 ({utterances.length} 件)
            </span>
          </div>
        </CardHeader>
        <CardContent>
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
