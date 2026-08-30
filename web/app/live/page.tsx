"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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
import { api, type LiveFeed, type LiveWindow, type RiskLevel } from "@/lib/api";
import { CHART } from "@/lib/chartTheme";
import { Badge, Card, PeakGauge, type Tone } from "@/components/ui";

const RISK_TONE: Record<RiskLevel, Tone> = {
  HIGH: "red",
  ELEVATED: "amber",
  LOW: "green",
};

function fmtClock(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function fmtAgo(ageS: number | null): string {
  if (ageS == null) return "never";
  if (ageS < 60) return `${Math.round(ageS)}s ago`;
  return `${Math.round(ageS / 60)}m ago`;
}

/** Attribution rows: live windows rank the same 18 features as offline. */
const FEATURE_TEXT: Record<string, string> = {
  flow_count: "number of connections",
  bytes_total: "traffic volume",
  pkts_total: "packet volume",
  duration_mean: "connection duration",
  syn_ratio: "connection initiation rate",
  ack_ratio: "acknowledgement behavior",
  fin_ratio: "connection teardown",
  rst_ratio: "connection reset behavior",
  psh_ratio: "push behavior",
  unique_dst_ports: "destination port spread",
  auth_port_share: "remote-access service share",
  unique_dst_ips: "destination host spread",
  unique_src_ips: "source host spread",
  dst_port_entropy: "port distribution entropy",
  iat_mean: "packet inter-arrival timing",
  iat_std: "timing jitter",
  avg_pkt_size: "packet size",
  down_up_ratio: "download/upload balance",
};

function LiveChart({ feed }: { feed: LiveFeed }) {
  const threshold = feed.latest?.threshold ?? 0.561;
  const firstLiveIdx = feed.windows.findIndex((w) => w.source === "live");
  const data = feed.windows.map((w, i) => ({
    label: fmtClock(w.ts),
    seed: w.source === "seed" ? (w.forecast_peak ?? undefined) : undefined,
    live: w.source === "live" ? (w.forecast_peak ?? undefined) : undefined,
    firstLive: i === firstLiveIdx,
  }));
  const anchorLabel = data[firstLiveIdx]?.label;

  return (
    <section className="rounded-lg border border-border bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-border px-5 py-3.5">
        <h2 className="text-[15px] font-semibold text-fg">Live forecast trajectory</h2>
        <span className="mono text-xs text-fg-2">
          peak next-horizon probability per {feed.bin_secs}s window
        </span>
      </div>
      <div className="p-4">
        <div className="h-60">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 10, right: 12, bottom: 0, left: -6 }}>
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
                formatter={(value, name) => {
                  const pct =
                    typeof value === "number" ? `${(value * 100).toFixed(1)}%` : String(value ?? "-");
                  return [pct, name === "seed" ? "Seeded history" : "Live capture"];
                }}
              />
              <ReferenceLine
                y={threshold}
                stroke={CHART.red}
                strokeDasharray="4 4"
                label={{
                  value: `threshold ${Math.round(threshold * 100)}%`,
                  position: "insideTopLeft",
                  fill: CHART.red,
                  fontSize: 10,
                  fontFamily: "JetBrains Mono",
                  dy: -2,
                }}
              />
              {anchorLabel && (
                <ReferenceLine
                  x={anchorLabel}
                  stroke={CHART.neutral}
                  strokeWidth={1}
                  label={{
                    value: "live",
                    position: "top",
                    fill: CHART.neutral,
                    fontSize: 10,
                    fontFamily: "JetBrains Mono",
                    dy: -2,
                  }}
                />
              )}
              <Line
                type="monotone"
                dataKey="seed"
                stroke={CHART.neutral}
                strokeWidth={1.5}
                dot={{ r: 2, fill: CHART.neutral, strokeWidth: 0 }}
                connectNulls={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="live"
                stroke={CHART.amber}
                strokeWidth={2}
                dot={{ r: 2.5, fill: CHART.amber, strokeWidth: 0 }}
                connectNulls={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1">
          <span className="flex items-center gap-2 text-xs text-fg-2">
            <span className="inline-block h-[2px] w-5 rounded-full bg-fg-2" />
            Seeded history (recorded benign)
          </span>
          <span className="flex items-center gap-2 text-xs text-fg-2">
            <span className="inline-block h-[2px] w-5 rounded-full bg-amber" />
            Live capture
          </span>
          <span className="flex items-center gap-2 text-xs text-fg-2">
            <span className="inline-block h-[2px] w-5 rounded-full bg-[repeating-linear-gradient(90deg,#ff6a5f_0_4px,transparent_4px_8px)]" />
            Threshold {Math.round(threshold * 100)}%
          </span>
        </div>
      </div>
    </section>
  );
}

function LatestRow({ w }: { w: LiveWindow }) {
  return (
    <tr>
      <td className="mono num">{fmtClock(w.ts)}</td>
      <td className="mono num">{Math.round(w.flow_count)}</td>
      <td className="mono num">{Math.round(w.pkts_total)}</td>
      <td className="mono num">{w.syn_ratio.toFixed(2)}</td>
      <td className="mono num">{Math.round(w.unique_dst_ports)}</td>
      <td>{w.rule_stage || <span className="text-fg-3">no rule matched</span>}</td>
      <td>
        {w.source === "seed" ? (
          <Badge tone="gray">seed</Badge>
        ) : (
          <Badge tone="green">live</Badge>
        )}
      </td>
    </tr>
  );
}

export default function LivePage() {
  const [feed, setFeed] = useState<LiveFeed | null>(null);
  const [busy, setBusy] = useState(false);
  const [startMsg, setStartMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const f = await api.liveFeed();
      setFeed(f);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
    timer.current = setInterval(refresh, 5000);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [refresh]);

  async function start() {
    setBusy(true);
    setStartMsg(null);
    try {
      const r = await api.liveStart();
      setStartMsg(
        r.ok
          ? r.already_running
            ? "Capture already running"
            : `Capture started · ${r.seeded_windows ?? 0} seeded windows · model ${r.model_ready ? "loaded" : "unavailable"}`
          : `Capture failed: ${r.error ?? "unknown error"}`,
      );
      await refresh();
    } catch (e) {
      setStartMsg(`Capture failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    setBusy(true);
    try {
      await api.liveStop();
      setStartMsg("Capture stopped");
      await refresh();
    } catch (e) {
      setStartMsg(`Stop failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  const sensor = feed?.sensor;
  const latest = feed?.latest ?? null;
  const running = sensor?.running ?? false;
  const tripped = latest !== null && latest.peak >= latest.threshold;
  const why = latest?.why ?? [];
  const maxImp = Math.max(...why.map((w) => w.importance), 1e-9);

  return (
    <div className="space-y-6">
      {/* ---- capture control (not a card: controls sit on the ground) ---- */}
      <section className="border-b border-border pb-5">
        <div className="flex flex-wrap items-center justify-between gap-x-8 gap-y-4">
          <div className="flex items-center gap-4">
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                running ? "bg-green" : "bg-fg-3"
              }`}
              aria-hidden="true"
            />
            <div>
              <div className="text-sm font-semibold text-fg">
                {running ? "Capturing live network traffic" : "Capture stopped"}
              </div>
              <div className="mono mt-0.5 text-xs text-fg-2">
                {running
                  ? `${sensor?.iface ?? "default interface"} · ${sensor?.packets_seen ?? 0} packets · last packet ${fmtAgo(sensor?.last_packet_age_s ?? null)}`
                  : "Start capture to monitor this machine's network in real time"}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-4">
            {running && (
              <div className="text-right">
                <div className="label">Next window closes</div>
                <div className="mono mt-1 text-sm text-fg">
                  {sensor?.bin_remaining_s?.toFixed(0) ?? "-"}s
                </div>
              </div>
            )}
            {running ? (
              <button
                onClick={stop}
                disabled={busy}
                className="rounded-md border border-border bg-surface-2 px-5 py-2.5 text-sm font-semibold text-fg transition-colors hover:border-red/40 hover:text-red active:translate-y-px disabled:opacity-50"
              >
                Stop capture
              </button>
            ) : (
              <button
                onClick={start}
                disabled={busy}
                className="rounded-md bg-amber px-5 py-2.5 text-sm font-semibold text-bg transition-colors hover:bg-amber/90 active:translate-y-px disabled:opacity-50"
              >
                {busy ? "Starting…" : "Start live capture"}
              </button>
            )}
          </div>
        </div>
        {startMsg && (
          <p className={`mt-3 border-t border-border pt-3 text-xs ${startMsg.includes("failed") ? "text-red" : "text-fg-2"}`}>
            {startMsg}
          </p>
        )}
      </section>

      {error && (
        <section className="rounded-lg border border-red/25 bg-red/10 p-4">
          <p className="text-sm font-medium text-red">{error}</p>
        </section>
      )}

      {sensor?.error && !running && (
        <section className="rounded-lg border border-red/25 bg-red/10 p-4">
          <p className="text-sm font-medium text-red">Capture error: {sensor.error}</p>
          <p className="mt-1 text-xs text-fg-2">
            Npcap must be installed on this machine (one-time admin install).
          </p>
        </section>
      )}

      {feed && !running && feed.n_seed + feed.n_live === 0 && (
        <section className="rounded-lg border border-dashed border-border bg-surface p-12">
          <div className="mx-auto max-w-md text-center">
            <p className="text-sm font-semibold text-fg">Live monitor ready</p>
            <p className="mt-1.5 text-sm text-fg-2">
              Starting capture pre-loads recorded benign history so the
              forecaster has its 10-window context immediately. Every window
              after that is real traffic from this network, scored live.
            </p>
          </div>
        </section>
      )}

      {latest && (
        <div className="rise-in space-y-6">
          {/* ---- current forecast ---- */}
          <section className="rounded-lg border border-border bg-surface">
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-border px-6 py-3.5">
              <h2 className="text-[15px] font-semibold tracking-tight text-fg">Current forecast</h2>
              <span className="mono text-xs text-fg-2">
                {latest.n_history} windows of history · {feed?.seq_len} needed
              </span>
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
                  <div className="pb-1.5">
                    <Badge tone={RISK_TONE[latest.level]} className="px-3 py-1 text-sm">
                      {latest.level} risk
                    </Badge>
                  </div>
                </div>
                <p className="mt-3 text-sm text-fg-2">
                  Probability of attack progression — peak over the next{" "}
                  {latest.probs.length} windows
                </p>
                <PeakGauge peak={latest.peak} threshold={latest.threshold} className="mt-4 max-w-md" />
              </div>
              <div className="pb-1">
                <div className="label mb-1.5">Predicted stage</div>
                <div className="text-lg font-semibold text-fg">
                  {latest.stage || "-"}
                </div>
                <div className="mt-1 text-xs text-fg-3">
                  rule engine: {latest.rule_stage || "no rule matched"}
                </div>
              </div>
            </div>
          </section>

          {/* ---- crossing banner ---- */}
          {tripped && (
            <section className="flex gap-3 rounded-lg border border-red/25 bg-red/10 p-4">
              <svg
                className="mt-0.5 h-4.5 w-4.5 shrink-0 text-red"
                viewBox="0 0 20 20"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.75"
                aria-hidden="true"
              >
                <path d="M10 7v4m0 3v.01" strokeLinecap="round" />
                <path d="M8.6 3.2 2.5 14a1.5 1.5 0 0 0 1.3 2.2h12.4a1.5 1.5 0 0 0 1.3-2.2L11.4 3.2a1.6 1.6 0 0 0-2.8 0Z" strokeLinejoin="round" />
              </svg>
              <div>
                <p className="text-sm font-semibold text-red">
                  Live forecast threshold crossed
                </p>
                <p className="mt-0.5 text-sm text-fg">
                  {(latest.peak * 100).toFixed(0)}% probability of attack
                  progression{latest.stage ? ` to ${latest.stage}` : ""} over the
                  next {latest.probs.length} windows.
                  {latest.rule_stage
                    ? ` Independent rule engine agrees: ${latest.rule_stage}.`
                    : ""}
                </p>
                <p className="mt-0.5 text-xs text-fg-2">
                  Model forecast on live traffic · not confirmed malicious
                  activity · decision support only
                </p>
              </div>
            </section>
          )}

          {feed && <LiveChart feed={feed} />}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {/* ---- attribution ---- */}
            <Card title="Why this forecast?" meta="Integrated Gradients on live windows">
              {why.length === 0 ? (
                <p className="text-sm text-fg-2">
                  Attribution unavailable for the latest window.
                </p>
              ) : (
                <div className="space-y-3">
                  <p className="text-sm text-fg">
                    {FEATURE_TEXT[why[0].feature] ?? why[0].feature}
                    {why[1] ? ` and ${FEATURE_TEXT[why[1].feature] ?? why[1].feature}` : ""}{" "}
                    contributed most to this forecast.
                  </p>
                  {why.map((w) => (
                    <div key={w.feature}>
                      <div className="flex items-baseline justify-between gap-3">
                        <span className="mono text-xs text-fg-2">{w.feature}</span>
                        <span className="mono text-xs text-fg-3">
                          {w.importance.toFixed(3)}
                        </span>
                      </div>
                      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-2">
                        <div
                          className="h-full rounded-full bg-blue"
                          style={{ width: `${Math.max((w.importance / maxImp) * 100, 2)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            {/* ---- event log ---- */}
            <Card title="Events" meta="threshold crossings, newest first">
              {feed && feed.events.length === 0 ? (
                <p className="text-sm text-fg-2">
                  No threshold crossings yet. Events appear the moment a live
                  forecast crosses the alert threshold.
                </p>
              ) : (
                <ul className="divide-y divide-border/60">
                  {feed &&
                    [...feed.events].reverse().map((e, i) => (
                      <li key={`${e.bin_id}-${i}`} className="flex items-center justify-between gap-3 py-2.5 first:pt-0 last:pb-0">
                        <span className="mono text-xs text-fg-2">
                          {new Date(e.ts * 1000).toLocaleTimeString()}
                        </span>
                        <span className="flex items-center gap-2">
                          <Badge tone={RISK_TONE[e.level]}>{e.level}</Badge>
                          <span className="mono text-xs text-fg">
                            peak {(e.peak * 100).toFixed(0)}%
                          </span>
                          {e.stage && (
                            <span className="text-xs text-fg-2">{e.stage}</span>
                          )}
                        </span>
                      </li>
                    ))}
                </ul>
              )}
            </Card>
          </div>

          {/* ---- window table ---- */}
          <Card
            title="Observed windows"
            meta={`${feed?.n_seed ?? 0} seeded · ${feed?.n_live ?? 0} live`}
            bodyClassName="p-0"
          >
            <div className="overflow-x-auto">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Window</th>
                    <th>Flows</th>
                    <th>Packets</th>
                    <th>SYN ratio</th>
                    <th>Ports</th>
                    <th>Rule engine</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {feed && [...feed.windows].reverse().slice(0, 12).map((w) => (
                    <LatestRow key={`${w.bin_id}-${w.ts}`} w={w} />
                  ))}
                </tbody>
              </table>
            </div>
            <p className="border-t border-border px-5 py-3 text-xs text-fg-2">
              Seeded rows are recorded benign history replayed for model
              context; live rows are traffic captured from this network. Empty
              windows mean zero matching packets in that period.
            </p>
          </Card>
        </div>
      )}

      {feed && !latest && running && (
        <section className="rounded-lg border border-border bg-surface p-6">
          <p className="text-sm text-fg">
            Collecting history: {feed.n_seed + feed.n_live} of {feed.seq_len}{" "}
            windows
          </p>
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-surface-2">
            <div
              className="h-full rounded-full bg-amber transition-all"
              style={{
                width: `${Math.min(((feed.n_seed + feed.n_live) / feed.seq_len) * 100, 100)}%`,
              }}
            />
          </div>
          <p className="mt-2 text-xs text-fg-2">
            The forecaster needs {feed.seq_len} windows before it can predict.
          </p>
        </section>
      )}
    </div>
  );
}
