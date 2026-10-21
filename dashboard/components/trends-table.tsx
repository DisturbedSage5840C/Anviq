"use client";

/**
 * Renders the k >= 20 anonymous trends grid.
 *
 * The backend answers GET /dashboard/trends with only the buckets that passed the
 * `public_trends` view (>= k_threshold distinct teachers), behind a bearer token. A cell
 * missing from the rows did not pass, so the page says so rather than inventing a zero:
 * "Suppressed · < 20". The threshold comes from the response so a migration change shows
 * on the page without redeploying it.
 */

"use client";

import { useMemo, useState } from "react";

export type TrendRow = {
  cluster_code: string;
  move_id: number;
  iso_week: string;
  n_teachers: number;
  avg_improvement: number;
  avg_sessions: number;
};

export type TrendsPayload = { k_threshold: number; rows: TrendRow[] };

const ALL_MOVES = [1, 2, 3, 4, 5, 6] as const;

type Present = { kind: "present"; avgImprovement: number; nTeachers: number };
type Cell = Present | { kind: "suppressed" };

type GridRow = { week: string; cluster: string; cells: Record<number, Cell> };

function buildGrid(payload: TrendsPayload, moves: readonly number[]): {
  rows: GridRow[];
  weeks: string[];
} {
  const weeksSeen = new Set<string>();
  const clusters = new Set<string>();
  const byKey = new Map<string, TrendRow>();
  for (const row of payload.rows) {
    weeksSeen.add(row.iso_week);
    clusters.add(row.cluster_code);
    byKey.set(`${row.iso_week}|${row.cluster_code}|${row.move_id}`, row);
  }
  const weeks = [...weeksSeen].sort((a, b) => (a < b ? 1 : -1));
  const rows: GridRow[] = [];
  for (const week of weeks) {
    for (const cluster of [...clusters].sort()) {
      const row: GridRow = { week, cluster, cells: {} };
      for (const move of moves) {
        const hit = byKey.get(`${week}|${cluster}|${move}`);
        row.cells[move] = hit
          ? { kind: "present", avgImprovement: hit.avg_improvement, nTeachers: hit.n_teachers }
          : { kind: "suppressed" };
      }
      rows.push(row);
    }
  }
  return { rows, weeks };
}

export default function TrendsTable({ payload }: { payload: TrendsPayload }) {
  const [moveFilter, setMoveFilter] = useState<number | null>(null);
  const [weekWindow, setWeekWindow] = useState(4);

  const moves = moveFilter === null ? ALL_MOVES : [moveFilter];
  const { rows, weeks } = useMemo(() => buildGrid(payload, moves), [payload, moves]);

  const shownWeeks = weeks.slice(0, weekWindow);
  const visible = rows.filter((row) => shownWeeks.includes(row.week));

  return (
    <section aria-labelledby="trends-heading" className="trends">
      <h2 id="trends-heading">हफ़्तों के हिसाब से गतिविधि · week over week</h2>

      <fieldset className="filter">
        <legend>कक्षा-तरीक़ा फ़िल्टर </legend>
        <div className="filter-row">
          <label>
            <input
              type="radio"
              name="move"
              checked={moveFilter === null}
              onChange={() => setMoveFilter(null)}
            />
            सभी (all)
          </label>
          {ALL_MOVES.map((move) => (
            <label key={move}>
              <input
                type="radio"
                name="move"
                checked={moveFilter === move}
                onChange={() => setMoveFilter(move)}
              />
              move {move}
            </label>
          ))}
        </div>
        <div className="filter-row">
          <label>
            हफ़्ते:
            <select value={weekWindow} onChange={(event) => setWeekWindow(Number(event.target.value))}>
              <option value={1}>latest 1</option>
              <option value={4}>last 4</option>
              <option value={12}>last 12</option>
              <option value={Number.MAX_SAFE_INTEGER}>सभी</option>
            </select>
          </label>
        </div>
      </fieldset>

      {visible.length === 0 ? (
        <p className="empty">
          कोई समूह अभी 20 शिक्षकों की सीमा पार नहीं करता। New clusters stay private until{" "}
          {payload.k_threshold} teachers share a cluster code and week. यही डिज़ाइन है।
        </p>
      ) : (
        <table>
          <thead>
            <tr>
              <th scope="col">हफ़्ता</th>
              <th scope="col">cluster</th>
              {moves.map((move) => (
                <th scope="col" key={move}>move {move}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <tr key={`${row.week}|${row.cluster}`}>
                <th scope="row">{row.week}</th>
                <td className="cluster">{row.cluster}</td>
                {moves.map((move) => {
                  const cell = row.cells[move];
                  return cell.kind === "suppressed" ? (
                    <td key={move} className="suppressed" title="निजी रखा गया">
                      Suppressed · &lt; {payload.k_threshold}
                    </td>
                  ) : (
                    <td key={move}>
                      <span className="avg">{cell.avgImprovement.toFixed(2)}</span>{" "}
                      <span className="n">n = {cell.nTeachers}</span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <p className="muted">
        Shown here: the group's average of criteria met (0–4 scale), only for buckets of{" "}
        {payload.k_threshold}+ teachers. The teacher's own 🌱/🌿/🌳 never leaves her chat, and
        no per-teacher view exists anywhere in the codebase, not even this page.
      </p>
    </section>
  );
}
