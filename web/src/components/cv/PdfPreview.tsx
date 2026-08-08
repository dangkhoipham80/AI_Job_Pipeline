import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  AlertTriangle,
  ExternalLink,
  FileText,
  Loader2,
  Maximize2,
  RefreshCw,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button, Card, CardBody, CardHeader, CardTitle } from "@/components/ui";
import { cn } from "@/lib/utils";

/** A4, the page size awesome-cv.cls sets. Drives the frame height. */
const PAGE_RATIO = 210 / 297;

/**
 * The viewer's own padding, measured against Chrome's built-in one at
 * `view=FitH`: ~4px each side, ~3px above the first page, ~4px between pages.
 * It fits the page to the width *inside* that padding, so ignoring it and using
 * a bare A4 ratio over-estimates the page height — which is what left a band of
 * the viewer's dark background under the CV.
 *
 * Other engines pad differently, so the estimate is deliberately biased 2px
 * short and the frame clips whatever is left: worst case we cut 2px off a page
 * margin that is 1.5cm of whitespace, instead of showing a dark stripe.
 */
const INSET_X = 4;
const INSET_TOP = 3;
const PAGE_GAP = 4;
const BIAS = 2;

/** Frame height that ends where the last page ends. */
function frameHeight(width: number, pages: number): number {
  const count = Math.max(1, pages);
  const pageHeight = (width - INSET_X * 2) / PAGE_RATIO;
  return Math.round(pageHeight * count + PAGE_GAP * (count - 1) + INSET_TOP - BIAS);
}

/** Element width, kept current across layout changes (rail resize, zoom). */
function useWidth<T extends HTMLElement>(): [(el: T | null) => void, number] {
  const [width, setWidth] = useState(0);
  const observer = useRef<ResizeObserver | null>(null);
  const ref = useCallback((el: T | null) => {
    observer.current?.disconnect();
    if (!el) return;
    setWidth(el.clientWidth);
    observer.current = new ResizeObserver(([entry]) =>
      setWidth(entry.contentRect.width),
    );
    observer.current.observe(el);
  }, []);
  useEffect(() => () => observer.current?.disconnect(), []);
  return [ref, width];
}

/**
 * Compile-on-demand PDF preview. The `<iframe>` can't attach the API token, so
 * the PDF is fetched as a blob and shown via an object URL (revoked on swap).
 */
export function PdfPreview({
  scope,
  dirty,
  compiling,
  pages,
  error,
  compiledAt,
  onCompile,
}: {
  scope: string;
  dirty: boolean;
  compiling: boolean;
  pages: number | null;
  error: string | null;
  compiledAt: number;
  onCompile: () => void;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [frameRef, width] = useWidth<HTMLDivElement>();
  const [full, setFull] = useState(false);
  // Stable: the overlay keys its key/scroll-lock effect off this, and an inline
  // arrow would tear it down and rebuild it on every parent render — which the
  // ResizeObserver above causes on any window resize.
  const closeFull = useCallback(() => setFull(false), []);

  // Fetch on mount as well as after every compile — a build survives a reload,
  // and an empty pane next to a CV that is already on disk reads as "broken".
  // `compiledAt` is the cache-buster for subsequent builds.
  //
  // The old object URL is revoked only once its replacement has arrived. The
  // previous version revoked it on effect *cleanup*, i.e. the moment a compile
  // started, which left the frame pointing at a dead blob for the seconds the
  // build takes — the pane kept showing the stale page and sometimes went blank.
  const live = useRef<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .cvPdfUrl(scope)
      .then((next) => {
        if (cancelled) return URL.revokeObjectURL(next);
        if (live.current) URL.revokeObjectURL(live.current);
        live.current = next;
        setUrl(next);
      })
      .catch(() => {
        if (!cancelled) setUrl(null);
      });
    return () => {
      cancelled = true;
    };
  }, [scope, compiledAt]);

  // Only on unmount: while mounted the URL above is still on screen.
  useEffect(
    () => () => {
      if (live.current) URL.revokeObjectURL(live.current);
    },
    [],
  );

  const frame = (
    <div
      ref={frameRef}
      className="w-full overflow-hidden rounded-lg border bg-white"
      style={{ height: width ? frameHeight(width, pages ?? 1) : undefined }}
    >
      {url && (
        // Taller than its frame on purpose — the overflow is the viewer's
        // trailing background, and clipping it is the only way to hide it.
        <iframe
          title="CV preview"
          src={`${url}#toolbar=0&view=FitH`}
          className="w-full"
          style={{ height: width ? frameHeight(width, pages ?? 1) + 48 : "100%" }}
        />
      )}
    </div>
  );

  return (
    <>
      <Card className="flex flex-col overflow-hidden">
        <CardHeader className="items-center">
          <CardTitle>Preview</CardTitle>
          <div className="flex items-center gap-2">
            {pages !== null && !error && (
              <span
                className={cn(
                  "rounded-md border px-2 py-0.5 font-mono text-[11px]",
                  pages === 1 ? "border-good/40 text-good" : "border-critical/40 text-critical",
                )}
                title={pages === 1 ? "Fits on one page" : "A CV should fit on one page"}
              >
                {pages} page{pages === 1 ? "" : "s"}
              </span>
            )}
            {url && !error && (
              <>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-8 px-2"
                  title="Full screen"
                  onClick={() => setFull(true)}
                >
                  <Maximize2 size={14} />
                </Button>
                <a
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                  title="Open in a new tab"
                  className="grid h-8 w-8 place-items-center rounded-lg text-ink-muted hover:bg-surface-2 hover:text-ink"
                >
                  <ExternalLink size={14} />
                </a>
              </>
            )}
            <Button size="sm" variant="outline" onClick={onCompile} disabled={compiling}>
              {compiling ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
              {compiling ? "Compiling…" : "Compile"}
            </Button>
          </div>
        </CardHeader>

        <CardBody className="flex-1 pt-3">
          {error ? (
            <div className="flex h-full flex-col gap-2 rounded-lg border border-critical/40 bg-critical/5 p-3">
              <div className="flex items-center gap-2 text-sm font-medium text-critical">
                <AlertTriangle size={15} /> LaTeX build failed
              </div>
              <pre className="max-h-72 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-ink-muted">
                {error}
              </pre>
            </div>
          ) : url ? (
            <>
              {frame}
              {dirty && (
                <p className="pt-2 text-xs text-ink-muted">
                  Showing the last compiled build — save and compile to see your edits.
                </p>
              )}
            </>
          ) : (
            <Placeholder compiling={compiling} />
          )}
        </CardBody>
      </Card>

      {full && url && <FullScreen url={url} onClose={closeFull} />}
    </>
  );
}

/**
 * The rail is too narrow to read a CV in, so this is where you actually look at
 * one: the page gets the whole window height and the viewer fits it vertically.
 */
function FullScreen({ url, onClose }: { url: string; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    const { overflow } = document.body.style;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);

  // Portalled to <body>. Rendered in place it lives inside the rail's `sticky`
  // subtree, and the sticky app header then sits above it in paint order — the
  // backdrop looked right but the Close button was unclickable, which is how
  // Playwright found it ("<header …> intercepts pointer events").
  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="CV preview, full screen"
      className="fixed inset-0 z-50 flex flex-col bg-black/80 backdrop-blur-sm"
      onClick={onClose}
    >
      <div className="flex items-center justify-between px-4 py-2 text-white">
        <span className="font-display text-sm font-semibold uppercase tracking-[0.14em]">
          CV preview
        </span>
        <button
          onClick={onClose}
          aria-label="Close preview"
          className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-sm hover:bg-white/10"
        >
          <X size={15} /> Close <kbd className="font-mono text-xs opacity-70">Esc</kbd>
        </button>
      </div>
      {/* Sized to the page rather than to the window: at `FitV` the viewer fits
          the page to the height, so a wider frame would just be more of its own
          background. stopPropagation keeps a click on the document from
          dismissing it. */}
      <iframe
        title="CV preview, full screen"
        src={`${url}#toolbar=0&view=FitV`}
        onClick={(e) => e.stopPropagation()}
        style={{ aspectRatio: `${PAGE_RATIO}` }}
        className="mx-auto mb-4 h-full min-h-0 w-auto rounded-lg bg-white shadow-2xl"
      />
    </div>,
    document.body,
  );
}

function Placeholder({ compiling }: { compiling: boolean }) {
  return (
    <div className="grid aspect-[210/297] place-items-center rounded-lg border border-dashed text-center">
      <div className="flex flex-col items-center gap-2 text-ink-muted">
        {compiling ? (
          <Loader2 size={22} className="animate-spin" />
        ) : (
          <FileText size={22} className="opacity-60" />
        )}
        <p className="text-sm">
          {compiling ? "Running xelatex in Docker…" : "Hit Compile to render the PDF."}
        </p>
        {!compiling && (
          <p className="max-w-xs text-xs leading-relaxed opacity-80">
            Needs Docker running — the build uses the Awesome-CV image.
          </p>
        )}
      </div>
    </div>
  );
}
