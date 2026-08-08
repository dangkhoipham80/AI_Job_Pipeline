// Validated dataviz palette (see dataviz skill references/palette.md).
// Categorical hues in FIXED order — assigned by entity, never cycled/repainted.
export const CATEGORICAL_LIGHT = [
  "#2a78d6", // blue
  "#1baf7a", // aqua
  "#eda100", // yellow
  "#008300", // green
  "#4a3aa7", // violet
  "#e34948", // red
  "#e87ba4", // magenta
  "#eb6834", // orange
];
export const CATEGORICAL_DARK = [
  "#3987e5",
  "#199e70",
  "#c98500",
  "#008300",
  "#9085e9",
  "#e66767",
  "#d55181",
  "#d95926",
];

// Ordinal blue ramp for the funnel (steps that clear 2:1 on each surface).
export const ORDINAL_BLUE_LIGHT = ["#86b6ef", "#5598e7", "#3987e5", "#256abf", "#184f95", "#0d366b"];
export const ORDINAL_BLUE_DARK = ["#184f95", "#256abf", "#2a78d6", "#3987e5", "#5598e7", "#86b6ef"];

export const STATUS = {
  good: "#0ca30c",
  critical: "#d03b3b",
};

export function isDark(): boolean {
  return typeof document !== "undefined" && document.documentElement.classList.contains("dark");
}

export function categorical(): string[] {
  return isDark() ? CATEGORICAL_DARK : CATEGORICAL_LIGHT;
}

// Stable color for a source name so ITviec is always the same hue everywhere.
// Every source that can appear, in a fixed order. Sources beyond the list all
// collapsed onto one hue, which put five different boards in the same red on
// the Market page — colour has to identify the entity, and a shared colour
// identifies nothing.
// Exactly as many entries as the palette has hues. A longer list wraps —
// `lever` at index 8 landed on `itviec`'s blue — and two boards sharing a
// colour is worse than an unrecognised board getting one, because it looks
// deliberate.
const SOURCE_ORDER = [
  "itviec",
  "topcv",
  "vietnamworks",
  "linkedin",
  "weworkremotely",
  "lever",
  "greenhouse",
  "arbeitnow",
];
export function sourceColor(source: string): string {
  const pool = categorical();
  const i = SOURCE_ORDER.indexOf(source);
  // An unknown source hashes to a stable slot rather than sharing one bucket
  // with every other unknown — same entity, same colour, every render.
  if (i !== -1) return pool[i % pool.length];
  let h = 0;
  for (const ch of source) h = (h * 31 + ch.charCodeAt(0)) % 1021;
  return pool[h % pool.length];
}

// Stable color per model provider, so Claude is the same hue in the cost bar,
// the table and the picker. Assigned by entity and fixed in order — filtering
// the list must never repaint the survivors.
const PROVIDER_ORDER = ["claude", "openai", "gemini"];
export function providerColor(provider: string): string {
  const pool = categorical();
  const i = PROVIDER_ORDER.indexOf(provider);
  return pool[(i === -1 ? PROVIDER_ORDER.length : i) % pool.length];
}
