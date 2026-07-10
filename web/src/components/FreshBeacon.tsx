import { cn } from "@/lib/utils";

// The signature "fresh <48h" marker — a pulsing runway beacon. Pairs a label so
// it never relies on the animation/color alone.
export function FreshBeacon({ withLabel = false, className }: { withLabel?: boolean; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5", className)} title="Posted within 48h">
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-beacon rounded-full bg-accent" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-accent" />
      </span>
      {withLabel && (
        <span className="font-mono text-[10px] font-medium uppercase tracking-wider text-accent">
          fresh
        </span>
      )}
    </span>
  );
}
