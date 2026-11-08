import { Check } from "lucide-react";

import { stepsDone } from "@/lib/dossier-progress";
import { cn } from "@/lib/utils";

const STEPS = ["Draft", "Manager signs", "Treasurer signs", "Sealed"];

// A dossier always moves through the same four steps, so show where this one has got to.
export function DossierProgress({ status }: { status: string }) {
  const done = stepsDone(status);
  return (
    <ol aria-label="Dossier progress" className="grid grid-cols-4 gap-2">
      {STEPS.map((step, i) => {
        const finished = i < done;
        const current = i === done;
        return (
          <li
            key={step}
            aria-current={current ? "step" : undefined}
            className="flex min-w-0 flex-col gap-1.5"
          >
            <span
              aria-hidden
              className={cn("h-1 rounded-full", finished ? "bg-primary" : current ? "bg-primary/35" : "bg-border")}
            />
            <span
              className={cn(
                "flex items-start gap-1 text-xs leading-tight",
                finished || current ? "font-medium text-foreground" : "text-muted-foreground",
              )}
            >
              {finished && <Check aria-hidden className="mt-px size-3 shrink-0 text-success" />}
              {step}
              {finished && <span className="sr-only"> (done)</span>}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
