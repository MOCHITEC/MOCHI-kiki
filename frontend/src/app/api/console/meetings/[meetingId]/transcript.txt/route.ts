import { devStore } from "@/lib/devmock/store";
import { errJson, requireAuth } from "@/lib/devmock/helpers";

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ meetingId: string }> },
) {
  const auth = await requireAuth();
  if (!auth.ok) return auth.res;
  const { meetingId } = await ctx.params;
  if (!devStore.getMeeting(meetingId)) {
    return errJson("meeting_not_found", "meeting が見つかりません", 404);
  }
  const lines = devStore
    .listUtterances(meetingId)
    .map((u) => `[${u.timestamp}] ${u.speaker || "(不明)"}:\n    ${u.text}`);
  const body = lines.length ? lines.join("\n") + "\n" : "";
  return new Response(body, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Content-Disposition": `attachment; filename="${meetingId}.txt"`,
    },
  });
}
