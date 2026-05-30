import { NextResponse } from "next/server";
import { devStore } from "@/lib/devmock/store";
import { errJson, requireAuth } from "@/lib/devmock/helpers";

export async function GET(
  req: Request,
  ctx: { params: Promise<{ meetingId: string }> },
) {
  const auth = await requireAuth();
  if (!auth.ok) return auth.res;
  const { meetingId } = await ctx.params;
  if (!devStore.getMeeting(meetingId)) {
    return errJson("meeting_not_found", "meeting が見つかりません", 404);
  }
  const since = new URL(req.url).searchParams.get("since") ?? undefined;
  return NextResponse.json({
    utterances: devStore.listUtterances(meetingId, since),
  });
}
