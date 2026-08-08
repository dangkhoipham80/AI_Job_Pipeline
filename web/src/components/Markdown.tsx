import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * A small Markdown renderer for the subset job descriptions actually contain.
 *
 * `crawler/text.py:html_to_markdown` emits headings, bullet lists and blank-line
 * separated paragraphs — that is the whole vocabulary, plus whatever a user
 * pastes by hand. So this is deliberately not a full CommonMark implementation
 * and deliberately not a dependency: it builds React nodes, never HTML strings,
 * so a JD scraped off a third-party board can't inject markup.
 */

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "para"; text: string }
  | { kind: "rule" };

const HEADING = /^(#{1,6})\s+(.*)$/;
const BULLET = /^\s*[-*•·]\s+(.*)$/;
const ORDERED = /^\s*\d+[.)]\s+(.*)$/;
const RULE = /^\s*(?:-{3,}|_{3,}|\*{3,})\s*$/;

function parse(source: string): Block[] {
  const blocks: Block[] = [];
  let para: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;

  const flush = () => {
    if (para.length) blocks.push({ kind: "para", text: para.join("\n") });
    if (list) blocks.push({ kind: "list", ...list });
    para = [];
    list = null;
  };

  for (const raw of source.replace(/\r\n?/g, "\n").split("\n")) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      flush();
      continue;
    }

    const rule = RULE.test(line);
    const heading = line.match(HEADING);
    const bullet = line.match(BULLET);
    const ordered = rule ? null : line.match(ORDERED);

    if (rule) {
      flush();
      blocks.push({ kind: "rule" });
    } else if (heading) {
      flush();
      blocks.push({ kind: "heading", level: heading[1].length, text: heading[2] });
    } else if (bullet || ordered) {
      const isOrdered = !bullet;
      const item = (bullet ?? ordered)![1];
      if (para.length) {
        blocks.push({ kind: "para", text: para.join("\n") });
        para = [];
      }
      // A change of marker starts a new list rather than mixing the two.
      if (list && list.ordered !== isOrdered) {
        blocks.push({ kind: "list", ...list });
        list = null;
      }
      list ??= { ordered: isOrdered, items: [] };
      list.items.push(item);
    } else if (list) {
      // Continuation of the previous bullet (wrapped line), not a new paragraph.
      list.items[list.items.length - 1] += ` ${line.trim()}`;
    } else {
      para.push(line);
    }
  }
  flush();
  return mergeLists(blocks);
}

/**
 * Fuse adjacent lists of the same kind into one.
 *
 * `html_to_markdown` joins *every* block with a blank line, siblings inside one
 * `<ul>` included — so a three-bullet list arrives as `"- a\n\n- b\n\n- c"`.
 * Read strictly that is three one-item lists, which is what the parser produced:
 * three `<ul>` elements, wrong spacing, and a screen reader announcing "list of
 * 1" three times. Only *adjacent* blocks fuse, so a paragraph between two lists
 * still keeps them apart.
 */
function mergeLists(blocks: Block[]): Block[] {
  const out: Block[] = [];
  for (const block of blocks) {
    const last = out[out.length - 1];
    if (block.kind === "list" && last?.kind === "list" && last.ordered === block.ordered) {
      last.items.push(...block.items);
    } else {
      out.push(block.kind === "list" ? { ...block, items: [...block.items] } : block);
    }
  }
  return out;
}

/* Inline: **bold**, *italic*, `code`, [label](url) ------------------------- */
const INLINE = /(\*\*[^*]+\*\*|\*[^*\n]+\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\))/g;
const LINK = /^\[([^\]]+)\]\(([^)\s]+)\)$/;

/** Only schemes that can't execute — a scraped JD is untrusted input. */
function safeHref(url: string): string | null {
  return /^(https?:|mailto:)/i.test(url) ? url : null;
}

function inline(text: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    if (i % 2 === 0) return part;
    if (part.startsWith("**")) return <strong key={i} className="font-semibold text-ink">{part.slice(2, -2)}</strong>;
    if (part.startsWith("`"))
      return (
        <code key={i} className="rounded bg-surface-2 px-1 py-px font-mono text-[0.85em] text-ink">
          {part.slice(1, -1)}
        </code>
      );
    const link = part.match(LINK);
    if (link) {
      const href = safeHref(link[2]);
      return href ? (
        <a
          key={i}
          href={href}
          target="_blank"
          rel="noreferrer"
          className="text-accent underline decoration-accent/40 underline-offset-2 hover:decoration-accent"
        >
          {link[1]}
        </a>
      ) : (
        <span key={i}>{link[1]}</span>
      );
    }
    return <em key={i} className="italic">{part.slice(1, -1)}</em>;
  });
}

/* Headings ------------------------------------------------------------------ */
// Boards don't agree on where their heading scale starts — ITviec's JD opens at
// `##`, a pasted one may open at `#` or `###`. Ranking relative to the shallowest
// heading present keeps the visual hierarchy right instead of rendering an entire
// description at one size.
function headingNode(text: string, tier: number, key: number): ReactNode {
  if (tier <= 0)
    return (
      <div key={key} className="mt-7 flex items-center gap-3 first:mt-0">
        <span className="h-3.5 w-[3px] shrink-0 rounded-full bg-accent" />
        <h3 className="font-display text-[13px] font-semibold uppercase tracking-[0.12em] text-ink">
          {inline(text)}
        </h3>
        <span className="h-px flex-1 bg-border" />
      </div>
    );
  if (tier === 1)
    return (
      <h4 key={key} className="mt-5 font-display text-[15px] font-semibold text-ink first:mt-0">
        {inline(text)}
      </h4>
    );
  return (
    // Not `text-ink-muted`: a heading dimmer than the bullets it introduces
    // inverts the hierarchy, which is exactly how it read in dark mode.
    <h5 key={key} className="mt-4 text-[13px] font-semibold text-ink first:mt-0">
      {inline(text)}
    </h5>
  );
}

export function Markdown({ source, className = "" }: { source: string; className?: string }) {
  const blocks = parse(source);
  const levels = blocks.filter((b) => b.kind === "heading").map((b) => (b as { level: number }).level);
  const base = levels.length ? Math.min(...levels) : 1;

  return (
    // The page itself is full-bleed, but prose isn't: a JD line running the
    // whole width of a 1920 monitor is unreadable. `cn` (tailwind-merge) means a
    // caller can still override the measure.
    <div className={cn("max-w-[100ch] text-sm leading-relaxed text-ink/90", className)}>
      {blocks.map((block, i) => {
        if (block.kind === "heading") return headingNode(block.text, block.level - base, i);
        if (block.kind === "rule") return <hr key={i} className="my-5 border-border" />;
        if (block.kind === "para")
          return (
            <p key={i} className="mt-3 whitespace-pre-line first:mt-0">
              {inline(block.text)}
            </p>
          );
        if (block.ordered)
          return (
            <ol
              key={i}
              className="mt-3 list-decimal space-y-1.5 pl-6 marker:font-mono marker:text-xs marker:text-ink-muted first:mt-0"
            >
              {block.items.map((item, j) => (
                <li key={j} className="pl-1">{inline(item)}</li>
              ))}
            </ol>
          );
        return (
          <ul key={i} className="mt-3 space-y-1.5 first:mt-0">
            {block.items.map((item, j) => (
              <li key={j} className="relative pl-4">
                <span className="absolute left-0 top-[0.62em] h-1.5 w-1.5 rounded-full bg-accent/50" />
                {inline(item)}
              </li>
            ))}
          </ul>
        );
      })}
    </div>
  );
}
