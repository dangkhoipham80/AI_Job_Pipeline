import { useEffect, useState } from "react";
import { AlertTriangle, Check, Loader2, PenSquare } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { Button, Card, CardBody, CardHeader, CardTitle } from "@/components/ui";
import { titleCase } from "@/lib/format";
import type { JobDetail } from "@/types";

/**
 * The job description, editable in place.
 *
 * LinkedIn Job Alert emails announce a job but not its text, and JobPilot won't
 * fetch the posting (robots.txt forbids it). So a job can arrive with nothing to
 * tailor against — this is where you paste it in, and it's called out loudly
 * rather than letting the tailor run on an empty JD and produce noise.
 */
export function JobDescription({ job, onSaved }: { job: JobDetail; onSaved: () => void }) {
  const empty = !job.description_md.trim();
  const [editing, setEditing] = useState(empty);
  const [draft, setDraft] = useState(job.description_md);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDraft(job.description_md);
    setEditing(!job.description_md.trim());
  }, [job.id, job.description_md]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.patchJob(job.id, { description_md: draft });
      onSaved();
      setEditing(false);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader className="items-center">
        <CardTitle>Job description</CardTitle>
        <div className="flex items-center gap-3">
          {job.apply_channel && (
            <span className="text-xs text-ink-muted">
              applies via {titleCase(job.apply_channel)}
            </span>
          )}
          {!editing && (
            <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>
              <PenSquare size={13} /> Edit
            </Button>
          )}
        </div>
      </CardHeader>
      <CardBody>
        {empty && !editing && (
          <p className="mb-3 flex items-start gap-2 rounded-lg border border-accent/40 bg-accent/8 px-3 py-2 text-xs leading-relaxed">
            <AlertTriangle size={14} className="mt-0.5 shrink-0 text-accent" />
            <span>
              No description yet. Tailoring without one produces a generic CV — open the posting,
              copy the description, and paste it here first.
            </span>
          </p>
        )}

        {editing ? (
          <div className="flex flex-col gap-2">
            <textarea
              rows={14}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Paste the full job description…"
              className="w-full resize-y rounded-lg border bg-surface px-3 py-2 font-sans text-sm leading-relaxed text-ink placeholder:text-ink-muted/70 focus:border-accent focus:outline-none"
            />
            <div className="flex items-center justify-end gap-2">
              {error && <span className="mr-auto text-xs text-critical">{error}</span>}
              {!empty && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setDraft(job.description_md);
                    setEditing(false);
                  }}
                >
                  Cancel
                </Button>
              )}
              <Button size="sm" onClick={save} disabled={busy || !draft.trim()}>
                {busy ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />} Save
              </Button>
            </div>
          </div>
        ) : (
          <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-ink/90">
            {job.description_md}
          </pre>
        )}
      </CardBody>
    </Card>
  );
}
