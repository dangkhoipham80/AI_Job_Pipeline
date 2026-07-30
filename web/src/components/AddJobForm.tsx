import { useState } from "react";
import { Loader2, Plus, X } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { Button, Card, CardBody, Input } from "@/components/ui";
import type { JobDetail } from "@/types";

/**
 * Add a posting by hand.
 *
 * The way in for jobs no crawler may fetch — LinkedIn most of all, whose
 * robots.txt disallows automated access to its job pages. You find the posting,
 * paste it here, and everything downstream (tailor, review, apply) treats it
 * like any other job.
 */
export function AddJobForm({ onCreated }: { onCreated: (job: JobDetail) => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    url: "",
    title: "",
    company: "",
    location: "",
    salary: "",
    description_md: "",
  });

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [k]: e.target.value });

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const job = await api.createJob({
        url: form.url.trim(),
        title: form.title.trim(),
        company: form.company.trim(),
        location: form.location.trim() || null,
        salary: form.salary.trim() || null,
        description_md: form.description_md,
      });
      onCreated(job);
      setForm({ url: "", title: "", company: "", location: "", salary: "", description_md: "" });
      setOpen(false);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not add the job");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <Button variant="outline" onClick={() => setOpen(true)}>
        <Plus size={15} /> Add job
      </Button>
    );
  }

  return (
    <Card className="w-full">
      <CardBody className="flex flex-col gap-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="font-display text-sm font-semibold">Add a job by hand</h2>
            <p className="text-xs leading-relaxed text-ink-muted">
              For postings JobPilot can't crawl — LinkedIn's robots.txt forbids it. Paste the
              description too, or the tailor has nothing to work from.
            </p>
          </div>
          <button
            onClick={() => setOpen(false)}
            aria-label="Close"
            className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-ink-muted hover:bg-surface-2 hover:text-ink"
          >
            <X size={15} />
          </button>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <Input placeholder="Job title *" value={form.title} onChange={set("title")} />
          <Input placeholder="Company *" value={form.company} onChange={set("company")} />
          <Input placeholder="Location" value={form.location} onChange={set("location")} />
          <Input placeholder="Salary" value={form.salary} onChange={set("salary")} />
        </div>
        <Input
          placeholder="https://www.linkedin.com/jobs/view/…"
          value={form.url}
          onChange={set("url")}
        />
        <textarea
          rows={7}
          value={form.description_md}
          onChange={set("description_md")}
          placeholder="Paste the full job description here…"
          className="w-full resize-y rounded-lg border bg-surface px-3 py-2 text-sm leading-relaxed text-ink placeholder:text-ink-muted/70 focus:border-accent focus:outline-none"
        />

        <div className="flex items-center justify-between gap-3">
          <span className="text-xs text-ink-muted">
            {error ? <span className="text-critical">{error}</span> : "Applies as external — you submit it yourself."}
          </span>
          <Button onClick={submit} disabled={busy || !form.title.trim() || !form.company.trim()}>
            {busy ? <Loader2 size={15} className="animate-spin" /> : <Plus size={15} />} Add job
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}
