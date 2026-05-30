"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { LogOut } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/meetings", label: "会議一覧" },
  { href: "/bots/new", label: "Bot 投入" },
];

export function Nav() {
  const pathname = usePathname();
  const router = useRouter();

  const { data: me } = useQuery({
    queryKey: ["me"],
    queryFn: () => api.me(),
    retry: false,
  });

  const logout = useMutation({
    mutationFn: () => api.logout(),
    onSuccess: () => {
      toast.success("ログアウトしました");
      router.push("/login");
      router.refresh();
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : "ログアウトに失敗しました";
      toast.error(msg);
    },
  });

  return (
    <header className="sticky top-0 z-40 border-b border-zinc-200 bg-white/80 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/80">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4">
        <Link href="/meetings" className="font-semibold tracking-tight">
          MOCHI-kiki
          <span className="ml-2 text-xs font-normal text-zinc-500">
            管理コンソール
          </span>
        </Link>
        <nav className="flex items-center gap-1">
          {navItems.map((item) => {
            const active =
              pathname === item.href || pathname.startsWith(item.href + "/");
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm transition-colors",
                  active
                    ? "bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-50"
                    : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50",
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          {me?.username && (
            <span className="text-xs text-zinc-500">{me.username}</span>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => logout.mutate()}
            disabled={logout.isPending}
          >
            <LogOut className="h-4 w-4" />
            <span className="hidden sm:inline">ログアウト</span>
          </Button>
        </div>
      </div>
    </header>
  );
}
