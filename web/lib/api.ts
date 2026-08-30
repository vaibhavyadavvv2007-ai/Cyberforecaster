/**
 * Typed client for the CyberForecaster FastAPI backend (api/).
 * Types mirror api/schemas.py exactly — if the two drift, one of them is wrong.
 * Base URL: NEXT_PUBLIC_API_URL (default http://localhost:8000, the demo laptop).
 */

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Mode = "REAL" | "CACHED" | "SIMULATED";
export type ScenarioKind = "onset" | "during" | "quiet";
export type RiskLevel = "HIGH" | "ELEVATED" | "LOW";

export interface Health {
  mode: Mode;
  boot_error: string | null;
  model_error: string | null;
  n_windows: number;
  n_scenarios: number;
  n_features: number | null;
  horizon: number | null;
  threshold: number;
  mean_attack_frac: number;
}

export interface Scenario {
  id: string;
  name: string;
  kind: ScenarioKind;
  anchor: number;
}

export interface AttributionItem {
  feature: string;
  importance: number;
}

export interface Forecast {
  scenario_id: string;
  mode: Mode;
  probs: number[];
  peak: number;
  level: RiskLevel;
  stage: string;
  rule_stage: string;
  threshold: number;
  /** 1-based step at which probs first cross the threshold; null = never. */
  crossing_step: number | null;
  why: AttributionItem[] | null;
  why_note: string | null;
}

export interface TimelinePoint {
  ts: string;
  /** Ground-truth attack fraction — the model never sees it. */
  observed: number;
  /** Null before the anchor; the anchor point repeats observed to join the curves. */
  forecast: number | null;
}

export interface Timeline {
  scenario_id: string;
  anchor_ts: string;
  /** Index into points[] where the forecast starts. */
  anchor_index: number;
  threshold: number;
  points: TimelinePoint[];
}

/** One row of the per-model benchmark table (aggregate metrics). */
export interface ModelMetrics {
  precision?: number;
  recall?: number;
  f1?: number;
  fpr?: number;
  pr_auc?: number;
  roc_auc?: number;
  accuracy?: number;
  threshold?: number;
  _per_step?: ModelMetrics[];
  [key: string]: unknown;
}

/** Lead-time stats — one entry per model/split. */
export interface LeadTimeMetrics {
  median_lead_min?: number;
  mean_lead_min?: number;
  n_onsets?: number;
  [key: string]: unknown;
}

/**
 * /api/metrics shape, namespaced by source file:
 *   { baseline: {logistic_baseline: ModelMetrics},
 *     lstm: {lstm_forecaster: ModelMetrics},
 *     lead_time: {lstm_forecaster: LeadTimeMetrics, ...} }
 */
export interface MetricsBundle {
  baseline?: Record<string, ModelMetrics>;
  lstm?: Record<string, ModelMetrics>;
  lead_time?: Record<string, LeadTimeMetrics>;
  [key: string]: Record<string, unknown> | undefined;
}

export interface FlaggedResponse {
  total_flagged: number;
  total_windows: number;
  rows: Record<string, unknown>[];
}

// ---- live traffic monitoring (/api/live/*) ----

export interface LiveSensorStatus {
  running: boolean;
  iface: string | null;
  error: string | null;
  bin_secs: number;
  packets_seen: number;
  packets_skipped: number;
  flows_in_bin: number;
  bin_elapsed_s: number;
  bin_remaining_s: number;
  started_at: number | null;
  last_packet_age_s: number | null;
}

export interface LiveWindow {
  ts: number;
  bin_id: number;
  source: "seed" | "live";
  flow_count: number;
  pkts_total: number;
  syn_ratio: number;
  unique_dst_ports: number;
  rule_stage: string;
  empty: boolean;
  /** Peak next-horizon probability forecast as of this window; null = not
   * enough history yet, or annotation unavailable. */
  forecast_peak?: number | null;
}

export interface LiveForecast {
  probs: number[];
  peak: number;
  level: RiskLevel;
  stage: string;
  threshold: number;
  crossing_step: number | null;
  why: AttributionItem[] | null;
  rule_stage: string;
  n_history: number;
}

export interface LiveEvent {
  ts: number;
  bin_id: number;
  peak: number;
  level: RiskLevel;
  stage: string;
  rule_stage: string;
  source: string;
}

export interface LiveFeed {
  sensor: LiveSensorStatus;
  bin_secs: number;
  seq_len: number;
  n_seed: number;
  n_live: number;
  ready: boolean;
  windows: LiveWindow[];
  latest: LiveForecast | null;
  events: LiveEvent[];
}

export interface LiveStartResponse {
  ok: boolean;
  error?: string;
  seeded_windows?: number;
  model_ready?: boolean;
  already_running?: boolean;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail ?? `GET ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail ?? `POST ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => get<Health>("/api/health"),
  scenarios: () => get<Scenario[]>("/api/scenarios"),
  forecast: (scenarioId: string, threshold?: number) =>
    post<Forecast>("/api/forecast", { scenario_id: scenarioId, threshold }),
  timeline: (scenarioId: string, threshold?: number) =>
    get<Timeline>(
      `/api/timeline?scenario_id=${encodeURIComponent(scenarioId)}` +
        (threshold != null ? `&threshold=${threshold}` : ""),
    ),
  metrics: () => get<MetricsBundle>("/api/metrics"),
  flagged: (limit = 15) => get<FlaggedResponse>(`/api/flagged?limit=${limit}`),
  liveFeed: () => get<LiveFeed>("/api/live/feed"),
  liveStart: (iface?: string, useSeed = true) =>
    post<LiveStartResponse>("/api/live/start", { iface: iface ?? null, use_seed: useSeed }),
  liveStop: () => post<{ ok: boolean }>("/api/live/stop", {}),
  liveInterfaces: () => get<{ interfaces: string[] }>("/api/live/interfaces"),
};

export const API_BASE = BASE;
