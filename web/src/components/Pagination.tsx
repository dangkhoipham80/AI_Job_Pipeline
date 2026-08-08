import { ChevronLeft, ChevronRight } from "lucide-react";
import { PAGE_SIZES } from "@/hooks/usePaging";
import { cn } from "@/lib/utils";

interface Props {
  page: number;
  size: number;
  total: number;
  onPage: (page: number) => void;
  onSize: (size: number) => void;
  /** What the rows are, for the range readout: "1–25 of 312 jobs". */
  noun?: string;
  className?: string;
}

/**
 * The pager: a range readout, a page-size picker, and prev/next.
 *
 * It renders even when everything fits on one page. A control that appears
 * only once a list gets long is a control nobody knows exists, and the range
 * readout is worth having on its own — "1–7 of 7" is the answer to "is this
 * everything?", which a bare list of seven rows never gives you.
 *
 * Numbered page buttons are deliberately absent. Page 6 of a job list is not a
 * place anyone means to go; the useful moves are one step either way and
 * changing how much you see at once.
 */
export function Pagination({ page, size, total, onPage, onSize, noun = "rows", className }: Props) {
  const lastPage = Math.max(0, Math.ceil(total / size) - 1);
  // Clamp for the readout only. When a list shrinks under the page you are on,
  // `useClampPage` fixes the page — but it is an effect, so it runs after this
  // paint, and the raw arithmetic would flash "51–50 of 50" for a frame.
  const shown = Math.min(page, lastPage);
  const first = total === 0 ? 0 : shown * size + 1;
  const last = Math.min(total, (shown + 1) * size);

  const step = (delta: number) => onPage(Math.min(lastPage, Math.max(0, page + delta)));

  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-between gap-3 border-t pt-3 text-sm",
        className,
      )}
    >
      <p className="tabular-nums text-muted-foreground">
        {total === 0 ? (
          <>No {noun}</>
        ) : (
          <>
            <span className="text-ink">
              {first}–{last}
            </span>{" "}
            of {total} {noun}
          </>
        )}
      </p>

      <div className="flex items-center gap-3">
        <PageSizeSelect size={size} onSize={onSize} />
        <div className="flex items-center gap-1">
          <PagerButton label="Previous page" disabled={page <= 0} onClick={() => step(-1)}>
            <ChevronLeft className="h-4 w-4" />
          </PagerButton>
          <span className="px-1 tabular-nums text-muted-foreground">
            {page + 1} / {lastPage + 1}
          </span>
          <PagerButton label="Next page" disabled={page >= lastPage} onClick={() => step(1)}>
            <ChevronRight className="h-4 w-4" />
          </PagerButton>
        </div>
      </div>
    </div>
  );
}

/** The page-size picker on its own, for surfaces that set one size across
 *  several lists — the Applications board, whose four columns share it rather
 *  than each carrying a dropdown into a quarter-width card. */
export function PageSizeSelect({
  size,
  onSize,
  label = "Per page",
}: {
  size: number;
  onSize: (size: number) => void;
  label?: string;
}) {
  return (
    <label className="flex items-center gap-1.5 text-sm text-muted-foreground">
      <span className="hidden sm:inline">{label}</span>
      <select
        value={size}
        onChange={(e) => onSize(Number(e.target.value))}
        className="rounded-lg border bg-surface px-2 py-1 text-sm text-ink"
      >
        {PAGE_SIZES.map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
      </select>
    </label>
  );
}

/**
 * Prev/next and a position, with no size picker and no range readout — what
 * fits at the foot of a narrow column.
 *
 * Renders nothing when there is only one page. That is the opposite of the
 * full `Pagination`, and on purpose: the full one earns its space by answering
 * "is this everything?" for a whole page of content, while four columns each
 * showing a disabled "1 / 1" is just noise around three cards.
 */
export function CompactPager({
  page,
  size,
  total,
  onPage,
}: {
  page: number;
  size: number;
  total: number;
  onPage: (page: number) => void;
}) {
  const lastPage = Math.max(0, Math.ceil(total / size) - 1);
  if (lastPage === 0) return null;
  const step = (delta: number) => onPage(Math.min(lastPage, Math.max(0, page + delta)));

  return (
    <div className="flex items-center justify-center gap-1 pt-1 text-xs">
      <PagerButton label="Previous page" disabled={page <= 0} onClick={() => step(-1)}>
        <ChevronLeft className="h-3.5 w-3.5" />
      </PagerButton>
      <span className="px-1 tabular-nums text-muted-foreground">
        {page + 1} / {lastPage + 1}
      </span>
      <PagerButton label="Next page" disabled={page >= lastPage} onClick={() => step(1)}>
        <ChevronRight className="h-3.5 w-3.5" />
      </PagerButton>
    </div>
  );
}

function PagerButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string;
  disabled: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "grid h-7 w-7 place-items-center rounded-lg border transition-colors",
        disabled
          ? "cursor-not-allowed text-muted-foreground/40"
          : "text-ink hover:bg-surface-2 active:bg-ink/10",
      )}
    >
      {children}
    </button>
  );
}
