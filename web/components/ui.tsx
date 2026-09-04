"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/*
  Shared UI primitives — the whole app draws cards, badges, metrics and
  nav from here so spacing, radii and semantic color stay consistent.
*/

export type Tone = "gray" | "amber" | "red" | "green" | "blue";

const TONE_BADGE: Record<Tone, string> = {
  gray: "border-border bg-surface-2 text-fg-2",
  amber: "border-amber/25 bg-amber/10 text-amber",
  red: "border-red/25 bg-red/10 text-red",
  green: "border-green/25 bg-green/10 text-green",
  blue: "border-blue/25 bg-blue/10 text-blue",
};

export function Badge({
  tone,
  children,
  className = "",
}: {
  tone: Tone;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-semibold ${TONE_BADGE[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

export function Card({
  title,
  meta,
  actions,
  children,
  className = "",
  bodyClassName = "p-5",
}: {
  title?: React.ReactNode;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  const hasHeader = title || meta || actions;
  return (
    <section className={`rounded-lg border border-border bg-surface ${className}`}>
      {hasHeader && (
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-border px-5 py-3.5">
          {title && <h2 className="text-[15px] font-semibold text-fg">{title}</h2>}
          {meta && <span className="mono text-xs text-fg-2">{meta}</span>}
          {actions}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

export function Metric({
  label,
  value,
  sub,
  tone = "fg",
}: {
  label: string;
  value: React.ReactNode;
  sub?: string;
  tone?: "fg" | "amber" | "red" | "green";
}) {
  const valueColor =
    tone === "amber" ? "text-amber" : tone === "red" ? "text-red" : tone === "green" ? "text-green" : "text-fg";
  return (
    <div className="rounded-lg border border-border bg-surface-2 px-4 py-3.5">
      <div className="label">{label}</div>
      <div className={`mono mt-1.5 text-2xl font-semibold ${valueColor}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-fg-2">{sub}</div>}
    </div>
  );
}

/**
 * Peak-vs-threshold gauge: a probability track with the alert threshold
 * as a fixed tick. Reads like an instrument dial — peak position is
 * data-true, never decorative.
 */
export function PeakGauge({
  peak,
  threshold,
  className = "",
}: {
  peak: number;
  threshold: number;
  className?: string;
}) {
  const over = peak >= threshold;
  return (
    <div className={className}>
      <div
        className="relative h-2 overflow-visible rounded-full bg-surface-2"
        role="img"
        aria-label={`Peak probability ${(peak * 100).toFixed(0)} percent against threshold ${(threshold * 100).toFixed(0)} percent`}
      >
        <div
          className={`h-full rounded-full transition-[width] duration-500 ${over ? "bg-red" : "bg-amber"}`}
          style={{ width: `${Math.min(peak, 1) * 100}%` }}
        />
        {/* threshold tick — sits above the track, outside the clip */}
        <span
          className="absolute -top-1 bottom-[-4px] w-px bg-red/80"
          style={{ left: `${threshold * 100}%` }}
          aria-hidden="true"
        />
      </div>
      <div className="mono mt-1.5 flex justify-between text-[10px] uppercase tracking-widest text-fg-3">
        <span>0%</span>
        <span className="text-red/80">alert {(threshold * 100).toFixed(0)}%</span>
        <span>100%</span>
      </div>
    </div>
  );
}

const NAV = [
  { href: "/", label: "Forecast" },
  { href: "/live", label: "Live" },
  { href: "/analyze", label: "Analyze" },
  { href: "/benchmarks", label: "Benchmarks" },
  { href: "/datasets", label: "Datasets" },
];

export function NavLinks() {
  const pathname = usePathname();
  return (
    <nav className="flex items-center gap-1">
      {NAV.map((item) => {
        const active = pathname === item.href;
        return (
          <Link
            key={item.href}
            href={item.href}
            className={`rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors ${
              active ? "bg-surface-2 text-fg" : "text-fg-2 hover:bg-surface-2/60 hover:text-fg"
            }`}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
