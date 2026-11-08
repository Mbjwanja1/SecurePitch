import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { roleIn } from "@/lib/club-guard";
import { createClient } from "@/lib/supabase/server";

import { RosterForm } from "./roster-form";

export const metadata: Metadata = { title: "Roster - SecurePitch" };

export default async function RosterPage({ params }: { params: Promise<{ clubId: string }> }) {
  const { clubId } = await params;
  const access = await roleIn(clubId);
  if (!access?.role) notFound();

  const supabase = await createClient();
  const { data: club } = await supabase.from("clubs").select("name").eq("id", clubId).maybeSingle();

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <Link href="/dashboard" className="text-sm text-muted-foreground hover:underline">
          &larr; Back to your clubs
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">Roster</h1>
        <p className="text-sm text-muted-foreground">{club?.name ?? "Your club"}</p>
      </div>
      {access.role === "manager" ? (
        <RosterForm clubId={clubId} />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Only the club manager can change the roster</CardTitle>
            <CardDescription>Ask your manager to add or update players.</CardDescription>
          </CardHeader>
        </Card>
      )}
    </div>
  );
}
