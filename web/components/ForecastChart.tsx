"use client";

import {
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Timeline } from "@/lib/api";
import { CHART } from "@/lib/chartTheme";

/**
 * Observed vs forecast. Left of "Now" is observed ground truth (gray);
 * right of it is model output (amber) over a subtly tinted forecast
 * region. The alert threshold is a red dashed line. The model never
 * sees the observed trace to the left.
 */
export function ForecastChart({ timeline }: { timeline: Timeline }) {
  const data = timeline.points.map((p) => ({
    label: new Date(p.ts).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    }),
    observed: p.observed,
    forecast: p.forecast,
  }));
  const anchorLabel = data[timeline.anchor_index]?.label ?? "";
  const lastLabel = data[data.length - 1]?.label ?? "";
  const thresholdPct = `${Math.round(timeline.threshold * 100)}%`;

  return (
    <section className="rounded-lg border border-border bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-border px-5 py-3.5">
        <h2 className="text-[15px] font-semibold text-fg">
          Progression over time
        </h2>
        <span className="mono text-xs text-fg-2">
          forecast origin:{" "}
          {new Date(timeline.anchor_ts).toLocaleString([], {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </div>

      <div className="p-4">
        <div className="h-60">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data} margin={{ top: 10, right: 12, bottom: 0, left: -6 }}>
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
                  return [pct, name === "observed" ? "Observed" : "Forecast"];
                }}
              />

              {/* forecast region — tinted so left/right need no legend */}
              <ReferenceArea
                x1={anchorLabel}
                x2={lastLabel}
                fill="rgba(255, 178, 36, 0.06)"
                stroke="none"
                label={{
                  value: "forecast",
                  position: "insideTopRight",
                  fill: CHART.amber,
                  fontSize: 10,
                  fontFamily: "JetBrains Mono",
                  dy: 4,
                }}
              />
              {/* "now" divider */}
              <ReferenceLine
                x={anchorLabel}
                stroke={CHART.neutral}
                strokeWidth={1}
                label={{
                  value: "now",
                  position: "top",
                  fill: CHART.neutral,
                  fontSize: 10,
                  fontFamily: "JetBrains Mono",
                  dy: -2,
                }}
              />
              {/* alert threshold */}
              <ReferenceLine
                y={timeline.threshold}
                stroke={CHART.red}
                strokeDasharray="4 4"
                label={{
                  value: `threshold ${thresholdPct}`,
                  position: "insideTopLeft",
                  fill: CHART.red,
                  fontSize: 10,
                  fontFamily: "JetBrains Mono",
                  dy: -2,
                }}
              />

              <Line
                type="monotone"
                dataKey="observed"
                stroke={CHART.neutral}
                strokeWidth={1.5}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="forecast"
                stroke={CHART.amber}
                strokeWidth={2}
                dot={{ r: 2.5, fill: CHART.amber, strokeWidth: 0 }}
                connectNulls={false}
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>

        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1">
          <span className="flex items-center gap-2 text-xs text-fg-2">
            <span className="inline-block h-[2px] w-5 rounded-full bg-fg-2" />
            Observed (ground truth)
          </span>
          <span className="flex items-center gap-2 text-xs text-fg-2">
            <span className="inline-block h-[2px] w-5 rounded-full bg-amber" />
            Forecast (model output)
          </span>
          <span className="flex items-center gap-2 text-xs text-fg-2">
            <span className="inline-block h-[2px] w-5 rounded-full bg-[repeating-linear-gradient(90deg,#ff6a5f_0_4px,transparent_4px_8px)]" />
            Threshold {thresholdPct}
          </span>
        </div>
      </div>
    </section>
  );
}
