import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { Plus, Save } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { Button, Card, CardBody, Select, Skeleton } from "@/components/ui";
import { AtsPanel } from "@/components/cv/AtsPanel";
import { MarkupLegend } from "@/components/cv/fields";
import { HeaderEditor } from "@/components/cv/HeaderEditor";
import { PdfPreview } from "@/components/cv/PdfPreview";
import { SectionEditor } from "@/components/cv/SectionEditor";
import { VersionHistory } from "@/components/cv/VersionHistory";
import type { AtsReport, CvDocument, CvSection, CvSectionType } from "@/types";

const NEW_SECTION: Record<CvSectionType, () => CvSection> = {
  paragraph: () => ({ type: "paragraph", key: "summary", title: "Summary", enabled: true, text: "", small: true }),
  bullets: () => ({ type: "bullets", key: "skills", title: "Skills", enabled: true, items: [] }),
  education: () => ({ type: "education", key: "education", title: "Education", enabled: true, entries: [] }),
  experience: () => ({ type: "experience", key: "experience", title: "Work Experience", enabled: true, entries: [] }),
  projects: () => ({ type: "projects", key: "projects", title: "Projects", enabled: true, entries: [] }),
};

/**
 * CV Studio (PLAN.md §5.6.1). The structured JSON is the source of truth: edits
 * stay local until Save, which appends a new version; Compile renders that
 * version to PDF through the Docker LaTeX builder.
 */
export function CvStudio({ version: wsVersion }: { version: number }) {
  // /cv edits the Master CV; /cv/<job id> edits that job's tailored fork.
  const { scope = "master" } = useParams();
  const { data, loading, error, refetch } = useApi(() => api.cv(scope), [scope]);

  const [draft, setDraft] = useState<CvDocument | null>(null);
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [savedVersion, setSavedVersion] = useState(0);

  const [compiling, setCompiling] = useState(false);
  const [compiledAt, setCompiledAt] = useState(0);
  const [pages, setPages] = useState<number | null>(null);
  const [buildError, setBuildError] = useState<string | null>(null);
  // undefined = never compiled this session; null = compiled but not checked.
  const [ats, setAts] = useState<AtsReport | null | undefined>(undefined);

  // Adopt the server document whenever a different version arrives.
  useEffect(() => {
    if (!data) return;
    setDraft(data.document);
    setSavedVersion(data.version);
  }, [data]);

  const versions = useApi(() => api.cvVersions(scope), [scope, savedVersion, wsVersion]);

  const dirty = useMemo(
    () => !!draft && !!data && JSON.stringify(draft) !== JSON.stringify(data.document),
    [draft, data],
  );

  const save = useCallback(async () => {
    if (!draft) return;
    setSaving(true);
    setActionError(null);
    try {
      const res = await api.saveCv(scope, draft);
      setSavedVersion(res.version);
      await refetch();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }, [draft, scope, refetch]);

  const compile = useCallback(async () => {
    setCompiling(true);
    setBuildError(null);
    try {
      const res = await api.compileCv(scope);
      setPages(res.pages);
      setAts(res.ats);
      setCompiledAt(Date.now());
    } catch (e) {
      setBuildError(e instanceof Error ? e.message : "Compile failed");
      setPages(null);
      setAts(undefined);
    } finally {
      setCompiling(false);
    }
  }, [scope]);

  const rollback = useCallback(
    async (target: number) => {
      setActionError(null);
      try {
        const res = await api.rollbackCv(scope, target);
        setSavedVersion(res.version);
        await refetch();
      } catch (e) {
        setActionError(e instanceof ApiError ? e.message : "Restore failed");
      }
    },
    [scope, refetch],
  );

  if (loading && !draft) return <StudioSkeleton />;
  if (error) return <Card><CardBody className="text-sm text-critical">{error}</CardBody></Card>;
  if (!draft) return null;

  const setSections = (sections: CvSection[]) => setDraft({ ...draft, sections });
  const moveSection = (i: number, delta: number) => {
    const next = [...draft.sections];
    const j = i + delta;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    setSections(next);
  };

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">CV Studio</h1>
          <p className="text-sm text-ink-muted">
            {scope === "master" ? "Master CV" : `Tailored · ${scope}`} · v{savedVersion}
            {dirty && <span className="ml-2 text-accent">unsaved changes</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {actionError && <span className="text-sm text-critical">{actionError}</span>}
          <Button onClick={save} disabled={!dirty || saving}>
            <Save size={15} /> {saving ? "Saving…" : "Save version"}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
        {/* Editor */}
        <div className="flex min-w-0 flex-col gap-4">
          <MarkupLegend />
          <HeaderEditor
            header={draft.header}
            theme={draft.theme}
            onHeader={(header) => setDraft({ ...draft, header })}
            onTheme={(theme) => setDraft({ ...draft, theme })}
          />

          {draft.sections.map((section, i) => (
            <SectionEditor
              key={`${section.key}-${i}`}
              section={section}
              disableUp={i === 0}
              disableDown={i === draft.sections.length - 1}
              onMove={(delta) => moveSection(i, delta)}
              onChange={(next) => setSections(draft.sections.map((s, j) => (j === i ? next : s)))}
              onRemove={() => setSections(draft.sections.filter((_, j) => j !== i))}
            />
          ))}

          <AddSection onAdd={(type) => setSections([...draft.sections, NEW_SECTION[type]()])} />
        </div>

        {/* Right rail */}
        <div className="flex flex-col gap-4 xl:sticky xl:top-20 xl:self-start">
          <PdfPreview
            scope={scope}
            dirty={dirty}
            compiling={compiling}
            pages={pages}
            error={buildError}
            compiledAt={compiledAt}
            onCompile={compile}
          />
          {ats !== undefined && (
            <Card className="p-4">
              <AtsPanel report={ats} />
            </Card>
          )}
          <VersionHistory
            versions={versions.data}
            current={savedVersion}
            loading={versions.loading}
            busy={saving}
            onRollback={rollback}
          />
        </div>
      </div>
    </div>
  );
}

function AddSection({ onAdd }: { onAdd: (type: CvSectionType) => void }) {
  const [type, setType] = useState<CvSectionType>("bullets");
  return (
    <div className="flex items-center gap-2">
      <Select value={type} onChange={(e) => setType(e.target.value as CvSectionType)}>
        <option value="paragraph">Paragraph</option>
        <option value="bullets">Bullets</option>
        <option value="education">Education</option>
        <option value="experience">Experience</option>
        <option value="projects">Projects</option>
      </Select>
      <Button variant="outline" size="sm" onClick={() => onAdd(type)}>
        <Plus size={14} /> Add section
      </Button>
    </div>
  );
}

function StudioSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
      <div className="flex flex-col gap-4">
        <Skeleton className="h-56" />
        <Skeleton className="h-14" />
        <Skeleton className="h-14" />
        <Skeleton className="h-14" />
      </div>
      <Skeleton className="h-[600px]" />
    </div>
  );
}
