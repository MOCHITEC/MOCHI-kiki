"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const q = useQuery({
    queryKey: ["me"],
    queryFn: () => api.me(),
    retry: false,
  });

  useEffect(() => {
    if (q.isError) {
      const err = q.error;
      if (err instanceof ApiError && err.status === 401) {
        router.replace("/login");
      }
    }
  }, [q.isError, q.error, router]);

  if (q.isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-zinc-500">
        読み込み中...
      </div>
    );
  }
  if (!q.data) return null;
  return <>{children}</>;
}
