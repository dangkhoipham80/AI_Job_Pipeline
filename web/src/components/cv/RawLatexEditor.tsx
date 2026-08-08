import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Check, Loader2, RotateCcw, Undo2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { Button, Card, CardBody, CardHeader, CardTitle, Skeleton } from "@/components/ui";
import { cn } from "@/lib/utils";

/**
 * Hand-edit the generated LaTeX.
 *
 * The structured JSON is still the source of truth for what the CV *says*; this
 * overrules how it *serializes*, for the cases the editor has no field for — a
 * `\vspace` to pull a widow back onto page one, a macro Awesome-CV exposes that
 * the schema doesn't. That trade is one-way: nothing parses `.tex` back into
 * JSON, so while an override is in force the fields above stop reaching the PDF.
 * Hence the banner, and hence "Revert to generated" being one click.
 */
export function RawLatexEditor({
  scope,
  version,
  onSaved,
}: {
  scope: string;
  version: number;
  onSaved: () => void;
}) {
  const { data, loading, error, refetch } = useApi(() => api.cvTex(scope), [scope, version]);
  const [path, setPath] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<"save" | "reset" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Adopt the server's files whenever a new version arrives; local edits are
  // keyed by path so switching files doesn't lose them.
  useEffect(() => {
    if (!data) return;
    setDrafts(data.files);
    setPath((prev) => (prev && prev in data.files ? prev : "cv.tex"));
  }, [data]);

  const paths = useMemo(() => Object.keys(drafts).sort(sortPaths), [drafts]);
  const dirty = useMemo(
    () => !!data && paths.some((p) => drafts[p] !== data.files[p]),
    [data, drafts, paths],
  );

  if (loading && !data) return <Skeleton className="h-96" />;
  if (error || !data) {
    return (
      <Card>
        <CardBody className="text-sm text-critical">{error ?? "Could not load the LaTeX."}</CardBody>
      </Card>
    );
  }

  const current = path ?? "cv.tex";
  const text = drafts[current] ?? "";
  const generated = data.generated[current];
  const edited = generated !== undefined && text !== generated;

  async function run(what: "save" | "reset") {
    setBusy(what);
    setActionError(null);
    try {
      if (what === "save") await api.saveCvTex(scope, drafts);
      else await api.resetCvTex(scope);
      await refetch();
      onSaved();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card className="flex min-w-0 flex-col">
      <CardHeader className="items-center">
        <CardTitle>Raw LaTeX</CardTitle>
        <div className="flex items-center gap-2">
          {actionError && <span className="text-xs text-critical">{actionError}</span>}
          {data.overridden && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => run("reset")}
              disabled={busy !== null}
              title="Build from the structured document again"
            >
              {busy === "reset" ? <Loader2 size={13} className="animate-spin" /> : <RotateCcw size={13} />}
              Revert to generated
            </Button>
          )}
          <Button size="sm" onClick={() => run("save")} disabled={busy !== null || !dirty}>
            {busy === "save" ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
            Save LaTeX
          </Button>
        </div>
      </CardHeader>

      <CardBody className="flex min-w-0 flex-col gap-3 pt-3">
        <Banner overridden={data.overridden} dirty={dirty} />

        <div className="flex flex-wrap gap-1.5">
          {paths.map((p) => (
            <button
              key={p}
              onClick={() => setPath(p)}
              className={cn(
                "rounded-md border px-2 py-1 font-mono text-[11px] transition-colors",
                p === current
                  ? "border-accent/50 bg-accent/10 text-ink"
                  : "text-ink-muted hover:bg-surface-2 hover:text-ink",
              )}
            >
              {p}
              {data.generated[p] !== undefined && drafts[p] !== data.generated[p] && (
                <span className="ml-1.5 text-accent" title="Differs from the generated file">
                  ●
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Read-only while a save is in flight: the refetch that follows adopts
            the server's files, so anything typed during the round-trip would be
            overwritten the moment it lands. */}
        <CodeArea
          value={text}
          disabled={busy !== null}
          onChange={(next) => setDrafts({ ...drafts, [current]: next })}
        />

        <div className="flex items-center justify-between gap-3 text-xs text-ink-muted">
          <span className="font-mono">
            {text.split("\n").length} lines · {text.length} chars
          </span>
          {edited && (
            <button
              className="inline-flex items-center gap-1 hover:text-ink"
              onClick={() => setDrafts({ ...drafts, [current]: generated! })}
            >
              <Undo2 size={12} /> Restore this file from the document
            </button>
          )}
        </div>
      </CardBody>
    </Card>
  );
}

function Banner({ overridden, dirty }: { overridden: boolean; dirty: boolean }) {
  if (!overridden) {
    return (
      <p className="rounded-lg border bg-surface-2/60 px-3 py-2 text-xs leading-relaxed text-ink-muted">
        This is what the fields above render to. Saving it makes the build follow{" "}
        <em>this text</em> instead — useful for the things the editor has no field for.
        {dirty && <span className="ml-1 text-accent">Unsaved LaTeX edits.</span>}
      </p>
    );
  }
  return (
    <p className="flex items-start gap-2 rounded-lg border border-accent/40 bg-accent/8 px-3 py-2 text-xs leading-relaxed">
      <AlertTriangle size={14} className="mt-0.5 shrink-0 text-accent" />
      <span>
        The PDF is built from this LaTeX, not from the fields above — nothing parses{" "}
        <code className="font-mono">.tex</code> back into the structured document, so edits up
        there won't reach it until you revert. Version history keeps both.
        {dirty && <span className="ml-1 font-medium text-accent">Unsaved LaTeX edits.</span>}
      </span>
    </p>
  );
}

/**
 * Textarea with a gutter. Not a code editor: Monaco is ~5 MB for syntax colours
 * on a file you visit rarely. Tab inserts a tab instead of leaving the field,
 * because losing your place mid-macro is the one thing that makes a plain
 * textarea unusable for LaTeX.
 */
function CodeArea({
  value,
  disabled,
  onChange,
}: {
  value: string;
  disabled?: boolean;
  onChange: (next: string) => void;
}) {
  const gutter = useRef<HTMLDivElement>(null);
  const lines = value.split("\n").length;

  return (
    <div className="flex max-h-[560px] min-h-[320px] overflow-hidden rounded-lg border bg-surface-2/40 font-mono text-[12px] leading-[1.6]">
      <div
        ref={gutter}
        aria-hidden
        className="select-none overflow-hidden border-r bg-surface/60 px-2 py-2 text-right text-ink-muted/60"
      >
        {Array.from({ length: lines }, (_, i) => (
          <div key={i}>{i + 1}</div>
        ))}
      </div>
      <textarea
        value={value}
        readOnly={disabled}
        spellCheck={false}
        onScroll={(e) => {
          if (gutter.current) gutter.current.scrollTop = e.currentTarget.scrollTop;
        }}
        onKeyDown={(e) => {
          if (disabled || e.key !== "Tab" || e.shiftKey) return;
          e.preventDefault();
          const el = e.currentTarget;
          const { selectionStart: from, selectionEnd: to } = el;
          onChange(value.slice(0, from) + "  " + value.slice(to));
          requestAnimationFrame(() => el.setSelectionRange(from + 2, from + 2));
        }}
        onChange={(e) => onChange(e.target.value)}
        className="min-w-0 flex-1 resize-none bg-transparent px-3 py-2 text-ink outline-none"
      />
    </div>
  );
}

/** `cv.tex` first — it's the entry file, and the one people come here to edit. */
function sortPaths(a: string, b: string): number {
  if (a === "cv.tex") return -1;
  if (b === "cv.tex") return 1;
  return a.localeCompare(b);
}
