import { ChevronLeft } from "lucide-react";
import Link from "next/link";

export function PageHeading({
  back,
  title,
  badge,
  children,
}: {
  back?: { href: string; label: string };
  title: string;
  badge?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      {back && (
        <Link
          href={back.href}
          className="-ml-1 inline-flex min-h-10 w-fit max-w-full items-center gap-0.5 text-sm text-muted-foreground hover:text-foreground lg:min-h-6"
        >
          <ChevronLeft aria-hidden className="size-4 shrink-0" />
          <span className="truncate">{back.label}</span>
        </Link>
      )}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h1 className="text-3xl leading-tight font-bold sm:text-4xl">{title}</h1>
        {badge}
      </div>
      {children && <p className="max-w-prose text-sm text-muted-foreground">{children}</p>}
    </div>
  );
}
