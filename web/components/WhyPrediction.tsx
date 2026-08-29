"use client";

import type { Forecast } from "@/lib/api";

/**
 * Why this prediction: per-feature attribution (Integrated Gradients,
 * |attribution| summed over the input sequence) ranked for a human, with
 * a plain-language summary derived from the actual top features — never
 * invented.
 */
const FEATURE_TEXT: Record<string, string> = {
  rst_ratio: "connection reset behavior",
  iat_mean: "packet inter-arrival timing",
  iat_std: "packet inter-arrival variability",
  avg_pkt_size: "average packet size",
  down_up_ratio: "download/upload volume asymmetry",
  flow_count: "connection volume",
  fin_ratio: "connection teardown patterns",
  syn_ratio: "connection initiation patterns",
  ack_ratio: "acknowledgment patterns",
  psh_ratio: "push flag frequency",
  bytes_total: "total traffic volume",
  pkts_total: "total packet count",
  duration_mean: "connection duration",
  unique_dst_ips: "distinct destination hosts",
  unique_src_ips: "distinct source hosts",
  unique_dst_ports: "destination port spread",
  auth_port_share: "authentication-port traffic share",
  dst_port_entropy: "destination port entropy",
};

function phrase(feature: string): string {
  return FEATURE_TEXT[feature] ?? feature.replace(/_/g, " ");
}

function summarize(why: { feature: string; importance: number }[]): string | null {
  if (why.length === 0) return null;
  const top = why[0];
  const second = why[1];
  const s = second
    ? `${cap(phrase(top.feature))} and ${phrase(second.feature)} contributed most to this forecast.`
    : `${cap(phrase(top.feature))} contributed most to this forecast.`;
  return s;
}

function cap(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function WhyPrediction({ forecast }: { forecast: Forecast }) {
  const why = forecast.why ?? [];
  const max = Math.max(...why.map((w) => w.importance), 1e-9);
  const summary = why.length > 0 ? summarize(why) : null;

  return (
    <section className="rounded-lg border border-border bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-border px-5 py-3.5">
        <h2 className="text-[15px] font-semibold text-fg">Why this prediction?</h2>
        <span className="mono text-xs text-fg-2">
          {why.length} features ranked
        </span>
      </div>

      {why.length === 0 ? (
        <div className="p-5">
          <p className="text-sm text-fg-2">
            {forecast.why_note
              ? `Attribution unavailable: ${forecast.why_note}`
              : "No attribution available for this prediction."}
          </p>
        </div>
      ) : (
        <div className="p-5">
          <ul className="space-y-2.5">
            {why.map((w) => (
              <li key={w.feature} className="flex items-center gap-3">
                <div
                  className="mono w-36 shrink-0 truncate text-xs text-fg-2"
                  title={w.feature}
                >
                  {w.feature}
                </div>
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
                  <div
                    className="h-full rounded-full bg-blue"
                    style={{ width: `${Math.max((w.importance / max) * 100, 2)}%` }}
                  />
                </div>
                <div className="mono w-10 shrink-0 text-right text-xs text-fg-2">
                  {w.importance.toFixed(2)}
                </div>
              </li>
            ))}
          </ul>

          {summary && (
            <p className="mt-4 border-t border-border pt-3 text-sm text-fg-2">
              {summary}
            </p>
          )}
          <p className="mt-1.5 text-xs text-fg-3">
            Integrated Gradients attribution, |contribution| summed over the
            input sequence.
          </p>
        </div>
      )}
    </section>
  );
}
