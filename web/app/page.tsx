"use client";

import { useEffect, useMemo, useState } from "react";
import { api, type Forecast, type RiskLevel, type Scenario, type Timeline } from "@/lib/api";
import { AttackProgression } from "@/components/AttackProgression";
import { ForecastChart } from "@/components/ForecastChart";
import { WhyPrediction } from "@/components/WhyPrediction";
import { Badge, type Tone } from "@/components/ui";

const RISK_TONE: Record<RiskLevel, Tone> = {
  HIGH: "red",
  ELEVATED: "amber",
  LOW: "green",
};

const KIND_NOTE: Record<Scenario["kind"], string> = {
  onset: "Forecast starts before the attack begins",
  during: "Attack in progress at forecast time",
  quiet: "Benign period with no attack nearby",
};

function SecondaryMetric({
  label,
  value,
  sub,
}: {
  label: string;
  value: React.ReactNode;
  sub?: string;
}) {
  return (
    <div className="px-5 py-4">
      <div className="label">{label}</div>
      <div className="mt-1.5 text-lg font-semibold text-fg">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-fg-2">{sub}</div>}
    </div>
  );
}

export default function ConsolePage() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState<string>("");
  const [threshold, setThreshold] = useState<number>(0.6);
  const [defaultThreshold, setDefaultThreshold] = useState<number>(0.6);
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    Promise.all([api.scenarios(), api.health()])
      .then(([scs, h]) => {
        setScenarios(scs);
        if (h.threshold) {
          setDefaultThreshold(h.threshold);
          setThreshold(h.threshold);
        }
        if (scs.length > 0) setScenarioId(scs[0].id);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoaded(true));
  }, []);

  const scenario = useMemo(
    () => scenarios.find((s) => s.id === scenarioId),
    [scenarios, scenarioId],
  );

  async function analyze() {
    if (!scenarioId) return;
    setBusy(true);
    setError(null);
    try {
      const [f, t] = await Promise.all([
        api.forecast(scenarioId, threshold),
        api.timeline(scenarioId, threshold),
      ]);
      setForecast(f);
      setTimeline(t);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const tripped = forecast !== null && forecast.peak >= forecast.threshold;
  const leadWindows = forecast?.crossing_step ?? 0;

  return (
    <div className="space-y-4">
      {/* ---- control bar ---- */}
      <section className="rounded-lg border border-border bg-surface p-5">
        <div className="flex flex-wrap items-end gap-x-8 gap-y-4">
          <div className="min-w-[280px] flex-1">
            <label htmlFor="scenario" className="label mb-1.5 block">
              Scenario
            </label>
            <select
              id="scenario"
              value={scenarioId}
              onChange={(e) => setScenarioId(e.target.value)}
              className="w-full rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-fg outline-none transition-colors focus:border-blue"
            >
              {scenarios.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            {scenario && (
              <p className="mt-1.5 text-xs text-fg-2">{KIND_NOTE[scenario.kind]}</p>
            )}
          </div>

          <div className="w-56">
            <label htmlFor="threshold" className="label mb-1.5 block">
              Alert threshold
            </label>
            <div className="flex items-center gap-3">
              <input
                id="threshold"
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={threshold}
                onChange={(e) => setThreshold(Number(e.target.value))}
                className="range flex-1"
              />
              <span className="mono w-10 text-right text-sm text-fg">
                {(threshold * 100).toFixed(0)}%
              </span>
            </div>
            <p className="mt-1.5 text-xs text-fg-2">
              Default {defaultThreshold.toFixed(2)}, tuned on validation data
            </p>
          </div>

          <button
            onClick={analyze}
            disabled={busy || !scenarioId}
            className="rounded-md bg-amber px-5 py-2.5 text-sm font-semibold text-bg transition-colors hover:bg-amber/90 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "Forecasting…" : "Run forecast"}
          </button>
        </div>
      </section>

      {error && (
        <section className="rounded-lg border border-red/25 bg-red/10 p-4">
          <p className="text-sm font-medium text-red">{error}</p>
        </section>
      )}

      {loaded && scenarios.length === 0 && !error && (
        <section className="rounded-lg border border-border bg-surface p-6">
          <p className="text-sm text-amber">
            No usable scenario in this dataset: the pipeline needs an attack
            onset with enough windows of history. Check its output.
          </p>
        </section>
      )}

      {!forecast && !error && scenarios.length > 0 && (
        <section className="rounded-lg border border-dashed border-border bg-surface p-12">
          <div className="mx-auto max-w-sm text-center">
            <p className="text-sm font-semibold text-fg">No forecast yet</p>
            <p className="mt-1.5 text-sm text-fg-2">
              Select a scenario and run a forecast. The predicted progression,
              supporting evidence and attribution will appear here.
            </p>
          </div>
        </section>
      )}

      {forecast && (
        <div key={forecast.scenario_id + threshold} className="rise-in space-y-4">
          {/* ---- primary prediction ---- */}
          <section className="rounded-lg border border-border bg-surface">
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-border px-5 py-3.5">
              <h2 className="text-[15px] font-semibold text-fg">
                Attack progression forecast
              </h2>
              <span className="mono text-xs text-fg-2">
                horizon: {forecast.probs.length} windows
              </span>
            </div>

            <div className="grid lg:grid-cols-[minmax(0,1fr)_auto]">
              <div className="flex flex-wrap items-center gap-x-6 gap-y-3 p-5">
                <div>
                  <div className="text-5xl font-semibold tabular-nums text-fg">
                    {(forecast.peak * 100).toFixed(0)}
                    <span className="text-2xl text-fg-2">%</span>
                  </div>
                  <div className="mt-1.5 text-sm text-fg-2">
                    Probability of attack progression
                  </div>
                  <div className="text-xs text-fg-3">
                    peak over next {forecast.probs.length} windows
                  </div>
                </div>
                <div>
                  <div className="label mb-1.5">Risk</div>
                  <Badge tone={RISK_TONE[forecast.level]} className="px-3 py-1 text-sm">
                    {forecast.level}
                  </Badge>
                  <div className="mt-1.5 text-xs text-fg-3">
                    threshold {(forecast.threshold * 100).toFixed(0)}%
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 border-t border-border sm:grid-cols-3 lg:border-l lg:border-t-0">
                <SecondaryMetric
                  label="Predicted stage"
                  value={forecast.stage || "-"}
                  sub={forecast.stage ? undefined : "no stage predicted"}
                />
                <SecondaryMetric
                  label="Lead time"
                  value={leadWindows === 1 ? "1 window" : `${leadWindows} windows`}
                  sub="until threshold crossing"
                />
                <SecondaryMetric
                  label="Threshold"
                  value={`${(forecast.threshold * 100).toFixed(0)}%`}
                  sub="alert operating point"
                />
              </div>
            </div>
          </section>

          {/* ---- threshold-crossed banner ---- */}
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
                  Forecast threshold crossed
                </p>
                <p className="mt-0.5 text-sm text-fg">
                  {(forecast.peak * 100).toFixed(0)}% probability of attack
                  progression
                  {forecast.stage ? ` to ${forecast.stage}` : ""} within the
                  forecast horizon.
                </p>
                <p className="mt-0.5 text-xs text-fg-2">
                  Model forecast · not confirmed malicious activity · decision
                  support only
                </p>
              </div>
            </section>
          )}

          {timeline && <ForecastChart timeline={timeline} />}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <AttackProgression forecast={forecast} />
            <WhyPrediction forecast={forecast} />
          </div>
        </div>
      )}
    </div>
  );
}
