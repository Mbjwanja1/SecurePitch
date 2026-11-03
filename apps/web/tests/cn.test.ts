// Pins how cn() resolves Tailwind class conflicts. Expected values are what the standard
// shadcn helper, twMerge(clsx(...)) from tailwind-merge 3, returns for the same inputs, so a
// cn upgrade that diverges from it fails here.
import { describe, expect, it } from "vitest";

import { cn } from "@/lib/utils";

const sorted = (s: string) => s.split(" ").filter(Boolean).sort();

describe("cn() class conflict resolution", () => {
  it.each([
    ["later utility wins", ["text-base", "text-lg"], "text-lg"],
    ["responsive variant is kept", ["text-base md:text-sm", "text-lg"], "md:text-sm text-lg"],
    ["responsive variant overridden", ["text-base md:text-sm", "md:text-lg"], "text-base md:text-lg"],
    ["padding axis only", ["px-2 py-1", "px-4"], "py-1 px-4"],
    ["shorthand then axis", ["p-4", "px-2"], "p-4 px-2"],
    ["theme colours", ["text-muted-foreground", "text-destructive"], "text-destructive"],
    ["arbitrary values", ["w-full", "w-[42px]"], "w-[42px]"],
    ["border width vs colour", ["border border-input", "border-2"], "border-input border-2"],
    ["conditionals", ["h-9", false, { "h-12": true }], "h-12"],
  ])("%s", (_name, args, expected) => {
    expect(sorted(cn(...(args as Parameters<typeof cn>)))).toEqual(sorted(expected as string));
  });

  it("lets <Input className='text-lg'> override the default text size", () => {
    const out = cn("h-9 w-full text-base md:text-sm", "text-lg").split(" ");
    expect(out).toContain("text-lg");
    expect(out).not.toContain("text-base");
  });
});
