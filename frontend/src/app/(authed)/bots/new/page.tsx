"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const TEAMS_URL = /^https:\/\/teams\.(microsoft|live)\.com\//i;

const schema = z.object({
  meeting_url: z
    .string()
    .min(1, "会議 URL は必須です")
    .refine(
      (v) => TEAMS_URL.test(v),
      "https://teams.microsoft.com/ または https://teams.live.com/ で始まる URL を入力してください",
    ),
  bot_name: z.string().max(64).optional().or(z.literal("")),
  language_code: z.enum(["ja", "en"]),
});

type FormValues = z.infer<typeof schema>;

export default function NewBotPage() {
  const router = useRouter();
  const [confirmOpen, setConfirmOpen] = React.useState(false);
  const [pending, setPending] = React.useState<FormValues | null>(null);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      meeting_url: "",
      bot_name: "MOCHI-kiki",
      language_code: "ja",
    },
  });

  const mutation = useMutation({
    mutationFn: (values: FormValues) =>
      api.createBot({
        meeting_url: values.meeting_url,
        bot_name: values.bot_name?.trim() || undefined,
        language_code: values.language_code,
      }),
    onSuccess: (res) => {
      toast.success(
        `Bot を投入しました (bot_id: ${res.bot_id} / meeting_id: ${res.meeting_id})`,
      );
      setConfirmOpen(false);
      router.push(`/meetings/${encodeURIComponent(res.meeting_id)}`);
    },
    onError: (err) => {
      const msg =
        err instanceof ApiError ? err.message : "Bot の投入に失敗しました";
      toast.error(msg);
    },
  });

  const onSubmit = (values: FormValues) => {
    setPending(values);
    setConfirmOpen(true);
  };

  const onConfirm = () => {
    if (pending) mutation.mutate(pending);
  };

  return (
    <div className="mx-auto max-w-2xl">
      <Card>
        <CardHeader>
          <CardTitle>Bot を会議に投入</CardTitle>
          <CardDescription>
            Teams 会議 URL を指定して MOCHI-kiki bot を呼び出します。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={form.handleSubmit(onSubmit)}
            className="flex flex-col gap-4"
          >
            <div className="flex flex-col gap-2">
              <Label htmlFor="meeting_url">会議 URL (必須)</Label>
              <Input
                id="meeting_url"
                placeholder="https://teams.microsoft.com/l/meetup-join/..."
                {...form.register("meeting_url")}
              />
              {form.formState.errors.meeting_url && (
                <p className="text-sm text-red-600">
                  {form.formState.errors.meeting_url.message}
                </p>
              )}
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor="bot_name">Bot 名 (任意)</Label>
              <Input
                id="bot_name"
                placeholder="MOCHI-kiki"
                {...form.register("bot_name")}
              />
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor="language_code">言語</Label>
              <Select
                id="language_code"
                {...form.register("language_code")}
              >
                <option value="ja">日本語 (ja)</option>
                <option value="en">英語 (en)</option>
              </Select>
            </div>

            <div className="flex justify-end">
              <Button type="submit" disabled={mutation.isPending}>
                会議に投入
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogHeader>
          <DialogTitle>投入を実行しますか?</DialogTitle>
          <DialogDescription>
            指定した Teams 会議に bot を入室させます。
          </DialogDescription>
        </DialogHeader>
        {pending && (
          <div className="space-y-2 rounded-md border border-zinc-200 bg-zinc-50 p-3 text-xs dark:border-zinc-800 dark:bg-zinc-900">
            <div className="break-all">
              <span className="text-zinc-500">URL: </span>
              {pending.meeting_url}
            </div>
            <div>
              <span className="text-zinc-500">Bot 名: </span>
              {pending.bot_name?.trim() || "MOCHI-kiki"}
            </div>
            <div>
              <span className="text-zinc-500">言語: </span>
              {pending.language_code}
            </div>
          </div>
        )}
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => setConfirmOpen(false)}
            disabled={mutation.isPending}
          >
            キャンセル
          </Button>
          <Button onClick={onConfirm} disabled={mutation.isPending}>
            {mutation.isPending ? "投入中..." : "投入する"}
          </Button>
        </DialogFooter>
      </Dialog>
    </div>
  );
}
