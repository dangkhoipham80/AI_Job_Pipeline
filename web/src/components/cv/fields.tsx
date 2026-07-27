import { useEffect, useRef } from "react";
import { GripVertical, Plus, Trash2 } from "lucide-react";
import { Button, Input } from "@/components/ui";
import { cn } from "@/lib/utils";

/**
 * Small form primitives for the CV Studio editor. Text that ends up in the PDF
 * accepts the inline markup from jobpilot/cv/latex.py (`**bold**`, `` `tech` ``,
 * `[label](url)`) — never raw LaTeX.
 */

export function Field({
  label,
  hint,
  className,
  children,
}: {
  label: string;
  hint?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <label className={cn("flex flex-col gap-1.5", className)}>
      <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-ink-muted">
        {label}
        {hint && <span className="ml-1.5 font-normal normal-case tracking-normal opacity-70">{hint}</span>}
      </span>
      {children}
    </label>
  );
}

export function TextField({
  label,
  value,
  onChange,
  placeholder,
  hint,
  className,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  hint?: string;
  className?: string;
}) {
  return (
    <Field label={label} hint={hint} className={className}>
      <Input value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
    </Field>
  );
}

/** Textarea that grows with its content — bullets are 1–3 lines, not scroll boxes. */
export function AutoTextarea({
  value,
  onChange,
  placeholder,
  className,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);

  return (
    <textarea
      ref={ref}
      rows={1}
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      className={cn(
        "w-full resize-none rounded-lg border bg-surface px-3 py-2 text-sm leading-relaxed text-ink",
        "placeholder:text-ink-muted/70 focus:border-accent focus:outline-none",
        className,
      )}
    />
  );
}

/** Reorderable list of markup strings (CV bullet points). */
export function BulletList({
  items,
  onChange,
  addLabel = "Add bullet",
  placeholder,
}: {
  items: string[];
  onChange: (items: string[]) => void;
  addLabel?: string;
  placeholder?: string;
}) {
  const move = (i: number, delta: number) => {
    const next = [...items];
    const j = i + delta;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  };

  return (
    <div className="flex flex-col gap-2">
      {items.map((item, i) => (
        <div key={i} className="group flex items-start gap-1.5">
          <ReorderHandle
            onUp={() => move(i, -1)}
            onDown={() => move(i, 1)}
            disableUp={i === 0}
            disableDown={i === items.length - 1}
          />
          <AutoTextarea
            value={item}
            placeholder={placeholder}
            onChange={(v) => onChange(items.map((x, j) => (j === i ? v : x)))}
          />
          <IconButton
            label="Remove bullet"
            onClick={() => onChange(items.filter((_, j) => j !== i))}
            danger
          >
            <Trash2 size={14} />
          </IconButton>
        </div>
      ))}
      <Button variant="ghost" size="sm" className="self-start" onClick={() => onChange([...items, ""])}>
        <Plus size={14} /> {addLabel}
      </Button>
    </div>
  );
}

/** Comma-separated tag input for ordered lists like a tech stack. */
export function TagsField({
  label,
  value,
  onChange,
  hint,
}: {
  label: string;
  value: string[];
  onChange: (v: string[]) => void;
  hint?: string;
}) {
  return (
    <Field label={label} hint={hint ?? "comma-separated, order is kept"}>
      <Input
        value={value.join(", ")}
        placeholder="Java, Spring Boot, Docker"
        onChange={(e) =>
          onChange(
            e.target.value
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean),
          )
        }
      />
    </Field>
  );
}

export function IconButton({
  label,
  onClick,
  disabled,
  danger,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "grid h-8 w-7 shrink-0 place-items-center rounded-md text-ink-muted transition-colors",
        "hover:bg-surface-2 hover:text-ink disabled:pointer-events-none disabled:opacity-30",
        danger && "hover:bg-critical/10 hover:text-critical",
      )}
    >
      {children}
    </button>
  );
}

/** Vertical up/down pair that reads as a drag handle but stays keyboard-usable. */
export function ReorderHandle({
  onUp,
  onDown,
  disableUp,
  disableDown,
}: {
  onUp: () => void;
  onDown: () => void;
  disableUp?: boolean;
  disableDown?: boolean;
}) {
  return (
    <div className="flex shrink-0 items-center pt-1.5 text-ink-muted/40">
      <GripVertical size={14} />
      <div className="flex flex-col opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        <button
          type="button"
          aria-label="Move up"
          disabled={disableUp}
          onClick={onUp}
          className="px-0.5 text-[9px] leading-[9px] hover:text-ink disabled:opacity-25"
        >
          ▲
        </button>
        <button
          type="button"
          aria-label="Move down"
          disabled={disableDown}
          onClick={onDown}
          className="px-0.5 text-[9px] leading-[9px] hover:text-ink disabled:opacity-25"
        >
          ▼
        </button>
      </div>
    </div>
  );
}

/** Legend for the inline markup, shown once at the top of the editor. */
export function MarkupLegend() {
  return (
    <p className="text-xs leading-relaxed text-ink-muted">
      Formatting:{" "}
      <code className="rounded bg-surface-2 px-1 font-mono text-[11px]">**bold**</code>,{" "}
      <code className="rounded bg-surface-2 px-1 font-mono text-[11px]">`accent`</code>,{" "}
      <code className="rounded bg-surface-2 px-1 font-mono text-[11px]">[label](url)</code>. Everything
      else is escaped — no LaTeX needed.
    </p>
  );
}
