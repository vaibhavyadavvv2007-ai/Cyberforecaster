"use client";

import { Badge, Card, type Tone } from "@/components/ui";
import type { UploadEvidenceRow } from "@/lib/api";

/*
  Evidence panel — Phase 9 evidence engine output, rendered verbatim.
  Every observed value, benign mean, p99 and z came from the backend; the
  panel computes nothing, so a number on screen is always traceable to the
  benign baseline artifact (TRAIN-split windows only).
*/

const DIRECTION_TONE: Record<UploadEvidenceRow["direction"], Tone> = {
  elevated: "red",
  suppressed: "blue",
  normal: "gray",
};

function fmt(v: number): string {
  const a = Math.abs(v);
  if (a === 0) return "0";
  if (a >= 1000) return v.toFixed(0);
  if (a >= 1) return v.toFixed(2);
  return v.toPrecision(3);
}

function fmtZ(z: number): string {
  return `${z >= 0 ? "+" : ""}${z.toFixed(1)}`;
}

export function EvidencePanel({ rows }: { rows: UploadEvidenceRow[] }) {
  // Max |attribution| across rows, so bars are comparable within this panel.
  const maxAttr = Math.max(...rows.map((r) => Math.abs(r.attribution)), 1e-9);

  return (
    <Card
      title="Why — feature evidence"
      meta={`observed vs benign TRAIN baseline · ${rows.length} features`}
    >
      <div className="space-y-3">
        {rows.map((r) => {
          const width = Math.round((Math.abs(r.attribution) / maxAttr) * 100);
          const elevated = r.direction === "elevated";
          return (
            <div key={r.feature} className="rounded-md border border-border bg-surface-2 px-4 py-3">
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <div className="flex flex-wrap items-baseline gap-x-2.5">
                  <span className="mono text-xs font-semibold text-fg">{r.feature}</span>
                  <span className="text-xs text-fg-3">{r.description}</span>
                </div>
                <Badge tone={DIRECTION_TONE[r.direction]}>{r.direction}</Badge>
              </div>

              <div className="mono mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-fg-2">
                <span>
                  observed <span className="text-fg">{fmt(r.observed)}</span>
                </span>
                <span>
                  benign mean <span className="text-fg">{fmt(r.benign_mean)}</span>
                </span>
                <span>
                  p99 <span className="text-fg">{fmt(r.benign_p99)}</span>
                </span>
                <span>
                  z <span className={elevated ? "text-red" : "text-blue"}>{fmtZ(r.z)}</span>
                </span>
              </div>

              {/* attribution bar — model's own integrated-gradients contribution */}
              <div className="mt-2.5 flex items-center gap-2.5">
                <div className="h-1 w-28 shrink-0 rounded bg-surface-3">
                  <div
                    className={`h-1 rounded ${elevated ? "bg-red" : "bg-blue"}`}
                    style={{ width: `${width}%` }}
                  />
                </div>
                <span className="mono text-xs text-fg-3">
                  attribution {r.attribution.toFixed(3)}
                  {r.contribution !== 0 && (
                    <>
                      {" "}
                      · contribution {r.contribution >= 0 ? "+" : ""}
                      {r.contribution.toFixed(3)}
                    </>
                  )}
                </span>
              </div>
            </div>
          );
        })}

        <p className="border-t border-border pt-3 text-xs text-fg-3">
          z = (observed − benign mean) / benign std over TRAIN-split windows.
          |z| &lt; 2 reads as normal; direction is never inferred — the panel
          shows exactly what the evidence engine reported.
        </p>
      </div>
    </Card>
  );
}
