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

// Ordinal ramps sized to the series count. A ramp is only legal if every
// adjacent pair differs by ΔL ≥ 0.06 and the end nearest the surface still
// clears 2:1 — squeeze six steps into the light band and the middle two become
// the same blue. So the step *choice* changes with n rather than the ramp being
// sliced blindly. Each row below is the widest evenly-spaced subset of the blue
// scale in the dataviz skill's palette.md that passes `validateOrdinal`, run per
// mode against this app's own surfaces (#ffffff / #1a1a19).
//
// Only for genuinely ordered categories — seniority, tiers, funnel stages. A
// ramp down a *nominal* ranking (skills, cities) would re-encode bar length as
// hue and spend the identity channel on nothing.
const ORDINAL_LIGHT: Record<number, string[]> = {
  1: ["#2a78d6"],
  2: ["#86b6ef", "#0d366b"],
  3: ["#86b6ef", "#2a78d6", "#0d366b"],
  4: ["#86b6ef", "#3987e5", "#1c5cab", "#0d366b"],
  5: ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#0d366b"],
};
const ORDINAL_DARK: Record<number, string[]> = {
  1: ["#3987e5"],
  2: ["#184f95", "#cde2fb"],
  3: ["#184f95", "#5598e7", "#cde2fb"],
  4: ["#184f95", "#2a78d6", "#6da7ec", "#cde2fb"],
  5: ["#184f95", "#256abf", "#3987e5", "#86b6ef", "#cde2fb"],
};

/** Validated ordinal ramp of exactly `n` steps, low → high.
 *
 *  Past five steps the blue scale has no legal subset — adjacent steps fall
 *  under ΔL 0.06 and read as one colour — so the ramp stops at five and the
 *  extra rows repeat the darkest step rather than coming back `undefined` and
 *  rendering an uncoloured bar. Five is enough for every ordered facet here
 *  (the seniority scale has exactly five levels); a longer one should be
 *  re-validated, not stretched. */
export function ordinalRamp(n: number): string[] {
  const table = isDark() ? ORDINAL_DARK : ORDINAL_LIGHT;
  const ramp = table[Math.min(Math.max(n, 1), 5)];
  if (n <= ramp.length) return ramp;
  const last = ramp[ramp.length - 1];
  return [...ramp, ...Array(n - ramp.length).fill(last)];
}

// Reserved state scale — never a stand-in for "series 4", and never shown
// without an icon and a label beside it (on the light surface `warning` and
// `serious` sit below 3:1 by design; the pairing is the mitigation).
export const STATUS = {
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
};

/** De-emphasis grey — the "Other" bucket and anything meaning *not known*.
 *  Deliberately below the chroma floor: it is not an identity hue, it is the
 *  absence of one. 3.59:1 on white, 4.85:1 on the dark surface. */
export const MUTED = "#898781";

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
export const SOURCE_ORDER = [
  "itviec",
  "topcv",
  "vietnamworks",
  "linkedin",
  "weworkremotely",
  "lever",
  "greenhouse",
  "arbeitnow",
];
/** Which palette slot a source occupies. Unknown sources hash to a stable slot
 *  rather than sharing one bucket with every other unknown — same entity, same
 *  colour, every render. */
export function sourceSlot(source: string): number {
  const i = SOURCE_ORDER.indexOf(source);
  if (i !== -1) return i;
  let h = 0;
  for (const ch of source) h = (h * 31 + ch.charCodeAt(0)) % 1021;
  return h % SOURCE_ORDER.length;
}

export function sourceColor(source: string): string {
  const pool = categorical();
  return pool[sourceSlot(source) % pool.length];
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
