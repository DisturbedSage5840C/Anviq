"use client";

/**
 * The only client the dashboard has: GET /dashboard/trends with a bearer token.
 *
 * The token is the endpoint's rate-limiter, not the privacy mechanism; the k>=20 rule is
 * enforced in SQL by the `public_trends` view, so a leaked token cannot reveal anything
 * about an individual teacher. That is why this token may live in a browser without
 * weakening the promise.
 */

import type { TrendsPayload, TrendRow } from "@/components/trends-table";

export class ApiError extends Error {
  status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

const TIMEOUT_MS = 15_000;

export function normaliseBase(base: string): string {
  return base.trim().replace(/\/+$/, "");
}

export async function fetchTrends(apiBase: string, token: string): Promise<TrendsPayload> {
  const base = normaliseBase(apiBase);
  if (base === "") throw new ApiError(0, "An API URL is needed.");
  if (token.trim() === "") throw new ApiError(0, "A dashboard token is needed.");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetch(`${base}/dashboard/trends`, {
      headers: { Authorization: `Bearer ${token}`, "Cache-Control": "no-store" },
      signal: controller.signal,
    });
    if (!response.ok) {
      let detail = `The trends feed answered ${response.status}`;
      if (response.status === 401) detail = "Token rejected. Check the dashboard token.";
      if (response.status === 503) {
        detail = "This deployment has no dashboard feed configured (also 503).";
      }
      throw new ApiError(response.status, detail);
    }
    const body = (await response.json()) as { k_threshold?: unknown; rows?: unknown };
    if (typeof body.k_threshold !== "number" || !Array.isArray(body.rows)) {
      throw new ApiError(response.status, "Unexpected trends response.");
    }
    const rows: TrendRow[] = body.rows.filter(isTrendRow);
    return { k_threshold: body.k_threshold, rows };
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(0, "The trends feed was too slow to answer.");
    }
    throw new ApiError(0, "Could not reach the API. Check the URL and its HTTPS certificate.");
  } finally {
    clearTimeout(timer);
  }
}

function isTrendRow(value: unknown): value is TrendRow {
  if (typeof value !== "object" || value === null) return false;
  const row = value as Record<string, unknown>;
  return (
    typeof row.cluster_code === "string" &&
    typeof row.move_id === "number" &&
    typeof row.iso_week === "string" &&
    typeof row.n_teachers === "number" &&
    typeof row.avg_improvement === "number" &&
    typeof row.avg_sessions === "number"
  );
}
