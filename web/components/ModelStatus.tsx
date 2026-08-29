"use client";

import { useEffect, useState } from "react";
import { api, type Health } from "@/lib/api";

/**
 * Model status — the honesty contract, rendered as a quiet status pill.
 * green = REAL (live inference), amber = CACHED, red = SIMULATED.
 * Always visible in the header.
 */
export function ModelStatus() {
  const [health, setHealth] = useState<Health | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch((e) => setErr(String(e)));
  }, []);

  let dot = "bg-fg-3";
  let label = "Connecting";
  let note: string | undefined;
  let extra: React.ReactNode = null;

  if (err) {
    dot = "bg-red";
    label = "API unreachable";
  } else if (health) {
    note = health.model_error ?? health.boot_error ?? undefined;
    if (health.mode === "REAL") {
      dot = "bg-green";
      label = "Model live";
      extra = <span className="mono text-xs text-fg-2">thr {health.threshold.toFixed(2)}</span>;
    } else if (health.mode === "CACHED") {
      dot = "bg-amber";
      label = "Cached results";
    } else {
      dot = "bg-red";
      label = "Simulated data";
    }
  }

  return (
    <span
      className="flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-1.5"
      title={note}
    >
      <span className={`h-2 w-2 shrink-0 rounded-full ${dot}`} aria-hidden="true" />
      <span className="text-[13px] font-medium text-fg-2">{label}</span>
      {extra}
    </span>
  );
}
