"use client";

import * as React from "react";
import Link from "next/link";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import type { Meeting } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { formatDateTime } from "@/lib/utils";

const PAGE_SIZE = 50;

export default function MeetingsPage() {
  const qc = useQueryClient();

  const query = useInfiniteQuery({
    queryKey: ["meetings"],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      api.listMeetings({ limit: PAGE_SIZE, before: pageParam }),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  const [leaveTarget, setLeaveTarget] = React.useState<Meeting | null>(null);

  const leave = useMutation({
    mutationFn: (botId: string) => api.leaveBot(botId),
    onSuccess: () => {
      toast.success("退出を要求しました");
      setLeaveTarget(null);
      qc.invalidateQueries({ queryKey: ["meetings"] });
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : "退出に失敗しました";
      toast.error(msg);
    },
  });

  const meetings = query.data?.pages.flatMap((p) => p.meetings) ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">会議一覧</h1>
          <p className="text-sm text-zinc-500">
            投入済みの bot / 過去の会議を確認できます。
          </p>
        </div>
        <Link href="/bots/new">
          <Button>＋ Bot を投入</Button>
        </Link>
      </div>

      {query.isLoading ? (
        <div className="rounded-lg border border-zinc-200 bg-white p-8 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-950">
          読み込み中...
        </div>
      ) : query.isError ? (
        <div className="rounded-lg border border-red-300 bg-red-50 p-8 text-center text-sm text-red-700">
          取得に失敗しました
        </div>
      ) : meetings.length === 0 ? (
        <div className="rounded-lg border border-zinc-200 bg-white p-8 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-950">
          会議はまだありません。「Bot を投入」から開始してください。
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-zinc-50 text-left text-xs uppercase text-zinc-500 dark:bg-zinc-900">
                <tr>
                  <th className="px-4 py-3 font-medium">meeting_id</th>
                  <th className="px-4 py-3 font-medium">bot_name</th>
                  <th className="px-4 py-3 font-medium">recall_bot_id</th>
                  <th className="px-4 py-3 font-medium">started_at</th>
                  <th className="px-4 py-3 font-medium">ended_at</th>
                  <th className="px-4 py-3 font-medium text-right">utterance</th>
                  <th className="px-4 py-3 font-medium">アクション</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                {meetings.map((m) => {
                  const active = !m.ended_at;
                  return (
                    <tr key={m.meeting_id}>
                      <td className="max-w-[12rem] truncate px-4 py-3 font-mono text-xs">
                        <Link
                          href={`/meetings/${encodeURIComponent(m.meeting_id)}`}
                          className="hover:underline"
                        >
                          {m.meeting_id}
                        </Link>
                      </td>
                      <td className="px-4 py-3">{m.bot_name ?? "-"}</td>
                      <td className="max-w-[10rem] truncate px-4 py-3 font-mono text-xs">
                        {m.recall_bot_id ?? "-"}
                      </td>
                      <td className="px-4 py-3 text-zinc-600 dark:text-zinc-400">
                        {formatDateTime(m.started_at)}
                      </td>
                      <td className="px-4 py-3 text-zinc-600 dark:text-zinc-400">
                        {active ? (
                          <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-700">
                            進行中
                          </span>
                        ) : (
                          formatDateTime(m.ended_at)
                        )}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {m.utterance_count}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <Link
                            href={`/meetings/${encodeURIComponent(m.meeting_id)}`}
                          >
                            <Button variant="outline" size="sm">
                              詳細
                            </Button>
                          </Link>
                          {active && m.recall_bot_id && (
                            <Button
                              variant="destructive"
                              size="sm"
                              onClick={() => setLeaveTarget(m)}
                            >
                              退出させる
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {query.hasNextPage && (
        <div className="flex justify-center">
          <Button
            variant="outline"
            onClick={() => query.fetchNextPage()}
            disabled={query.isFetchingNextPage}
          >
            {query.isFetchingNextPage ? "読み込み中..." : "さらに読み込む"}
          </Button>
        </div>
      )}

      <Dialog
        open={!!leaveTarget}
        onOpenChange={(open) => {
          if (!open) setLeaveTarget(null);
        }}
      >
        <DialogHeader>
          <DialogTitle>会議から退出させますか?</DialogTitle>
          <DialogDescription>
            Recall API で leave_call を実行します。
          </DialogDescription>
        </DialogHeader>
        {leaveTarget && (
          <div className="space-y-1 rounded-md border border-zinc-200 bg-zinc-50 p-3 text-xs dark:border-zinc-800 dark:bg-zinc-900">
            <div>
              <span className="text-zinc-500">meeting_id: </span>
              <span className="font-mono">{leaveTarget.meeting_id}</span>
            </div>
            <div>
              <span className="text-zinc-500">recall_bot_id: </span>
              <span className="font-mono">{leaveTarget.recall_bot_id}</span>
            </div>
          </div>
        )}
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => setLeaveTarget(null)}
            disabled={leave.isPending}
          >
            キャンセル
          </Button>
          <Button
            variant="destructive"
            onClick={() => {
              if (leaveTarget?.recall_bot_id) {
                leave.mutate(leaveTarget.recall_bot_id);
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
