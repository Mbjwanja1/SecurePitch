import { KeyRound } from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Brand } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { createClient } from "@/lib/supabase/server";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  // The middleware already redirects; this guards against a misconfigured matcher.
  if (!user) redirect("/login");

  return (
    <div className="min-h-dvh">
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-2.5">
          <Link href="/dashboard" aria-label="SecurePitch: your clubs" className="inline-flex min-h-10 shrink-0 items-center">
            <Brand />
          </Link>
          <form action="/auth/signout" method="post" className="flex min-w-0 items-center gap-1 sm:gap-3">
            <span className="hidden min-w-0 truncate text-sm text-muted-foreground lg:inline">
              {user.email}
            </span>
            <Link
              href="/settings/passkeys"
              className="inline-flex min-h-10 items-center gap-1.5 rounded-md px-2 text-sm hover:bg-muted lg:min-h-8"
            >
              <KeyRound aria-hidden className="size-4 text-muted-foreground" />
              Passkeys
            </Link>
            <Button type="submit" variant="outline" size="sm">
              Sign out
            </Button>
          </form>
        </div>
      </header>
      {/* Pages are a readable column unless they ask for the full width (data-wide). */}
      <main className="mx-auto max-w-5xl px-4 py-6 sm:py-8 [&>*:not([data-wide])]:mx-auto [&>*:not([data-wide])]:max-w-3xl">
        {children}
      </main>
    </div>
  );
}
