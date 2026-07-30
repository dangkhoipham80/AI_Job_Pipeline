import { useEffect, useState } from "react";
import { AlertTriangle, FileText, Loader2, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { Button, Card, CardBody, CardHeader, CardTitle } from "@/components/ui";
import { cn } from "@/lib/utils";

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

  // Re-fetch after every successful compile; `compiledAt` is the cache-buster.
  useEffect(() => {
    if (compiledAt === 0) return;
    let revoked: string | null = null;
    api
      .cvPdfUrl(scope)
      .then((next) => {
        revoked = next;
        setUrl((prev) => {
          if (prev) URL.revokeObjectURL(prev);
          return next;
        });
      })
      .catch(() => setUrl(null));
    return () => {
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [scope, compiledAt]);

  return (
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
            <iframe
              title="CV preview"
              src={`${url}#toolbar=0&view=FitH`}
              className="h-[780px] w-full rounded-lg border bg-white"
            />
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
  );
}

function Placeholder({ compiling }: { compiling: boolean }) {
  return (
    <div className="grid h-[780px] place-items-center rounded-lg border border-dashed text-center">
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
