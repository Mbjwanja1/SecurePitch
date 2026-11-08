"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";

type Row = {
  date: string;
  coach: string;
  sponsor?: string; // no sponsor line: a personal row, which never leaves the coach
  category?: string;
  amount: string;
  balance: string;
};

// Made-up rows, to show what the real engine does to a statement.
const ROWS: Row[] = [
  { date: "3 Oct", coach: "Funds received from Community Sports Trust", sponsor: "From Paybill 400200", category: "Income", amount: "+40,000", balance: "52,300" },
  { date: "5 Oct", coach: "Sent to Mum", amount: "−3,000", balance: "49,300" },
  { date: "9 Oct", coach: "Paid to Sports Kit Ltd", sponsor: "Till 5123456", category: "Kit", amount: "−12,000", balance: "37,300" },
  { date: "12 Oct", coach: "KPLC prepaid tokens", amount: "−1,500", balance: "35,800" },
  { date: "17 Oct", coach: "Sent to Grace Akinyi", sponsor: "Player P01", category: "Transport", amount: "−250", balance: "35,550" },
  { date: "17 Oct", coach: "Sent to Mary Wanjiru", sponsor: "Player P02", category: "Transport", amount: "−250", balance: "35,300" },
  { date: "20 Oct", coach: "Supermarket", amount: "−2,340", balance: "32,960" },
];

const VIEWS = [
  { key: false, label: "Coach's statement" },
  { key: true, label: "Sponsor's dossier" },
];

// The idea in one tap: the same statement, and what's left of it once it's a dossier.
export function StatementDemo() {
  const [sponsor, setSponsor] = useState(false);
  const shown = ROWS.filter((r) => r.sponsor).length;

  return (
    <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
      <div className="flex gap-1 border-b bg-muted/60 p-1.5" role="group" aria-label="Whose view">
        {VIEWS.map((v) => (
          <button
            key={v.label}
            type="button"
            aria-pressed={sponsor === v.key}
            onClick={() => setSponsor(v.key)}
            className={cn(
              "h-10 flex-1 rounded-lg text-sm font-medium transition-colors duration-200",
              sponsor === v.key
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {v.label}
          </button>
        ))}
      </div>

      <ul>
        {ROWS.map((r, i) => {
          const hidden = sponsor && !r.sponsor;
          return (
            <li
              key={i}
              aria-hidden={hidden}
              className={cn(
                "grid transition-[grid-template-rows,opacity] duration-300 ease-out",
                hidden ? "grid-rows-[0fr] opacity-0" : "grid-rows-[1fr] opacity-100",
              )}
            >
              <div className="min-h-0 overflow-hidden">
                <div className="flex items-center justify-between gap-3 border-b px-4 py-2.5 text-sm">
                  <div className="min-w-0">
                    <p className="truncate font-medium">{sponsor ? r.sponsor : r.coach}</p>
                    <p className="text-xs text-muted-foreground">
                      {r.date}
                      {sponsor && r.category && ` · ${r.category}`}
                    </p>
                  </div>
                  <div className="shrink-0 text-right tabular-nums">
                    <p className={r.amount.startsWith("+") ? "text-success" : ""}>KES {r.amount}</p>
                    {!sponsor && (
                      <p className="text-xs text-muted-foreground">Balance {r.balance}</p>
                    )}
                  </div>
                </div>
              </div>
            </li>
          );
        })}
      </ul>

      <p aria-live="polite" className="px-4 py-3 text-xs text-muted-foreground">
        {sponsor
          ? `${shown} club payments shown. ${ROWS.length - shown} personal payments, every name and the balance stay with the coach.`
          : "Everything on the coach's personal M-Pesa line, mixed together. Switch views to see what a sponsor gets."}
      </p>
    </div>
  );
}
