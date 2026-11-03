import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { createClient } from "@/lib/supabase/server";

export const metadata: Metadata = { title: "Dashboard · SecurePitch" };

const ROLE_LABEL: Record<string, string> = {
  manager: "Manager",
  treasurer: "Treasurer",
  captain: "Captain",
};

type Membership = {
  club_id: string;
  role: string;
  display_name: string;
  clubs: { name: string } | null;
};

type DossierRow = {
  id: string;
  status: string;
  period_from: string;
  period_to: string;
  clubs: { name: string } | null;
};

const STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  submitted: "Waiting for approval",
  approved: "Approved",
  sealed: "Sealed",
  revoked: "Revoked",
};

export default async function DashboardPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  // The layout checks too, but this is a separate getUser() call: if the session expired in
  // between (or Supabase was briefly unreachable), send them to sign in instead of crashing.
  if (!user) redirect("/login?next=/dashboard");

  // Read with the user's own session: row-level security returns only their memberships.
  const { data, error } = await supabase
    .from("club_members")
    .select("club_id, role, display_name, clubs(name)")
    .eq("user_id", user.id);
  const memberships = (data ?? []) as unknown as Membership[];
  const { data: dossierData, error: dossierError } = await supabase
    .from("dossiers")
    .select("id, status, period_from, period_to, clubs(name)")
    .order("created_at", { ascending: false })
    .limit(20);
  const dossiers = (dossierData ?? []) as unknown as DossierRow[];
  const managed = memberships.filter((m) => m.role === "manager");

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
              <li key={m.club_id}>
                <Card>
                  <CardHeader>
                    <CardTitle>{m.clubs?.name ?? "Club"}</CardTitle>
                    <CardDescription>
                      {m.display_name} · {ROLE_LABEL[m.role] ?? m.role}
                    </CardDescription>
                  </CardHeader>
                  {m.role === "manager" && (
                    <CardContent>
                      <Link
                        href={`/club/${m.club_id}/statements/new`}
                        className={buttonVariants({ size: "sm" })}
                      >
                        Upload a statement
                      </Link>
                    </CardContent>
                  )}
                </Card>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-xl font-semibold tracking-tight">Dossiers</h2>
        {dossierError ? (
          <p role="alert" className="text-sm text-destructive">
            Couldn&apos;t load dossiers. Refresh the page.
          </p>
        ) : dossiers.length === 0 ? (
          <Card>
            <CardHeader>
              <CardTitle>No dossiers yet</CardTitle>
              <CardDescription>
                {managed.length > 0
                  ? "Upload a month's M-Pesa statement to start your first sponsor dossier."
                  : "Your club manager starts each dossier by uploading the month's statement."}
              </CardDescription>
            </CardHeader>
          </Card>
        ) : (
          <ul className="flex flex-col divide-y rounded-xl border">
            {dossiers.map((d) => (
              <li key={d.id}>
                <Link
                  href={`/dossiers/${d.id}`}
                  className="flex items-center justify-between gap-3 p-3 text-sm hover:bg-muted/50"
                >
                  <span>
                    <span className="font-medium">
                      {d.period_from} to {d.period_to}
                    </span>
                    {memberships.length > 1 && d.clubs && (
                      <span className="text-muted-foreground"> · {d.clubs.name}</span>
                    )}
                  </span>
                  <span className="text-muted-foreground">{STATUS_LABEL[d.status] ?? d.status}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
