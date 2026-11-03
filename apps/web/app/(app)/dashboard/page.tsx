import type { Metadata } from "next";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { createClient } from "@/lib/supabase/server";

export const metadata: Metadata = { title: "Dashboard · SecurePitch" };

const ROLE_LABEL: Record<string, string> = {
  manager: "Manager",
  treasurer: "Treasurer",
  captain: "Captain",
};

type Membership = { role: string; display_name: string; clubs: { name: string } | null };

export default async function DashboardPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  // Read with the user's own session: row-level security returns only their memberships.
  const { data, error } = await supabase
    .from("club_members")
    .select("role, display_name, clubs(name)")
    .eq("user_id", user!.id);
  const memberships = (data ?? []) as unknown as Membership[];

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Your clubs</h1>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            Couldn&apos;t load your clubs. Refresh the page; if it keeps happening, tell the
            SecurePitch team.
          </p>
        ) : memberships.length === 0 ? (
          <Card>
            <CardHeader>
              <CardTitle>You&apos;re not in a club yet</CardTitle>
              <CardDescription>
                Ask your club admin to add you. You&apos;ll see your club here once they have.
              </CardDescription>
            </CardHeader>
          </Card>
        ) : (
          <ul className="flex flex-col gap-2">
            {memberships.map((m) => (
              <li key={m.clubs?.name ?? m.role}>
                <Card>
                  <CardHeader>
                    <CardTitle>{m.clubs?.name ?? "Club"}</CardTitle>
                    <CardDescription>
                      {m.display_name} · {ROLE_LABEL[m.role] ?? m.role}
                    </CardDescription>
                  </CardHeader>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-xl font-semibold tracking-tight">Dossiers</h2>
        <Card>
          <CardHeader>
            <CardTitle>No dossiers yet</CardTitle>
            <CardDescription>
              Upload a month&apos;s M-Pesa statement to start your first sponsor dossier.
            </CardDescription>
          </CardHeader>
          <CardContent />
        </Card>
      </section>
    </div>
  );
}
