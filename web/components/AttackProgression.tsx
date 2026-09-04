"use client";

import type { Forecast } from "@/lib/api";
import { Badge } from "@/components/ui";

/**
 * ATT&CK progression, read like an analyst: stages before the predicted
 * one are marked passed, the predicted stage is highlighted with its
 * technique ID and peak probability, later stages stay open. DoS sits
 * outside the chain on purpose (ATT&CK places flooding under Impact).
 */
const CHAIN = [
  { name: "Reconnaissance", tag: "TA0043" },
  { name: "Initial Access", tag: "TA0001" },
  { name: "Lateral Movement", tag: "TA0008" },
  { name: "Command & Control", tag: "TA0011" },
  { name: "Exfiltration", tag: "TA0010" },
];

function CheckIcon() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4 text-fg-2" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden="true">
      <path d="m3 8.5 3.2 3.2L13 5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ArrowIcon() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4 text-amber" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden="true">
      <path d="M2 8h11m0 0-4-4m4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function CircleIcon() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4 text-fg-3" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden="true">
      <circle cx="8" cy="8" r="5" />
    </svg>
  );
}

export function AttackProgression({ forecast }: { forecast: Forecast }) {
  const predictedIdx = CHAIN.findIndex((c) => c.name === forecast.stage);

  return (
    <section className="rounded-lg border border-border bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-border px-5 py-3.5">
        <h2 className="text-[15px] font-semibold text-fg">ATT&amp;CK progression</h2>
        <span className="mono text-xs text-fg-2">
          horizon: {forecast.probs.length} windows
        </span>
      </div>

      <ul className="divide-y divide-border/60">
        {CHAIN.map((c, i) => {
          const predicted = i === predictedIdx;
          const passed = predictedIdx >= 0 && i < predictedIdx;
          return (
            <li
              key={c.name}
              className={`flex items-center gap-3 px-5 py-3 ${
                predicted ? "bg-amber/5" : ""
              }`}
            >
              {passed ? <CheckIcon /> : predicted ? <ArrowIcon /> : <CircleIcon />}
              <div className="min-w-0 flex-1">
                <div
                  className={`text-sm ${
                    predicted ? "font-semibold text-fg" : passed ? "text-fg" : "text-fg-2"
                  }`}
                >
                  {c.name}
                </div>
              </div>
              <span className="mono text-xs text-fg-3">{c.tag}</span>
              {predicted && (
                <>
                  <span className="mono text-xs text-amber">
                    peak {(forecast.peak * 100).toFixed(0)}%
                  </span>
                  <Badge tone="amber">Predicted</Badge>
                </>
              )}
            </li>
          );
        })}
      </ul>

      {(forecast.stage === "DoS" || predictedIdx < 0) && (
        <p className="border-t border-border px-5 py-3 text-xs text-fg-2">
          {forecast.stage === "DoS"
            ? "Predicted stage DoS is outside this chain (ATT&CK classifies flooding under Impact)."
            : "No chain stage predicted for this horizon."}
        </p>
      )}

      {forecast.future_steps && forecast.future_steps.length > 0 && (
        <div className="border-t border-border px-5 py-4">
          <div className="mb-2 flex items-baseline justify-between gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-2">
              Per-step stage (state rollout)
            </h3>
            <span className="mono text-xs text-fg-3">V3 world model</span>
          </div>
          <ol className="flex flex-wrap gap-2">
            {forecast.future_steps.map((fs) => (
              <li
                key={fs.step}
                className="rounded border border-border bg-surface-2 px-2.5 py-1.5"
                title={fs.movers
                  .map((m) => `${m.feature} ${m.direction} (${m.delta})`)
                  .join(", ")}
              >
                <div className="mono text-xs text-fg-3">T+{fs.step}</div>
                <div className="text-xs font-medium text-fg">{fs.stage || "—"}</div>
                <div className="mono text-xs text-fg-2">
                  {(fs.risk * 100).toFixed(0)}% risk
                </div>
              </li>
            ))}
          </ol>
          <p className="mt-2 text-xs leading-relaxed text-fg-3">
            Stage and risk at each step are decoded from the model&rsquo;s
            forecast network state S(t+k) — hover a chip for the state features
            driving it.
          </p>
        </div>
      )}

      <p className="flex flex-wrap items-baseline gap-x-2 border-t border-border px-5 py-3 text-xs">
        <span className="text-fg-2">Independent rule engine:</span>
        <span className="mono text-fg-2">
          {forecast.rule_stage || "no rule matched"}
        </span>
      </p>
    </section>
  );
}
