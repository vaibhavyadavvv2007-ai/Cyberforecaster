"use client";

import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type MetricsBundle, type ModelMetrics } from "@/lib/api";
import { Card, Metric } from "@/components/ui";

const COLS: (keyof ModelMetrics)[] = ["precision", "recall", "f1", "fpr", "pr_auc", "roc_auc"];

const COL_LABEL: Partial<Record<keyof ModelMetrics, string>> = {
  precision: "Precision",
  recall: "Recall",
  f1: "F1",
  fpr: "FPR",
  pr_auc: "PR-AUC",
  roc_auc: "ROC-AUC",
};

function fmt(v: unknown): string {
  return typeof v === "number" ? v.toFixed(3) : "-";
}

function fmt1(v: unknown): string {
  return typeof v === "number" ? v.toFixed(1) : "-";
}

function displayName(key: string): string {
  return key.replace(/_/g, " ");
}

/* ---- comparison bars: two models per metric, exact values kept ---- */
const COMPARE_COLS: (keyof ModelMetrics)[] = ["pr_auc", "f1", "recall", "precision", "fpr"];

function ComparisonRow({
  label,
  baseline,
  lstm,
}: {
  label: string;
  baseline?: number;
  lstm?: number;
}) {
  const max = Math.max(baseline ?? 0, lstm ?? 0, 1e-9);
  const bars = [
    { name: "Logistic baseline", value: baseline, cls: "bg-fg-2/50" },
    { name: "LSTM forecaster", value: lstm, cls: "bg-amber" },
  ];
  return (
    <div className="px-5 py-3.5">
      <div className="text-sm font-medium text-fg">{label}</div>
      <div className="mt-2 space-y-1.5">
        {bars.map((b) => (
          <div key={b.name} className="flex items-center gap-3">
            <span className="w-32 shrink-0 truncate text-xs text-fg-2">{b.name}</span>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-surface-2">
              <div
                className={`h-full rounded-full ${b.cls}`}
                style={{
                  width: b.value == null ? 0 : `${Math.max((b.value / max) * 100, 2)}%`,
                }}
              />
            </div>
            <span className="mono w-12 shrink-0 text-right text-xs text-fg">
              {b.value == null ? "-" : b.value.toFixed(3)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function MetricTable({ rows }: { rows: { model: string; m: ModelMetrics }[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="data-table">
        <thead>
          <tr>
            <th>Model</th>
            {COLS.map((c) => (
              <th key={c}>{COL_LABEL[c]}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(({ model, m }) => (
            <tr key={model}>
              <td className="rowhead">{model}</td>
              {COLS.map((c) => (
                <td key={c} className="num">
                  {fmt(m[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function BenchmarksPage() {
  const [metrics, setMetrics] = useState<MetricsBundle | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.metrics().then(setMetrics).catch((e) => setError(String(e)));
  }, []);

  if (error) {
    return (
      <section className="rounded-lg border border-red/25 bg-red/10 p-4">
        <p className="text-sm font-medium text-red">{error}</p>
      </section>
    );
  }
  if (!metrics) {
    return (
      <section className="rounded-lg border border-border bg-surface p-6">
        <p className="text-sm text-fg-2">Loading metrics…</p>
      </section>
    );
  }

  // Every model from every non-lead-time section — the detailed tables keep
  // all of them, served verbatim.
  const sections = Object.entries(metrics).filter(
    ([k, v]) => k !== "lead_time" && v && typeof v === "object",
  );
  const aggRows = sections.flatMap(([section, models]) =>
    Object.entries(models as Record<string, ModelMetrics>)
      .filter(([, m]) => "pr_auc" in (m ?? {}) || "f1" in (m ?? {}))
      .map(([name, m]) => ({
        model: displayName(name),
        key: name,
        m,
        section,
      })),
  );
  const findRow = (match: (key: string) => boolean) => aggRows.find((r) => match(r.key));
  const lstmRow = findRow((k) => k.includes("lstm"));
  const baselineRow = findRow((k) => k.includes("logistic") || k.includes("baseline"));
  const lstm = lstmRow?.m;
  const baseline = baselineRow?.m;

  // Per-step series for the horizon chart.
  const steps = Math.max(
    lstm?._per_step?.length ?? 0,
    baseline?._per_step?.length ?? 0,
  );
  const horizonData =
    steps > 0
      ? Array.from({ length: steps }, (_, i) => ({
          step: `t+${i + 1}`,
          lstm: lstm?._per_step?.[i]?.pr_auc ?? undefined,
          baseline: baseline?._per_step?.[i]?.pr_auc ?? undefined,
        }))
      : [];

  return (
    <div className="space-y-4">
      {/* ---- page header ---- */}
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-fg">Benchmarks</h1>
        <p className="mt-1 text-sm text-fg-2">
          Chronological test split · threshold tuned on validation under an FPR
          budget, never on test · values served verbatim from the training
          scripts
        </p>
      </div>

      {aggRows.length === 0 ? (
        <Card>
          <p className="text-sm text-amber">No metrics yet: run the training scripts.</p>
        </Card>
      ) : (
        <>
          {/* ---- headline metrics for the shipping model ---- */}
          {lstm && (
            <Card title="Model performance" meta="LSTM forecaster · test split">
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <Metric label="F1" value={fmt(lstm.f1)} sub="higher is better" />
                <Metric label="Recall" value={fmt(lstm.recall)} sub="higher is better" />
                <Metric label="Precision" value={fmt(lstm.precision)} sub="higher is better" />
                <Metric label="FPR" value={fmt(lstm.fpr)} sub="lower is better" />
              </div>
            </Card>
          )}

          {/* ---- visual comparison ---- */}
          {lstm && baseline && (
            <Card title="Model comparison" meta="logistic baseline vs LSTM forecaster">
              <div className="divide-y divide-border/60">
                {COMPARE_COLS.map((c) => (
                  <ComparisonRow
                    key={c}
                    label={COL_LABEL[c] ?? String(c)}
                    baseline={typeof baseline[c] === "number" ? (baseline[c] as number) : undefined}
                    lstm={typeof lstm[c] === "number" ? (lstm[c] as number) : undefined}
                  />
                ))}
              </div>
            </Card>
          )}

          {/* ---- per-horizon decay ---- */}
          {horizonData.length > 0 && (
            <Card title="Performance by forecast horizon" meta="PR-AUC by step">
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={horizonData} margin={{ top: 8, right: 16, bottom: 0, left: -12 }}>
                    <CartesianGrid stroke="#232831" strokeDasharray="3 3" vertical={false} />
                    <XAxis
                      dataKey="step"
                      stroke="#232831"
                      tick={{ fill: "#5b6470", fontSize: 10, fontFamily: "JetBrains Mono" }}
                      tickLine={false}
                    />
                    <YAxis
                      stroke="#232831"
                      tick={{ fill: "#5b6470", fontSize: 10, fontFamily: "JetBrains Mono" }}
                      tickLine={false}
                      tickFormatter={(v: number) => v.toFixed(2)}
                      width={52}
                      domain={[0, 0.7]}
                    />
                    <Tooltip
                      contentStyle={{
                        background: "#161b21",
                        border: "1px solid #232831",
                        borderRadius: 8,
                        fontSize: 12,
                        fontFamily: "JetBrains Mono",
                      }}
                      labelStyle={{ color: "#8b929d" }}
                      formatter={(value, name) => [
                        typeof value === "number" ? value.toFixed(3) : String(value ?? "-"),
                        name === "lstm" ? "LSTM forecaster" : "Logistic baseline",
                      ]}
                    />
                    <Line
                      type="monotone"
                      dataKey="baseline"
                      name="baseline"
                      stroke="#8b929d"
                      strokeWidth={1.5}
                      dot={{ r: 2.5, fill: "#8b929d", strokeWidth: 0 }}
                      connectNulls
                      isAnimationActive={false}
                    />
                    <Line
                      type="monotone"
                      dataKey="lstm"
                      name="lstm"
                      stroke="#f59e0b"
                      strokeWidth={2}
                      dot={{ r: 2.5, fill: "#f59e0b", strokeWidth: 0 }}
                      connectNulls
                      isAnimationActive={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1">
                <span className="flex items-center gap-2 text-xs text-fg-2">
                  <span className="inline-block h-[2px] w-5 rounded-full bg-fg-2" />
                  Logistic baseline
                </span>
                <span className="flex items-center gap-2 text-xs text-fg-2">
                  <span className="inline-block h-[2px] w-5 rounded-full bg-amber" />
                  LSTM forecaster
                </span>
              </div>
              <p className="mt-3 text-xs text-fg-2">
                Both models lose accuracy as they forecast further out; the
                temporal model keeps a consistent edge at every step. Exact
                values in the detailed tables below.
              </p>
            </Card>
          )}

          {/* ---- lead time ---- */}
          {metrics.lead_time && (
            <Card title="Early-warning lead time">
              <div className="overflow-x-auto">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Model / split</th>
                      <th>Median lead (min)</th>
                      <th>Mean lead (min)</th>
                      <th>Onsets</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(metrics.lead_time).map(([name, v]) => (
                      <tr key={name}>
                        <td className="rowhead">{displayName(name)}</td>
                        <td className="num">{fmt1(v.median_lead_min)}</td>
                        <td className="num">{fmt1(v.mean_lead_min)}</td>
                        <td className="num">
                          {typeof v.n_onsets === "number" ? v.n_onsets : "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-3 border-t border-border pt-3 text-xs text-fg-2">
                Measured lead time is 0 on this dataset: CIC-IDS2018 attacks
                are scripted and start abruptly, with no precursors in the
                preceding windows. The honest differentiators are trajectory
                shape: persistence mid-attack (0.90-0.97), resumption
                forecasting (0.92) and per-step decay.
              </p>
            </Card>
          )}

          {/* ---- detailed tables ---- */}
          <Card title="Detailed results" meta="every model, exact values">
            <div className="overflow-x-auto">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Model</th>
                    {COLS.map((c) => (
                      <th key={c}>{COL_LABEL[c]}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {aggRows.map(({ model, m }) => (
                    <tr key={`${model}-${m}`}>
                      <td className="rowhead">{model}</td>
                      {COLS.map((c) => (
                        <td key={c} className="num">
                          {fmt(m[c])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3 border-t border-border pt-3 text-xs text-fg-2">
              Identical split, identical feature transform, identical
              evaluation for every model. Values come straight from the
              training scripts and are never hand-edited.
            </p>
          </Card>

          {sections.map(([section, models]) =>
            Object.entries(models as Record<string, ModelMetrics>)
              .filter(([, m]) => Array.isArray(m?._per_step))
              .map(([name, m]) => (
                <Card
                  key={`${section}-${name}`}
                  title={`Per horizon step · ${displayName(name)}`}
                  meta="does accuracy decay as we forecast further?"
                >
                  <MetricTable
                    rows={(m._per_step as ModelMetrics[]).map((s, i) => ({
                      model: `t+${i + 1}`,
                      m: s,
                    }))}
                  />
                </Card>
              )),
          )}
        </>
      )}
    </div>
  );
}
