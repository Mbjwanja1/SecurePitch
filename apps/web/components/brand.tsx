import { cn } from "@/lib/utils";

/** The crest from the dossier PDF and the app icon, with the product name beside it. */
export function Brand({ inverted = false, className }: { inverted?: boolean; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <span
        aria-hidden
        className={cn(
          "grid size-8 place-items-center border-2 font-heading text-sm leading-none font-bold tracking-wide",
          inverted ? "border-seal text-pitch-foreground" : "border-primary text-primary",
        )}
      >
        SP
      </span>
      <span className="font-heading text-xl leading-none font-bold tracking-wide">SecurePitch</span>
    </span>
  );
}
