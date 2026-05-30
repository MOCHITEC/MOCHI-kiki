import { NextResponse } from "next/server";
import { devStore } from "@/lib/devmock/store";
import { errJson, requireAuth } from "@/lib/devmock/helpers";

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ meetingId: string }> },
) {
  const auth = await requireAuth();
  if (!auth.ok) return auth.res;
  const { meetingId } = await ctx.params;
  const m = devStore.getMeeting(meetingId);
  if (!m) return errJson("meeting_not_found", "meeting が見つかりません", 404);
  return NextResponse.json({
    ...m,
    utterance_count: devStore.countUtterances(meetingId),
  });
}
