import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { roleIn } from "@/lib/club-guard";
import { createClient } from "@/lib/supabase/server";

import { StatementTagger } from "./statement-tagger";

export const metadata: Metadata = { title: "Upload statement · SecurePitch" };

export default async function NewStatementPage({
  params,
}: {
  params: Promise<{ clubId: string }>;
}) {
  const { clubId } = await params;
  const access = await roleIn(clubId);
  // Not a UUID, signed out, or not a member: row-level security hides the club either way.
  if (!access?.role) notFound();

  const supabase = await createClient();
  const { data: club } = await supabase.from("clubs").select("name").eq("id", clubId).maybeSingle();

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <Link href="/dashboard" className="text-sm text-muted-foreground hover:underline">
          ← {club?.name ?? "Your clubs"}
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">Upload a statement</h1>
      </div>
      {access.role === "manager" ? (
        <StatementTagger clubId={clubId} />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Only the manager uploads statements</CardTitle>
            <CardDescription>
              The club manager tags the month&apos;s M-Pesa statement. You&apos;ll review the
              draft dossier once they&apos;ve saved it.
            </CardDescription>
          </CardHeader>
        </Card>
      )}
    </div>
  );
}
