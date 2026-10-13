/**
 * SAMPLE DATA, not real runs: the hero's run city, floating cards and
 * headline numbers, as drawn on the v4 Landing and PhoneLanding boards
 * (design/reference/gen_landing3.py, hero()).
 */
import { HERO_CITY_SAMPLE_SESSIONS, sampleHeroCityDays } from "@syn137/skyline-core/geometry";

export interface CityLayout {
  cols: number;
  rows: number;
  cell: number;
  live: number[];
  failed: number[];
  errored: number[];
}

/** Desktop: 26 x 11 blocks of 36 units; phone: 16 x 8 of 30. Indexes are block numbers (row * cols + column). */
export const CITY_DESKTOP: CityLayout = { cols: 26, rows: 11, cell: 36, live: [150, 171, 199, 222], failed: [88, 260], errored: [141] };
export const CITY_PHONE: CityLayout = { cols: 16, rows: 8, cell: 30, live: [90, 101, 118], failed: [52], errored: [77] };

const END = "2026-10-08";
export const cityDays = (c: CityLayout) => sampleHeroCityDays(c.cols, c.rows, END);
export const CITY_MAX_SESSIONS = HERO_CITY_SAMPLE_SESSIONS;

export const HERO_CARDS = {
  run: { meta: "self-heal-ci · run #142", title: "Fixed the failing check on PR #311", detail: "Triggered by GitHub · 4m 10s · $0.31" },
  phases: {
    meta: "implement-and-review",
    chips: [
      { provider: "claude", label: "implement · claude" },
      { provider: "codex", label: "review · codex" },
    ],
  },
  trend: { meta: "this workflow, 5 weeks", gains: ["−37% time", "+24 pts quality"] },
} as const;

export const HERO_STATS: readonly { value: string; label: string }[] = [
  { value: "1", label: "workflow, run 142 times" },
  { value: "2", label: "harnesses, any phase" },
  { value: "214", label: "tool calls in the last run, all kept" },
  { value: "+24", label: "quality points in 2 weeks" },
];
