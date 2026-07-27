import { Card, CardBody, CardHeader, CardTitle, Input } from "@/components/ui";
import { Field, TextField } from "@/components/cv/fields";
import type { CvHeader, CvTheme } from "@/types";

// Awesome-CV's built-in accent colours, plus whatever hex the user types.
const THEME_COLORS = [
  "awesome-red",
  "awesome-emerald",
  "awesome-skyblue",
  "awesome-pink",
  "awesome-orange",
  "awesome-nephritis",
  "awesome-concrete",
  "awesome-darknight",
];

export function HeaderEditor({
  header,
  theme,
  onHeader,
  onTheme,
}: {
  header: CvHeader;
  theme: CvTheme;
  onHeader: (h: CvHeader) => void;
  onTheme: (t: CvTheme) => void;
}) {
  const set = <K extends keyof CvHeader>(key: K, value: CvHeader[K]) =>
    onHeader({ ...header, [key]: value });
  const opt = (key: keyof CvHeader) => (v: string) => set(key, (v || null) as never);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Identity</CardTitle>
      </CardHeader>
      <CardBody className="grid grid-cols-2 gap-4 pt-3">
        <TextField label="First name" value={header.first_name} onChange={(v) => set("first_name", v)} />
        <TextField label="Last name" value={header.last_name} onChange={(v) => set("last_name", v)} />
        <TextField
          label="Position"
          value={header.position}
          onChange={(v) => set("position", v)}
          className="col-span-2"
        />
        <TextField label="Email" value={header.email ?? ""} onChange={opt("email")} />
        <TextField label="Mobile" value={header.mobile ?? ""} onChange={opt("mobile")} />
        <TextField label="GitHub" value={header.github ?? ""} onChange={opt("github")} hint="username" />
        <TextField
          label="LinkedIn"
          value={header.linkedin ?? ""}
          onChange={opt("linkedin")}
          hint="username"
        />
        <TextField
          label="Address"
          value={header.address ?? ""}
          onChange={opt("address")}
          hint="optional"
          className="col-span-2"
        />

        <Field label="Extra link" hint="label + url, shown next to the home icon" className="col-span-2">
          <div className="flex gap-2">
            <Input
              className="w-40"
              placeholder="Portfolio"
              value={header.extra_info?.label ?? ""}
              onChange={(e) =>
                set(
                  "extra_info",
                  e.target.value || header.extra_info?.url
                    ? { label: e.target.value, url: header.extra_info?.url ?? "" }
                    : null,
                )
              }
            />
            <Input
              placeholder="https://…"
              value={header.extra_info?.url ?? ""}
              onChange={(e) =>
                set(
                  "extra_info",
                  e.target.value || header.extra_info?.label
                    ? { label: header.extra_info?.label ?? "", url: e.target.value }
                    : null,
                )
              }
            />
          </div>
        </Field>

        <Field label="Accent colour" hint="Awesome-CV name or #hex" className="col-span-2">
          <div className="flex flex-wrap items-center gap-1.5">
            {THEME_COLORS.map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => onTheme({ ...theme, color: c })}
                className={
                  "rounded-md border px-2 py-1 font-mono text-[11px] transition-colors " +
                  (theme.color === c
                    ? "border-accent bg-accent/12 text-ink"
                    : "text-ink-muted hover:bg-surface-2 hover:text-ink")
                }
              >
                {c.replace("awesome-", "")}
              </button>
            ))}
            <Input
              className="ml-1 w-28 font-mono text-[11px]"
              placeholder="#ca63a8"
              value={theme.color.startsWith("#") ? theme.color : ""}
              onChange={(e) => onTheme({ ...theme, color: e.target.value || "awesome-red" })}
            />
          </div>
        </Field>
      </CardBody>
    </Card>
  );
}
