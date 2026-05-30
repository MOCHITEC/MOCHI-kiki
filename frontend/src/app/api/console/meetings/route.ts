import { NextResponse } from "next/server";
import { devStore } from "@/lib/devmock/store";
import { requireAuth } from "@/lib/devmock/helpers";

export async function GET(req: Request) {
  const auth = await requireAuth();
  if (!auth.ok) return auth.res;
  const url = new URL(req.url);
  const limit = Math.max(
    1,
    Math.min(200, parseInt(url.searchParams.get("limit") ?? "50", 10) || 50),
  );
  const before = url.searchParams.get("before") ?? undefined;
  const list = devStore.listMeetings(limit, before).map((m) => ({
    ...m,
    utterance_count: devStore.countUtterances(m.meeting_id),
  }));
  const next_cursor =
    list.length >= limit ? list[list.length - 1].started_at ?? null : null;
  return NextResponse.json({ meetings: list, next_cursor });
}
