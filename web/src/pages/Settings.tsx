import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Check, Loader2, Save, ShieldAlert } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { Button, Card, CardBody, CardHeader, CardTitle, Input, Skeleton } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { Settings as SettingsData } from "@/types";

/**
 * Settings (PLAN.md §5.6). Saves land in a gitignored overlay merged over
 * config.yaml, so the commented defaults — which document the email safety
 * gates — are never rewritten by a form.
 *
 * Each card saves only its own section, so a half-finished edit in one place
 * can't clobber another.
 */
export function Settings() {
  const { data, loading, error, refetch } = useApi(() => api.settings(), []);
  const [draft, setDraft] = useState<SettingsData | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (data) setDraft(structuredClone(data));
  }, [data]);

  const save = useCallback(
    async (section: keyof SettingsData) => {
      if (!draft) return;
      setSaving(section);
      setSaveError(null);
      try {
        await api.saveSettings({ [section]: draft[section] } as Partial<SettingsData>);
        await refetch();
        setSaved(section);
        setTimeout(() => setSaved(null), 2000);
      } catch (e) {
        setSaveError(e instanceof ApiError ? e.message : "Save failed");
      } finally {
        setSaving(null);
      }
    },
    [draft, refetch],
  );

  if (error) {
    return (
      <Card className="p-6 text-sm">
        <span className="font-medium text-critical">Couldn't load settings.</span> {error}
      </Card>
    );
  }
  if (loading && !draft) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-40 rounded-card" />
        <Skeleton className="h-56 rounded-card" />
      </div>
    );
  }
  if (!draft) return null;

  const set = (patch: Partial<SettingsData>) => setDraft({ ...draft, ...patch });

  return (
    <div className="animate-fade-up space-y-4">
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-ink-muted">
          Saved to <code className="font-mono text-xs">config.local.yaml</code>, merged over the
          commented defaults. Delete that file to reset.
        </p>
      </div>

      {saveError && (
        <Card className="flex items-start gap-2 border-critical/40 bg-critical/5 p-3 text-sm">
          <AlertTriangle size={15} className="mt-0.5 shrink-0 text-critical" />
          <span>{saveError}</span>
        </Card>
      )}

      <Section
        title="Crawl"
        onSave={() => save("crawl")}
        saving={saving === "crawl"}
        saved={saved === "crawl"}
      >
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <NumberField
            label="Jobs per site"
            value={draft.crawl.jobs_per_site}
            onChange={(v) => set({ crawl: { ...draft.crawl, jobs_per_site: v } })}
          />
          <NumberField
            label="Max pages per site"
            hint="a ceiling, not a target"
            value={draft.crawl.max_pages}
            onChange={(v) => set({ crawl: { ...draft.crawl, max_pages: v } })}
          />
          <NumberField
            label="Fresh window (hours)"
            hint="🔥 flag below this age"
            value={draft.crawl.fresh_hours}
            onChange={(v) => set({ crawl: { ...draft.crawl, fresh_hours: v } })}
          />
          <NumberField
            label="Min match score"
            step={0.05}
            value={draft.crawl.match_score_min}
            onChange={(v) => set({ crawl: { ...draft.crawl, match_score_min: v } })}
          />
        </div>
        <TagField
          label="Stacks"
          hint="what a good job looks like"
          value={draft.crawl.stacks}
          onChange={(stacks) => set({ crawl: { ...draft.crawl, stacks } })}
        />
        <TagField
          label="Exclude keywords"
          hint="drop jobs whose title or JD matches"
          value={draft.crawl.exclude_keywords}
          onChange={(exclude_keywords) => set({ crawl: { ...draft.crawl, exclude_keywords } })}
        />
      </Section>

      <Section
        title="Sources"
        onSave={() => save("sources")}
        saving={saving === "sources"}
        saved={saved === "sources"}
      >
        <div className="flex flex-col gap-1.5">
          {draft.sources.map((source, i) => (
            <label
              key={source.key}
              className="flex items-center gap-3 rounded-lg border px-3 py-2 text-sm"
            >
              <input
                type="checkbox"
                checked={source.enabled}
                onChange={(e) =>
                  set({
                    sources: draft.sources.map((s, j) =>
                      j === i ? { ...s, enabled: e.target.checked } : s,
                    ),
                  })
                }
                className="h-4 w-4 accent-[rgb(var(--accent))]"
              />
              <span className="font-medium">{source.key}</span>
              <span className="font-mono text-[11px] text-ink-muted">tier {source.tier}</span>
            </label>
          ))}
        </div>
      </Section>

      <Section
        title="Apply — email"
        onSave={() => save("apply")}
        saving={saving === "apply"}
        saved={saved === "apply"}
        danger={draft.apply.email.enabled && !draft.apply.email.dry_run && !draft.apply.email.test_recipient}
      >
        <GateWarning email={draft.apply.email} />
        <div className="flex flex-col gap-1.5">
          <Toggle
            label="Enabled"
            hint="nothing is sent at all while this is off"
            checked={draft.apply.email.enabled}
            onChange={(enabled) =>
              set({ apply: { ...draft.apply, email: { ...draft.apply.email, enabled } } })
            }
          />
          <Toggle
            label="Dry run"
            hint="build and record the message, never send it"
            checked={draft.apply.email.dry_run}
            onChange={(dry_run) =>
              set({ apply: { ...draft.apply, email: { ...draft.apply.email, dry_run } } })
            }
          />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label="Test recipient"
            hint="deliver here instead of employers"
            value={draft.apply.email.test_recipient}
            onChange={(test_recipient) =>
              set({ apply: { ...draft.apply, email: { ...draft.apply.email, test_recipient } } })
            }
          />
          <TextField
            label="From address"
            value={draft.apply.email.from_addr}
            onChange={(from_addr) =>
              set({ apply: { ...draft.apply, email: { ...draft.apply.email, from_addr } } })
            }
          />
        </div>
        <p className="text-xs text-ink-muted">
          SMTP credentials live in <code className="font-mono">.env</code>, not here.
        </p>
      </Section>

      <Section
        title="CV"
        onSave={() => save("app")}
        saving={saving === "app"}
        saved={saved === "app"}
      >
        <NumberField
          label="Max edit rounds"
          hint="how many times you can ask the agent to revise one CV"
          value={draft.app.edit_max_rounds}
          onChange={(v) => set({ app: { ...draft.app, edit_max_rounds: v } })}
        />
      </Section>
    </div>
  );
}

function GateWarning({ email }: { email: SettingsData["apply"]["email"] }) {
  if (!email.enabled)
    return (
      <p className="rounded-lg border border-good/30 bg-good/5 px-3 py-2 text-xs text-ink-muted">
        Email apply is off. Nothing can be sent.
      </p>
    );
  if (email.dry_run)
    return (
      <p className="rounded-lg border border-good/30 bg-good/5 px-3 py-2 text-xs text-ink-muted">
        Dry run: messages are built and shown on the Applications board, never sent.
      </p>
    );
  if (email.test_recipient)
    return (
      <p className="rounded-lg border border-accent/40 bg-accent/8 px-3 py-2 text-xs text-ink-muted">
        Live, but every message goes to{" "}
        <span className="font-mono text-ink">{email.test_recipient}</span> instead of the employer.
      </p>
    );
  return (
    <p className="flex items-start gap-2 rounded-lg border border-critical/40 bg-critical/8 px-3 py-2 text-xs text-critical">
      <ShieldAlert size={14} className="mt-0.5 shrink-0" />
      <span>
        All three gates are open — approved applications will be emailed to real employers from{" "}
        {email.from_addr || "(no from address set)"}.
      </span>
    </p>
  );
}

/* Primitives ---------------------------------------------------------------- */
function Section({
  title,
  children,
  onSave,
  saving,
  saved,
  danger,
}: {
  title: string;
  children: React.ReactNode;
  onSave: () => void;
  saving: boolean;
  saved: boolean;
  danger?: boolean;
}) {
  return (
    <Card className={cn(danger && "border-l-2 border-l-critical")}>
      <CardHeader className="items-center">
        <CardTitle>{title}</CardTitle>
        <Button size="sm" variant="outline" onClick={onSave} disabled={saving}>
          {saving ? (
            <Loader2 size={14} className="animate-spin" />
          ) : saved ? (
            <Check size={14} className="text-good" />
          ) : (
            <Save size={14} />
          )}
          {saved ? "Saved" : "Save"}
        </Button>
      </CardHeader>
      <CardBody className="flex flex-col gap-4 pt-3">{children}</CardBody>
    </Card>
  );
}

function Label({ label, hint }: { label: string; hint?: string }) {
  return (
    <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-ink-muted">
      {label}
      {hint && <span className="ml-1.5 font-normal normal-case tracking-normal opacity-70">{hint}</span>}
    </span>
  );
}

function NumberField({
  label,
  hint,
  value,
  step = 1,
  onChange,
}: {
  label: string;
  hint?: string;
  value: number;
  step?: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <Label label={label} hint={hint} />
      <Input
        type="number"
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  );
}

function TextField({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint?: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <Label label={label} hint={hint} />
      <Input value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

function TagField({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint?: string;
  value: string[];
  onChange: (v: string[]) => void;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <Label label={label} hint={hint ?? "comma-separated"} />
      <Input
        value={value.join(", ")}
        onChange={(e) =>
          onChange(
            e.target.value
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean),
          )
        }
      />
    </label>
  );
}

function Toggle({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-3 rounded-lg border px-3 py-2 text-sm">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 accent-[rgb(var(--accent))]"
      />
      <span className="font-medium">{label}</span>
      {hint && <span className="text-xs text-ink-muted">{hint}</span>}
    </label>
  );
}
