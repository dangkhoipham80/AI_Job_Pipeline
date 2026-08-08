/**
 * Display names for the raw keys that come out of the crawler.
 *
 * The database stores what the parsers produce — `no_jd`, `ci/cd`,
 * `weworkremotely` — and that is the right thing for it to store. But a chart
 * axis is prose, and `thin_jd` on an axis reads as a leaked column name. The
 * translation belongs here, at the edge, so nothing downstream is tempted to
 * "clean up" the stored value itself.
 *
 * Unknown keys fall back to title case rather than disappearing: a new source
 * or a new quality flag must still be readable the day it lands, before anyone
 * has added it to a map.
 */

const SOURCE_NAMES: Record<string, string> = {
  itviec: "ITviec",
  topcv: "TopCV",
  vietnamworks: "VietnamWorks",
  linkedin: "LinkedIn",
  weworkremotely: "WeWorkRemotely",
  arbeitnow: "Arbeitnow",
  greenhouse: "Greenhouse",
  lever: "Lever",
  topdev: "TopDev",
};

const QUALITY_NAMES: Record<string, string> = {
  clean: "Clean",
  no_jd: "No description",
  thin_jd: "Thin description",
  stale: "Stale posting",
  undated: "No posting date",
};

const LEVEL_NAMES: Record<string, string> = {
  intern: "Intern",
  fresher: "Fresher",
  junior: "Junior",
  middle: "Mid-level",
  senior: "Senior",
};

// Technologies whose casing is not title case. Everything else — react, docker,
// kafka — title-cases correctly, so the map only carries the exceptions.
const SKILL_NAMES: Record<string, string> = {
  ai: "AI",
  api: "API",
  aws: "AWS",
  "ci/cd": "CI/CD",
  css: "CSS",
  gcp: "GCP",
  graphql: "GraphQL",
  html: "HTML",
  ios: "iOS",
  javascript: "JavaScript",
  jquery: "jQuery",
  k8s: "Kubernetes",
  ml: "ML",
  mongodb: "MongoDB",
  mysql: "MySQL",
  nodejs: "Node.js",
  "node.js": "Node.js",
  oop: "OOP",
  php: "PHP",
  postgresql: "PostgreSQL",
  mariadb: "MariaDB",
  qa: "QA",
  rest: "REST",
  sql: "SQL",
  typescript: "TypeScript",
  ui: "UI",
  ux: "UX",
};

function titleCase(key: string): string {
  return key
    .replace(/[_-]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

const lookup = (map: Record<string, string>) => (key: string) =>
  map[key.toLowerCase()] ?? titleCase(key);

export const sourceLabel = lookup(SOURCE_NAMES);
export const qualityLabel = lookup(QUALITY_NAMES);
export const levelLabel = lookup(LEVEL_NAMES);
export const skillLabel = lookup(SKILL_NAMES);
