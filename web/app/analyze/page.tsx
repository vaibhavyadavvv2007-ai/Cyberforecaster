"use client";

import { useRef, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type UploadAnalysis, type UploadTrajectoryPoint } from "@/lib/api";
import { CHART } from "@/lib/chartTheme";
import { Badge, Card, PeakGauge } from "@/components/ui";
import { DecisionSupportPanel } from "@/components/DecisionSupportPanel";
import { EvidencePanel } from "@/components/EvidencePanel";

/*
  Upload analysis — PCAP/PCAPNG or flow CSV in, the full Phase 9–11 stack
  out: trajectory, latest forecast, MC uncertainty, evidence and decision
  support. Every panel renders backend numbers verbatim; the page's only
  job is layout and honest empty states.
*/

const FMT_TONE = {
  pcap: "green",
  pcapng: "green",
  csv: "blue",
} as const;

function fmtLabel(p: UploadTrajectoryPoint): string {
  if (typeof p.ts === "number") {
    return new Date(p.ts * 1000).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }
  if (typeof p.ts === "string") {
    const d = new Date(p.ts);
    return isNaN(d.getTime()) ? p.ts : d.toLocaleTimeString();
  }
  return "";
}

export default function AnalyzePage() {
  const [analysis, setAnalysis] = useState<UploadAnalysis | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  async function onFile(file: File | null) {
    if (!file) return;
    setBusy(true);
    setError(null);
    setFileName(file.name);
    try {
      const out = await api.analyzeUpload(file);
      setAnalysis(out);
    } catch (e) {
      setAnalysis(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const latest = analysis?.latest ?? null;
  const det = analysis?.detection ?? null;
  const unc = analysis?.uncertainty ?? null;
  const tripped = latest !== null && latest.peak >= latest.threshold;

  const chartData =
    analysis?.trajectory.map((t) => ({
      label: fmtLabel(t),
      peak: t.peak,
    })) ?? [];

  return (
    <div className="space-y-6">
      {/* ---- upload control ---- */}
      <section className="border-b border-border pb-5">
        <div className="flex flex-wrap items-center justify-between gap-x-8 gap-y-4">
          <div className="flex items-center gap-4">
            <div>
              <div className="text-sm font-semibold text-fg">
                Analyze a capture or flow export
              </div>
              <div className="mono mt-0.5 text-xs text-fg-2">
                PCAP / PCAPNG or flow CSV (CIC-style or generic) · max 100 MB ·
                detected by content, never by filename
              </div>
            </div>
          </div>
          <input
            ref={inputRef}
            type="file"
            className="hidden"
            accept=".pcap,.pcapng,.csv,.bin"
            onChange={(e) => onFile(e.target.files?.[0] ?? null)}
          />
          <button
            onClick={() => inputRef.current?.click()}
            disabled={busy}
            className="rounded-md bg-amber px-5 py-2.5 text-sm font-semibold text-bg transition-colors hover:bg-amber/90 active:translate-y-px disabled:opacity-50"
          >
            {busy ? "Analyzing…" : "Choose file"}
          </button>
        </div>
        {fileName && !busy && !error && (
          <p className="mono mt-3 border-t border-border pt-3 text-xs text-fg-2">
            {fileName}
          </p>
        )}
      </section>

      {error && (
        <section className="rounded-lg border border-red/25 bg-red/10 p-4">
          <p className="text-sm font-semibold text-red">Analysis failed</p>
          <p className="mt-1 text-sm text-fg">{error}</p>
          <p className="mt-1 text-xs text-fg-2">
            Unknown-schema files need their columns mapped before they can be
            windowed — the system never guesses a schema.
          </p>
        </section>
      )}

      {busy && (
        <section className="rounded-lg border border-border bg-surface p-6">
          <p className="text-sm text-fg-2">
            Detecting schema, windowing traffic and running the forecaster per
            anchor…
          </p>
        </section>
      )}

      {analysis && (
        <div className="rise-in space-y-6">
          {/* ---- detection card ---- */}
          {det && (
            <Card
              title="Detected input"
              meta={`${analysis.n_flows_or_packets.toLocaleString()} rows · ${analysis.n_windows} × ${analysis.bin_secs}s windows · ${analysis.n_forecasts} forecasts`}
            >
              <div className="flex flex-wrap items-center gap-3">
                <Badge tone={FMT_TONE[det.format]} className="px-3 py-1 text-sm">
                  {det.format.toUpperCase()}
                </Badge>
                {det.style && <span className="text-sm text-fg-2">{det.style}</span>}
                <span className="mono text-xs text-fg-3">
                  detection confidence {(det.confidence * 100).toFixed(0)}%
                </span>
              </div>
              <div className="mono mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-fg-3">
                <span>matched: {det.matched.join(", ") || "—"}</span>
                {det.missing.length > 0 && (
                  <span>missing: {det.missing.join(", ")}</span>
                )}
              </div>
              {analysis.unavailable_features.length > 0 && (
                <p className="mt-3 border-t border-border pt-3 text-xs text-fg-2">
                  Features this source cannot provide (reported, never filled
                  with fake zeros):{" "}
                  <span className="mono text-fg-3">
                    {analysis.unavailable_features.join(", ")}
                  </span>
                </p>
              )}
            </Card>
          )}

          {/* ---- latest forecast ---- */}
          {latest && (
            <section className="rounded-lg border border-border bg-surface">
              <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-border px-6 py-3.5">
                <h2 className="text-[15px] font-semibold tracking-tight text-fg">
                  Forecast at end of capture
                </h2>
                {unc && (
                  <span className="mono text-xs text-fg-2">
                    MC dropout · T={unc.T} · band {unc.confidence}
                  </span>
                )}
              </div>
              <div className="flex flex-wrap items-end gap-x-8 gap-y-4 p-6">
                <div>
                  <div className="flex flex-wrap items-end gap-x-5 gap-y-2">
                    <div
                      className={`text-[72px] font-semibold leading-none tracking-[-0.02em] tabular-nums ${
                        tripped ? "text-red" : "text-fg"
                      }`}
                    >
                      {(latest.peak * 100).toFixed(0)}
                      <span className="align-top text-3xl font-medium text-fg-2">%</span>
                    </div>
                    {unc && (
                      <div className="pb-1.5">
                        <Badge
                          tone={
                            unc.confidence === "HIGH"
                              ? "green"
                              : unc.confidence === "MEDIUM"
                                ? "amber"
                                : "red"
                          }
                          className="px-3 py-1 text-sm"
                        >
                          {unc.confidence} confidence
                        </Badge>
                      </div>
                    )}
                  </div>
                  <p className="mt-3 text-sm text-fg-2">
                    Probability of attack progression — peak over the next{" "}
                    {latest.probs.length} windows
                    {latest.crossing_step != null
                      ? ` · threshold crossed at step ${latest.crossing_step}`
                      : " · threshold not crossed"}
                  </p>
                  <PeakGauge peak={latest.peak} threshold={latest.threshold} className="mt-4 max-w-md" />
                  {unc && (
                    <p className="mono mt-3 text-xs text-fg-3">
                      max σ across steps {unc.max_std.toFixed(3)} · stage votes{" "}
                      {Object.entries(unc.stage_votes)
                        .sort((a, b) => b[1] - a[1])
                        .slice(0, 3)
                        .map(([s, v]) => `${s || "none"}:${v}`)
                        .join(" · ")}
                    </p>
                  )}
                </div>
                <div className="pb-1">
                  <div className="label mb-1.5">Predicted stage</div>
                  <div className="text-lg font-semibold text-fg">
                    {latest.stage || "-"}
                  </div>
                </div>
              </div>
            </section>
          )}

          {/* ---- trajectory chart ---- */}
          {chartData.length > 1 && (
            <section className="rounded-lg border border-border bg-surface">
              <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-border px-5 py-3.5">
                <h2 className="text-[15px] font-semibold text-fg">
                  Forecast trajectory through the capture
                </h2>
                <span className="mono text-xs text-fg-2">
                  peak next-horizon probability per anchor window
                </span>
              </div>
              <div className="p-4">
                <div className="h-60">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData} margin={{ top: 10, right: 12, bottom: 0, left: -6 }}>
                      <CartesianGrid stroke={CHART.grid} vertical={false} />
                      <XAxis
                        dataKey="label"
                        stroke={CHART.grid}
                        tick={{ fill: CHART.tick, fontSize: 10, fontFamily: "JetBrains Mono" }}
                        tickLine={false}
                        interval="preserveStartEnd"
                        minTickGap={56}
                      />
                      <YAxis
                        domain={[0, 1]}
                        stroke={CHART.grid}
                        tick={{ fill: CHART.tick, fontSize: 10, fontFamily: "JetBrains Mono" }}
                        tickLine={false}
                        tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
                        width={44}
                      />
                      <Tooltip
                        cursor={{ stroke: CHART.tick, strokeDasharray: "2 3" }}
                        contentStyle={{
                          background: CHART.tooltipBg,
                          border: `1px solid ${CHART.tooltipBorder}`,
                          borderRadius: 8,
                          fontSize: 12,
                          fontFamily: "JetBrains Mono",
                        }}
                        labelStyle={{ color: CHART.neutral }}
                        formatter={(value) => [
                          typeof value === "number" ? `${(value * 100).toFixed(1)}%` : String(value ?? "-"),
                          "peak forecast",
                        ]}
                      />
                      <ReferenceLine
                        y={latest?.threshold ?? 0.561}
                        stroke={CHART.red}
                        strokeDasharray="4 4"
                        label={{
                          value: `threshold ${Math.round((latest?.threshold ?? 0.561) * 100)}%`,
                          position: "insideTopLeft",
                          fill: CHART.red,
                          fontSize: 10,
                          fontFamily: "JetBrains Mono",
                          dy: -2,
                        }}
                      />
                      <Line
                        type="monotone"
                        dataKey="peak"
                        stroke={CHART.amber}
                        strokeWidth={2}
                        dot={{ r: 2.5, fill: CHART.amber, strokeWidth: 0 }}
                        connectNulls={false}
                        isAnimationActive={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
                <p className="mt-2 text-xs text-fg-2">
                  Each point is a separate forecast made from the 10 windows
                  ending at that timestamp — the model reacting as the capture
                  progresses, not one prediction stretched over time.
                </p>
              </div>
            </section>
          )}

          {/* ---- evidence + decision support ---- */}
          {analysis.evidence && analysis.evidence.length > 0 && (
            <EvidencePanel rows={analysis.evidence} />
          )}
          {analysis.decision_support && (
            <DecisionSupportPanel ds={analysis.decision_support} />
          )}
        </div>
      )}

      {!analysis && !busy && !error && (
        <section className="rounded-lg border border-dashed border-border bg-surface p-12">
          <div className="mx-auto max-w-md text-center">
            <p className="text-sm font-semibold text-fg">
              Offline analysis, same pipeline as live
            </p>
            <p className="mt-1.5 text-sm text-fg-2">
              Upload a packet capture or a flow export from any tool. The file
              is schema-detected by its bytes, windowed exactly like the
              training data, and forecast per anchor with uncertainty,
              evidence-based explanation and defender decision support.
            </p>
          </div>
        </section>
      )}
    </div>
  );
}
