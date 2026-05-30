import { NextResponse } from "next/server";
import { devStore } from "@/lib/devmock/store";
import { errJson, requireAuth } from "@/lib/devmock/helpers";

export async function POST(req: Request) {
  const auth = await requireAuth();
  if (!auth.ok) return auth.res;

  let body: { meeting_url?: string; bot_name?: string; language_code?: string };
  try {
    body = await req.json();
  } catch {
    return errJson("invalid_body", "JSON 形式の body が必要です", 400);
  }
  const meetingUrl = (body.meeting_url ?? "").trim();
  if (
    !meetingUrl ||
    !(
      meetingUrl.startsWith("https://teams.microsoft.com/") ||
      meetingUrl.startsWith("https://teams.live.com/")
    )
  ) {
    return errJson(
      "invalid_meeting_url",
      "Teams 会議 URL (https://teams.microsoft.com/ または https://teams.live.com/) を指定してください",
      400,
    );
  }

  const meetingId = devStore.generateMeetingId();
  const botId = devStore.generateBotId();
  devStore.addMeeting({
    meeting_id: meetingId,
    bot_name: body.bot_name?.trim() || "MOCHI-kiki",
    meeting_url: meetingUrl,
    recall_bot_id: botId,
    started_at: new Date().toISOString(),
    ended_at: null,
    utterance_count: 0,
  });
  devStore.seedSampleUtterances(meetingId);

  return NextResponse.json(
    { meeting_id: meetingId, bot_id: botId },
    { status: 201 },
  );
}
