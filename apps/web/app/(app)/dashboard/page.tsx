import type { Metadata } from "next";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export const metadata: Metadata = { title: "Dashboard · SecurePitch" };

export default function DashboardPage() {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-semibold tracking-tight">Dossiers</h1>
      <Card>
        <CardHeader>
          <CardTitle>No dossiers yet</CardTitle>
          <CardDescription>
            Upload a month&apos;s M-Pesa statement to start your first sponsor dossier. Statement
            upload arrives on Day 3.
          </CardDescription>
        </CardHeader>
        <CardContent />
      </Card>
    </div>
  );
}
