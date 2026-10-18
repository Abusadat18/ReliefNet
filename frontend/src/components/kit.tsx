import { ChevronDownIcon, GitBranchIcon, WavesIcon } from "lucide-react";
import type { ComponentProps, ElementType, ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Urgency bands from the priority score: 85+ critical, 70+ high, 40+ medium. */
export function urgency(priority: number | null | undefined) {
  const p = priority ?? 0;
  if (priority == null) return { key: "none", text: "text-muted-foreground", bg: "bg-muted", ring: "ring-border" };
  if (p >= 85) return { key: "critical", text: "text-critical", bg: "bg-critical-soft", ring: "ring-critical" };
  if (p >= 70) return { key: "high", text: "text-high", bg: "bg-high-soft", ring: "ring-high" };
  if (p >= 40) return { key: "medium", text: "text-medium", bg: "bg-medium-soft", ring: "ring-medium" };
  return { key: "low", text: "text-low", bg: "bg-muted", ring: "ring-border" };
}

export function BrandMark({ className }: { className?: string }) {
  return (
    <span className={cn("grid size-6 shrink-0 place-items-center rounded-md bg-primary text-primary-foreground", className)}>
      <WavesIcon className="size-3.5" aria-hidden="true" />
    </span>
  );
}

/** The bracketed mono label above a heading or inside a card: "[ Shift status · live ]". */
export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("eyebrow", className)}>[ {children} ]</span>;
}

/** A heading that pairs a regular sans phrase with an italic serif accent. */
export function SerifTitle<T extends ElementType = "h2">({
  as,
  sans,
  serif,
  className,
  after = false,
  ...props
}: { as?: T; sans: ReactNode; serif: ReactNode; after?: boolean; className?: string } & Omit<ComponentProps<T>, "as">) {
  const Tag = (as ?? "h2") as ElementType;
  return (
    <Tag className={cn("font-normal tracking-tight", className)} {...props}>
      {after ? (
        <>
          <span className="accent-serif">{serif}</span> {sans}
        </>
      ) : (
        <>
          {sans} <span className="accent-serif">{serif}</span>
        </>
      )}
    </Tag>
  );
}

/** The priority number on a soft tile in its urgency colour. */
export function ScoreTile({ priority, size = "md" }: { priority: number | null | undefined; size?: "sm" | "md" }) {
  const u = urgency(priority);
  return (
    <span
      className={cn(
        "num grid shrink-0 place-items-center rounded-lg font-semibold",
        u.bg,
        u.text,
        size === "md" ? "h-12 w-11 text-xl leading-none" : "h-7 w-8 text-xs",
      )}
      aria-label={priority == null ? "Not scored yet" : `Priority ${priority}`}
    >
      <span className="flex flex-col items-center">
        {priority ?? "–"}
        {size === "md" && <span className="mt-0.5 text-[9px] font-medium tracking-wide text-muted-foreground">PRI</span>}
      </span>
    </span>
  );
}

/** A small receipt that names the graph edge a decision came from. */
export function GraphReceipt({
  edge,
  text,
  open,
  onClick,
  className,
}: {
  edge: string;
  text: string;
  open?: boolean;
  onClick?: () => void;
  className?: string;
}) {
  const body = (
    <>
      <GitBranchIcon className="size-3 text-primary" aria-hidden="true" />
      <span className="font-semibold text-primary">{edge}</span>
      <span className="truncate text-muted-foreground">{text}</span>
      {onClick && (
        <ChevronDownIcon className={cn("size-3 text-muted-foreground transition-transform", open && "rotate-180")} aria-hidden="true" />
      )}
    </>
  );
  const cls = cn(
    "num inline-flex h-[22px] max-w-full items-center gap-1.5 rounded-full border bg-background px-2 text-[10px]",
    onClick && "hover:bg-muted",
    className,
  );
  return onClick ? (
    <button type="button" className={cls} onClick={onClick} aria-expanded={open}>
      {body}
    </button>
  ) : (
    <span className={cls}>{body}</span>
  );
}

export function ErrorLine({ children }: { children: ReactNode }) {
  return (
    <p className="text-sm text-destructive" role="alert">
      {children}
    </p>
  );
}

export function ResultLine({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn("text-sm text-muted-foreground", className)}>{children}</p>;
}
