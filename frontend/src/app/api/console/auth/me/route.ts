import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/devmock/helpers";

export async function GET() {
  const auth = await requireAuth();
  if (!auth.ok) return auth.res;
  return NextResponse.json({ username: auth.username });
}
