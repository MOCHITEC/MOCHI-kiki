import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { devStore } from "./store";

export const MOCK_COOKIE = "mochi_session";

export function errJson(code: string, message: string, status: number) {
  return NextResponse.json(
    { error: { code, message } },
    { status },
  );
}

export async function requireAuth(): Promise<
  { ok: true; username: string } | { ok: false; res: NextResponse }
> {
  const c = await cookies();
  const token = c.get(MOCK_COOKIE)?.value;
  const user = devStore.verifyToken(token);
  if (!user) {
    return {
      ok: false,
      res: errJson("unauthorized", "認証が必要です", 401),
    };
  }
  return { ok: true, username: user };
}
