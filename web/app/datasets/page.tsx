"use client";

import { useEffect, useState } from "react";
import { api, type DatasetRow } from "@/lib/api";
import { Badge, Card, type Tone } from "@/components/ui";

/*
  Dataset registry — the multi-dataset training story, rendered from the
  live registry status. Each row states exactly what is on disk and what
  remains, because a dataset that is not downloaded is shown as not
  downloaded — never implied to be "coming soon data".
*/

const STATUS_TONE: Record<DatasetRow["status"], Tone> = {
  READY: "green",
  PENDING_WIRING: "amber",
  NOT_DOWNLOADED: "gray",
};

const STATUS_TEXT: Record<DatasetRow["status"], string> = {
  READY: "files on disk · adapter wired",
  PENDING_WIRING: "files on disk · adapter pending",
  NOT_DOWNLOADED: "not downloaded",
};

export default function DatasetsPage() {
  const [rows, setRows] = useState<DatasetRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .datasets()
      .then((r) => setRows(r.datasets))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <div className="space-y-6">
      <section className="border-b border-border pb-5">
        <div className="text-sm font-semibold text-fg">Dataset registry</div>
        <div className="mono mt-0.5 text-xs text-fg-2">
          every registered dataset with its live on-disk status · a missing
          dataset is reported as missing, never as zero or fake
        </div>
      </section>

      {error && (
        <section className="rounded-lg border border-red/25 bg-red/10 p-4">
          <p className="text-sm font-medium text-red">{error}</p>
        </section>
      )}

      {rows && (
        <Card
          title="Registered datasets"
          meta={`${rows.filter((r) => r.status === "READY").length}/${rows.length} ready`}
          bodyClassName="p-0"
        >
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Dataset</th>
                  <th>Version</th>
                  <th>Modality</th>
                  <th>Files</th>
                  <th>Status</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <span className="mono text-xs font-semibold text-fg">{r.id}</span>
                      <div className="mt-0.5 text-xs text-fg-2">{r.name}</div>
                    </td>
                    <td className="mono num">{r.version}</td>
                    <td className="text-xs text-fg-2">{r.modality}</td>
                    <td className="mono num">{r.n_files}</td>
                    <td>
                      <Badge tone={STATUS_TONE[r.status]}>{r.status}</Badge>
                      <div className="mt-0.5 text-xs text-fg-3">{STATUS_TEXT[r.status]}</div>
                    </td>
                    <td>
                      {r.source_url ? (
                        <a
                          href={r.source_url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-xs text-blue hover:underline"
                        >
                          download page ↗
                        </a>
                      ) : (
                        <span className="text-xs text-fg-3">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="border-t border-border px-5 py-3 text-xs text-fg-2">
            Files belong in <span className="mono">data/raw/&lt;dataset-id&gt;/</span>.
            When new datasets land, each is adapted separately — never blindly
            concatenated — and the canonical schema records what each source
            can and cannot provide.
          </p>
        </Card>
      )}

      {!rows && !error && (
        <section className="rounded-lg border border-border bg-surface p-6">
          <p className="text-sm text-fg-2">Loading registry…</p>
        </section>
      )}
    </div>
  );
}
