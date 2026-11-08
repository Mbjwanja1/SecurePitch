import { cn } from "@/lib/utils";

const STATUS: Record<string, { label: string; className: string }> = {
  draft: { label: "Draft", className: "bg-muted text-muted-foreground" },
  submitted: { label: "Waiting for the treasurer", className: "bg-warning-soft text-warning" },
  approved: { label: "Approved, not sealed", className: "bg-warning-soft text-warning" },
  sealed: { label: "Sealed", className: "bg-success-soft text-success" },
  revoked: { label: "Revoked", className: "bg-destructive/10 text-destructive" },
};

export function StatusBadge({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status, className: "bg-muted text-muted-foreground" };
  return (
    <span
      className={cn(
        "inline-flex w-fit items-center rounded-md px-2 py-0.5 text-xs font-medium",
        s.className,
      )}
    >
      {s.label}
    </span>
  );
}
