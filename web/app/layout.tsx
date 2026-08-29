import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { ModelStatus } from "@/components/ModelStatus";
import { NavLinks } from "@/components/ui";

export const metadata: Metadata = {
  title: "CyberForecaster",
  description:
    "Temporal attack-progression forecasting: SIH26153 prototype (offline demo)",
};

/** Brand mark: a rising forecast trace crossing its threshold. */
function LogoMark() {
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true">
      <rect x="0.75" y="0.75" width="20.5" height="20.5" rx="6"
            fill="#11151a" stroke="#232831" strokeWidth="1.5" />
      <path d="M4 14.5 L8.5 11 L12 12.5 L18 6.5"
            fill="none" stroke="#f59e0b" strokeWidth="2"
            strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="18" cy="6.5" r="2" fill="#f59e0b" />
    </svg>
  );
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <header className="sticky top-0 z-10 border-b border-border bg-bg/85 backdrop-blur">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-6 py-3">
            <Link href="/" className="flex items-center gap-2.5">
              <LogoMark />
              <span className="text-[15px] font-semibold tracking-tight text-fg">
                Cyber<span className="text-amber">Forecaster</span>
              </span>
            </Link>
            <NavLinks />
            <div className="ml-auto">
              <ModelStatus />
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
        <footer className="mx-auto max-w-6xl px-6 pb-10 pt-2">
          <p className="text-xs text-fg-3">
            Forecasts are decision support, not automated blocking · SIH26153
            prototype · offline demo
          </p>
        </footer>
      </body>
    </html>
  );
}
