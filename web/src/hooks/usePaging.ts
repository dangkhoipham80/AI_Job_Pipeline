import { useCallback, useEffect, useState } from "react";

/** The page sizes offered in every pager. */
export const PAGE_SIZES = [10, 25, 50, 100] as const;

export const DEFAULT_PAGE_SIZE = 25;

const KEY = (name: string) => `jobpilot-page-size:${name}`;

function storedSize(name: string): number {
  try {
    const raw = Number(localStorage.getItem(KEY(name)));
    // Validate against the offered sizes rather than trusting the string. A
    // hand-edited or stale value would otherwise go straight into a query the
    // server caps at 200 and rejects with a 422 — an unreadable page for
    // something the user never typed.
    return (PAGE_SIZES as readonly number[]).includes(raw) ? raw : DEFAULT_PAGE_SIZE;
  } catch {
    return DEFAULT_PAGE_SIZE;
  }
}

/**
 * Page position for one list, with the size remembered per list.
 *
 * Per list, not global: the Jobs table wants 100 rows and the run history wants
 * 10, and forcing one number on both means whichever you set last is wrong
 * somewhere. `name` is the storage key, so it has to be stable and unique —
 * the four Applications columns each pass their own.
 *
 * `offset` is derived from `page`, never stored, so the two can't disagree.
 */
export function usePaging(name: string) {
  const [size, setSizeState] = useState(() => storedSize(name));
  const [page, setPage] = useState(0);

  // Remember the choice, not the position. Where you were in a list is a fact
  // about one visit; how much of it you like to see at once is a preference.
  const setSize = useCallback(
    (next: number) => {
      setSizeState(next);
      setPage(0); // page 4 of 10-row pages is nowhere in 100-row pages.
      try {
        localStorage.setItem(KEY(name), String(next));
      } catch {
        /* private mode — the size just won't persist */
      }
    },
    [name],
  );

  return {
    page,
    size,
    offset: page * size,
    setSize,
    setPage,
    /** Back to the first page — call when a *filter* changes, not when the
     *  data merely refreshes. Staying on page 7 of a search that now has two
     *  results shows an empty table and no hint why. */
    reset: useCallback(() => setPage(0), []),
  };
}

/**
 * Clamp the current page back into range when the list shrinks under it.
 *
 * A realtime push, a crawl finishing, or another tab deleting rows can all cut
 * a list short while you are looking at its last page. Without this the pager
 * sits on an empty page with working "previous" — technically recoverable, but
 * it reads as data loss.
 */
export function useClampPage(
  total: number | undefined,
  { page, size, setPage }: { page: number; size: number; setPage: (n: number) => void },
) {
  useEffect(() => {
    if (total === undefined) return;
    const last = Math.max(0, Math.ceil(total / size) - 1);
    if (page > last) setPage(last);
  }, [total, page, size, setPage]);
}
