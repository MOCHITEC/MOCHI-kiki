import { devStore } from "@/lib/devmock/store";
import { errJson, requireAuth } from "@/lib/devmock/helpers";

export async function POST(
  _req: Request,
  ctx: { params: Promise<{ botId: string }> },
) {
  const auth = await requireAuth();
  if (!auth.ok) return auth.res;
  const { botId } = await ctx.params;
  const m = devStore.markEnded(botId);
  if (!m) {
    return errJson("meeting_not_found", "bot に対応する meeting が見つかりません", 404);
  }
  return new Response(null, { status: 202 });
}
