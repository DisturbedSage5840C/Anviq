"use client";

/**
 * Synthetic trends, so the dashboard can be shown to mentors and judges before the pilot
 * produces a real bucket of 20 teachers. Rows are produced raw, exactly as a data source
 * would emit them, including cells that under 20 teachers would belong to. The source
 * itself applies the k>=20 cut, so the page only ever sees what it would see live.
 */

import type { TrendsPayload, TrendRow } from "@/components/trends-table";

const K_THRESHOLD = 20;

// One deterministic loop, so the same demo shows the same story every time.
function seeded(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0x1000_0000;
  };
}

export function syntheticTrends(): TrendsPayload {
  const rows: TrendRow[] = [];
  const random = seeded(20_261_031);

  const clusters = [
    { code: "DEMO-A", teachers: 26, base: 1.9, drift: 0.06 },
    { code: "DEMO-B", teachers: 21, base: 1.6, drift: 0.09 },
    // A third cluster deliberately below the threshold: it must never appear in the output.
    { code: "DEMO-C", teachers: 9, base: 2.4, drift: 0.05 },
  ];

  const starts = ["2026-W43", "2026-W44", "2026-W45"];

  for (const cluster of clusters) {
    for (let index = 0; index < starts.length; index++) {
      const week = starts[index];
      for (const move of cluster.teachers >= K_THRESHOLD ? [1, 2] : [2]) {
        const average =
          (cluster.base + index * cluster.drift + move * 0.05 + (random() - 0.5) * 0.1) * 100;
        rows.push({
          cluster_code: cluster.code,
          move_id: move,
          iso_week: week,
          n_teachers: cluster.teachers,
          avg_improvement: Math.round(average) / 100,
          avg_sessions: Math.round((3 + random()) * 10) / 10,
        });
      }
    }
  }

  // The view would drop the sub-threshold cluster entirely; drop it the way SQL would.
  const passed = rows.filter((row) => row.n_teachers >= K_THRESHOLD);
  return { k_threshold: K_THRESHOLD, rows: passed };
}
