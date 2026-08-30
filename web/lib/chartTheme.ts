/**
 * Chart theme — the palette hexes Recharts needs as raw SVG attribute
 * values (it cannot consume CSS custom properties). Single source for
 * every chart so axis/line colors cannot drift from globals.css.
 * Keep in sync with @theme in app/globals.css.
 */
export const CHART = {
  grid: "#222d3f",
  axis: "#222d3f",
  tick: "#6d7c92",
  tooltipBg: "#171f2b",
  tooltipBorder: "#222d3f",
  neutral: "#9fadbe", // observed / baseline / seeded history
  amber: "#ffb224",   // forecast / live capture
  red: "#ff6a5f",     // threshold / danger
  blue: "#6ea8fe",    // attribution / informational
} as const;
