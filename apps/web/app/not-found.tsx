import Link from "next/link";

import { Brand } from "@/components/brand";

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-4 px-4 py-12">
      <Brand />
      <h1 className="text-3xl font-bold">We can&apos;t find that page</h1>
      <p className="text-sm text-muted-foreground">
        If you followed a dossier link or QR code, check that you have the whole address. A dossier
        only appears here once its club has sealed it.
      </p>
      <Link href="/login" className="w-fit py-2 text-sm font-medium underline underline-offset-4">
        Club officials: sign in
      </Link>
    </main>
  );
}
