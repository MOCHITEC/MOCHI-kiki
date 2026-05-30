import { cookies } from "next/headers";
import { MOCK_COOKIE } from "@/lib/devmock/helpers";

export async function POST() {
  (await cookies()).delete(MOCK_COOKIE);
  return new Response(null, { status: 204 });
}
