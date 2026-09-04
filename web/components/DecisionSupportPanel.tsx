"use client";

import { Badge, Card, type Tone } from "@/components/ui";
import type { DecisionSupport } from "@/lib/api";

/*
  Decision-support panel — renders the Phase 10 engine record verbatim.
  Every number shown came from the backend (forecast facts, MC band, STIX
  mitigations); this component adds no claims of its own.
*/

const LEVEL_TONE: Record<DecisionSupport["level"], Tone> = {
  MONITOR: "green",
  INVESTIGATE: "amber",
  "CONTAINMENT REVIEW": "red",
  ESCALATE: "red",
};

const PRIORITY_TONE: Record<string, Tone> = { P1: "red", P2: "amber", P3: "gray" };

function fmtPct(v: number): string {
  return `${(v * 100).toFixed(0)}%`;
}

export function DecisionSupportPanel({ ds }: { ds: DecisionSupport }) {
  const f = ds.level_facts;
  const techniques = ds.mitre.techniques ?? [];
  return (
    <Card
      title="Defender decision support"
      meta={`peak ${fmtPct(f.peak)} vs threshold ${fmtPct(f.threshold)} · ${f.steps_above} steps above · MC band ${f.confidence}`}
    >
      <div className="space-y-5">
        <div className="flex flex-wrap items-center gap-3">
          <Badge tone={LEVEL_TONE[ds.level]} className="px-3 py-1 text-sm">
            {ds.level}
          </Badge>
          <span className="text-sm text-fg-2">{ds.level_why}</span>
        </div>

        <p className="rounded-md border border-border bg-surface-2 px-4 py-3 text-sm text-fg">
          {ds.guidance}
        </p>

        {/* ranked actions */}
        <div>
          <div className="label mb-2">Recommended investigation actions</div>
          <ol className="space-y-2.5">
            {ds.recommendations.map((r, i) => (
              <li key={i} className="flex items-start gap-3">
                <span className="mono mt-0.5 w-5 shrink-0 text-right text-xs text-fg-3">
                  {i + 1}.
                </span>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={PRIORITY_TONE[r.priority] ?? "gray"}>{r.priority}</Badge>
                    <span className="label">
                      {r.source}
                      {r.refs.length > 0 && ` · ${r.refs.join(", ")}`}
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-fg">{r.action}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>

        {/* MITRE enrichment — only when the STIX knowledge base is loaded */}
        <div>
          <div className="label mb-2">ATT&amp;CK enrichment</div>
          {ds.mitre.knowledge_base === "unavailable" ? (
            <p className="text-sm text-fg-2">
              MITRE knowledge base unavailable — no techniques are shown rather
              than guessed.
            </p>
          ) : techniques.length === 0 ? (
            <p className="text-sm text-fg-2">
              {ds.mitre.stage
                ? `Predicted stage "${ds.mitre.stage}" has no mapped technique.`
                : "No stage predicted, so no technique mapping."}
            </p>
          ) : (
            <div className="space-y-3">
              {techniques.slice(0, 4).map((t) => (
                <div key={t.id} className="rounded-md border border-border bg-surface-2 px-4 py-3">
                  <div className="flex flex-wrap items-baseline gap-x-2.5">
                    <span className="mono text-xs font-semibold text-blue">{t.id}</span>
                    <span className="text-sm font-medium text-fg">{t.name}</span>
                  </div>
                  {t.mitigations.length > 0 && (
                    <p className="mt-1.5 text-xs text-fg-2">
                      <span className="font-semibold text-fg-2">MITRE mitigations:</span>{" "}
                      {t.mitigations.join(" · ")}
                    </p>
                  )}
                  {t.detection && (
                    <p className="mt-1 text-xs text-fg-2">
                      <span className="font-semibold text-fg-2">Detection:</span> {t.detection}
                    </p>
                  )}
                </div>
              ))}
              <p className="text-xs text-fg-3">source: {ds.mitre.knowledge_base}</p>
            </div>
          )}
        </div>

        <p className="border-t border-border pt-3 text-xs text-fg-3">
          {ds.human_in_loop}
        </p>
      </div>
    </Card>
  );
}
