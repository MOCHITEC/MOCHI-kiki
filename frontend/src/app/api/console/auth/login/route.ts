import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { devStore } from "@/lib/devmock/store";
import { MOCK_COOKIE, errJson } from "@/lib/devmock/helpers";

export async function POST(req: Request) {
  let body: { username?: string; password?: string };
  try {
    body = await req.json();
  } catch {
    return errJson("invalid_body", "JSON 形式の body が必要です", 400);
  }
  const username = (body.username ?? "").trim();
  const password = body.password ?? "";
  if (!username || !password) {
    return errJson("invalid_body", "username と password は必須です", 400);
  }
  if (
    username !== devStore.expectedUser ||
    password !== devStore.expectedPassword
  ) {
    return errJson("unauthorized", "ユーザ名またはパスワードが違います", 401);
  }
  const token = devStore.issueToken(username);
  const res = NextResponse.json({ username });
  (await cookies()).set(MOCK_COOKIE, token, {
    httpOnly: true,
    secure: false,
    sameSite: "strict",
    path: "/",
    maxAge: 12 * 60 * 60,
  });
  return res;
}
