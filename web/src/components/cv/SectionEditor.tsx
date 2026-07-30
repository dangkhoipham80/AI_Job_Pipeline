import { useState } from "react";
import { ChevronDown, ChevronRight, Eye, EyeOff, Plus, Trash2 } from "lucide-react";
import { Button, Card, Input } from "@/components/ui";
import { AutoTextarea, BulletList, IconButton, ReorderHandle, TagsField, TextField } from "@/components/cv/fields";
import { cn } from "@/lib/utils";
import type { CvEducationEntry, CvEntry, CvSection } from "@/types";

const EMPTY_ENTRY: CvEntry = { title: "", date: "", url: null, items: [], role: null, tech_stack: [] };
const EMPTY_EDUCATION: CvEducationEntry = {
  degree: "",
  institution: "",
  location: "",
  date: "",
  items: [],
};

const TYPE_LABEL: Record<CvSection["type"], string> = {
  paragraph: "Paragraph",
  bullets: "Bullets",
  education: "Education",
  experience: "Experience",
  projects: "Projects",
};

function summarize(section: CvSection): string {
  switch (section.type) {
    case "paragraph":
      return `${section.text.trim().split(/\s+/).filter(Boolean).length} words`;
    case "bullets":
      return `${section.items.length} item${section.items.length === 1 ? "" : "s"}`;
    default:
      return `${section.entries.length} entr${section.entries.length === 1 ? "y" : "ies"}`;
  }
}

export function SectionEditor({
  section,
  onChange,
  onRemove,
  onMove,
  disableUp,
  disableDown,
}: {
  section: CvSection;
  onChange: (s: CvSection) => void;
  onRemove: () => void;
  onMove: (delta: number) => void;
  disableUp: boolean;
  disableDown: boolean;
}) {
  // Collapsed by default: six expanded sections make the page ~10,000px tall,
  // which hides the one thing this screen is for — seeing the CV's shape. The
  // collapsed header carries the title, type and item count, so you can tell
  // where to click without opening anything.
  const [open, setOpen] = useState(false);

  return (
    <Card className={cn("group", !section.enabled && "opacity-55")}>
      <div className="flex items-center gap-1 px-3 py-2.5">
        <ReorderHandle
          onUp={() => onMove(-1)}
          onDown={() => onMove(1)}
          disableUp={disableUp}
          disableDown={disableDown}
        />
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
          <span className="truncate font-display text-sm font-semibold">{section.title || section.key}</span>
          <span className="shrink-0 rounded border px-1.5 py-px font-mono text-[10px] uppercase tracking-wide text-ink-muted">
            {TYPE_LABEL[section.type]}
          </span>
          <span className="shrink-0 text-xs text-ink-muted">{summarize(section)}</span>
        </button>
        <IconButton
          label={section.enabled ? "Hide from PDF" : "Show in PDF"}
          onClick={() => onChange({ ...section, enabled: !section.enabled })}
        >
          {section.enabled ? <Eye size={15} /> : <EyeOff size={15} />}
        </IconButton>
        <IconButton label="Delete section" onClick={onRemove} danger>
          <Trash2 size={15} />
        </IconButton>
      </div>

      {open && (
        <div className="flex flex-col gap-4 border-t px-5 py-4">
          <div className="grid grid-cols-2 gap-4">
            <TextField
              label="Section title"
              value={section.title}
              onChange={(v) => onChange({ ...section, title: v })}
            />
            <TextField
              label="Key"
              hint="file name"
              value={section.key}
              onChange={(v) => onChange({ ...section, key: v })}
            />
          </div>
          <SectionBody section={section} onChange={onChange} />
        </div>
      )}
    </Card>
  );
}

function SectionBody({
  section,
  onChange,
}: {
  section: CvSection;
  onChange: (s: CvSection) => void;
}) {
  switch (section.type) {
    case "paragraph":
      return (
        <AutoTextarea
          value={section.text}
          placeholder="A short professional summary…"
          onChange={(text) => onChange({ ...section, text })}
        />
      );

    case "bullets":
      return (
        <div className="flex flex-col gap-2">
          {section.items.map((item, i) => (
            <div key={i} className="group flex items-start gap-1.5">
              <Input
                className="w-44 shrink-0"
                placeholder="Label (optional)"
                value={item.label ?? ""}
                onChange={(e) =>
                  onChange({
                    ...section,
                    items: section.items.map((x, j) =>
                      j === i ? { ...x, label: e.target.value || null } : x,
                    ),
                  })
                }
              />
              <AutoTextarea
                value={item.text}
                placeholder="Java, Spring Boot, Docker"
                onChange={(text) =>
                  onChange({
                    ...section,
                    items: section.items.map((x, j) => (j === i ? { ...x, text } : x)),
                  })
                }
              />
              <Input
                className="w-32 shrink-0"
                placeholder="Date"
                value={item.date ?? ""}
                onChange={(e) =>
                  onChange({
                    ...section,
                    items: section.items.map((x, j) =>
                      j === i ? { ...x, date: e.target.value || null } : x,
                    ),
                  })
                }
              />
              <IconButton
                label="Remove item"
                danger
                onClick={() => onChange({ ...section, items: section.items.filter((_, j) => j !== i) })}
              >
                <Trash2 size={14} />
              </IconButton>
            </div>
          ))}
          <Button
            variant="ghost"
            size="sm"
            className="self-start"
            onClick={() =>
              onChange({ ...section, items: [...section.items, { label: null, text: "", date: null }] })
            }
          >
            <Plus size={14} /> Add item
          </Button>
        </div>
      );

    case "education":
      return (
        <EntryList
          entries={section.entries}
          empty={EMPTY_EDUCATION}
          addLabel="Add education"
          onChange={(entries) => onChange({ ...section, entries })}
          render={(entry, set) => (
            <>
              <div className="grid grid-cols-2 gap-4">
                <TextField label="Degree" value={entry.degree} onChange={(v) => set({ degree: v })} />
                <TextField
                  label="Institution"
                  value={entry.institution}
                  onChange={(v) => set({ institution: v })}
                />
                <TextField label="Location" value={entry.location} onChange={(v) => set({ location: v })} />
                <TextField
                  label="Date"
                  hint="use -- for the dash"
                  value={entry.date}
                  onChange={(v) => set({ date: v })}
                />
              </div>
              <BulletList items={entry.items} onChange={(items) => set({ items })} />
            </>
          )}
        />
      );

    case "experience":
    case "projects":
      return (
        <EntryList
          entries={section.entries}
          empty={EMPTY_ENTRY}
          addLabel={section.type === "projects" ? "Add project" : "Add role"}
          onChange={(entries) => onChange({ ...section, entries } as CvSection)}
          render={(entry, set) => (
            <>
              <div className="grid grid-cols-2 gap-4">
                <TextField
                  label="Title"
                  value={entry.title}
                  onChange={(v) => set({ title: v })}
                  className="col-span-2"
                />
                <TextField
                  label="Date"
                  hint="use -- for the dash"
                  value={entry.date}
                  onChange={(v) => set({ date: v })}
                />
                <TextField
                  label="Link"
                  hint="optional"
                  value={entry.url ?? ""}
                  onChange={(v) => set({ url: v || null })}
                />
              </div>
              <BulletList items={entry.items} onChange={(items) => set({ items })} />
              <div className="grid grid-cols-3 gap-4">
                <TextField
                  label="Role"
                  hint="optional"
                  value={entry.role ?? ""}
                  onChange={(v) => set({ role: v || null })}
                />
                <TagsField
                  label="Tech stack"
                  value={entry.tech_stack}
                  onChange={(tech_stack) => set({ tech_stack })}
                />
              </div>
            </>
          )}
        />
      );
  }
}

/** Reorderable list of entry cards, shared by education/experience/projects. */
function EntryList<T>({
  entries,
  empty,
  addLabel,
  onChange,
  render,
}: {
  entries: T[];
  empty: T;
  addLabel: string;
  onChange: (entries: T[]) => void;
  render: (entry: T, set: (patch: Partial<T>) => void) => React.ReactNode;
}) {
  const move = (i: number, delta: number) => {
    const next = [...entries];
    const j = i + delta;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  };

  return (
    <div className="flex flex-col gap-3">
      {entries.map((entry, i) => (
        <div key={i} className="group flex items-start gap-1.5 rounded-lg border bg-surface-2/60 p-3">
          <ReorderHandle
            onUp={() => move(i, -1)}
            onDown={() => move(i, 1)}
            disableUp={i === 0}
            disableDown={i === entries.length - 1}
          />
          <div className="flex min-w-0 flex-1 flex-col gap-3">
            {render(entry, (patch) =>
              onChange(entries.map((x, j) => (j === i ? { ...x, ...patch } : x))),
            )}
          </div>
          <IconButton
            label="Remove entry"
            danger
            onClick={() => onChange(entries.filter((_, j) => j !== i))}
          >
            <Trash2 size={14} />
          </IconButton>
        </div>
      ))}
      <Button
        variant="ghost"
        size="sm"
        className="self-start"
        onClick={() => onChange([...entries, structuredClone(empty)])}
      >
        <Plus size={14} /> {addLabel}
      </Button>
    </div>
  );
}
