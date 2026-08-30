---
name: CyberForecaster
description: Attack-progression forecasting console styled as a professional security analytics product (Datadog/Grafana/Linear register).
colors:
  primary: "#ffb224"          # amber — forecast / attention
  danger: "#ff6a5f"           # red — threshold crossed / errors
  success: "#43d97b"          # green — healthy / live model
  info: "#6ea8fe"             # blue — informational (attribution)
  background: "#0a0e14"
  surface: "#10151d"
  surface-2: "#171f2b"
  border: "#222d3f"
  text-primary: "#e9edf4"
  text-secondary: "#9fadbe"
  text-faint: "#6d7c92"
typography:
  body:
    fontFamily: "Inter Variable, Inter, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  heading:
    fontFamily: "Inter Variable, Inter, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 600
    letterSpacing: "normal"
    textTransform: "none"
  label:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "10px"
    fontWeight: 500
    letterSpacing: "0.1em"
    textTransform: "uppercase"
  mono:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "12-13px"
    fontWeight: 400
    fontFeature: "tnum"
  table-cell:
    fontFamily: "Inter Variable, Inter, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
  hero:
    fontFamily: "Inter Variable, Inter, system-ui, sans-serif"
    fontSize: "72px"
    fontWeight: 600
    letterSpacing: "-0.02em"
rounded:
  card: "8px"      # rounded-lg
  control: "6px"   # rounded-md (buttons, inputs, badges)
  bar: "9999px"    # full pill — bar/badge/gauge tracks, slider/scrollbar thumbs
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
  2xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.background}"
    rounded: "{rounded.control}"
    padding: "10px 20px"
  card:
    backgroundColor: "{colors.surface}"
    borderColor: "{colors.border}"
    rounded: "{rounded.card}"
  input-select:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
  badge-high:
    backgroundColor: "rgba(255,106,95,0.1)"
    textColor: "{colors.danger}"
    borderColor: "rgba(255,106,95,0.25)"
    rounded: "{rounded.control}"
---

# Design System: CyberForecaster

## Overview

**Creative North Star: "The Analyst's Console"**

A professional security analytics product — the register of Datadog, Grafana
and Linear, with a subtle cybersecurity identity. The screen answers one
question within seconds: *what does the model think will happen?* Everything
else (chart, ATT&CK progression, attribution, benchmarks) is supporting
evidence, deliberately quieter than the prediction it supports.

The world is dark, dense but calm, and semantic in its color: gray for
neutral system chrome, amber for forecast and attention, red for danger,
green for healthy, blue for informational. Decoration carries no
information here — no corner brackets, scanlines, terminal framing, or glow.
Cards are subtle-bordered 8px-radius surfaces; hierarchy comes from type
scale, spacing and color semantics, not effects. Fonts are self-hosted
(the demo runs offline on one laptop), and every number is served from the
local API.

**Key Characteristics:**
- Inter for the interface; JetBrains Mono for timestamps, IDs, feature names, metrics, thresholds and section labels
- Sentence case everywhere; uppercase survives only as 10px mono section labels
- Semantic color discipline: amber = forecast/attention, red = danger, green = healthy, blue = informational
- Subtle 1px borders, 8px card radius, 6px control radius; no glows, no gradients-as-decoration
- The honesty contract (model status: live / cached / simulated) always visible in the header

## Colors

### Semantic
- **Amber** (#ffb224): the forecast identity — primary action, forecast
  line, ELEVATED risk, predicted-stage highlight. Used sparingly.
- **Red** (#ff6a5f): danger only — threshold-crossed banner, HIGH risk,
  error states, alert-threshold line. Never decorative.
- **Green** (#43d97b): healthy — live-model status dot, LOW risk.
- **Blue** (#6ea8fe): informational — attribution bars, focus-visible rings.

### Neutral
- **Background** (#0a0e14): page ground.
- **Surface** (#10151d): cards.
- **Surface-2** (#171f2b): elevated wells — inputs, table hover, bar tracks.
- **Border** (#222d3f): all hairlines.
- **Text** (#e9edf4): primary text.
- **Text-2** (#9fadbe): secondary text (contrast ≥ 7:1 on surface).
- **Text-3** (#6d7c92): faint — axis ticks, footnotes (≥ 4.5:1 on surface). Never primary copy.

### Named Rules
**The Semantic Color Rule.** Every use of amber/red/green/blue must map to
its meaning (forecast / danger / healthy / informational). If a color cannot
state its semantics, it is decoration and comes out.
**The Status Pill Rule.** The model status pill (green live / amber cached /
red simulated) is the only place where a colored dot asserts data provenance.
Risk level is text + tinted badge, never a bare dot — states must read
through text, not color alone.

## Typography

**Interface Font:** Inter (variable, self-hosted)
**Technical Font:** JetBrains Mono (self-hosted)

### Hierarchy
- **Page title** (600, 20px, sentence case): "Benchmarks".
- **Card title** (600, 15px, sentence case): every section header sits in the card's header strip.
- **Section label** (JetBrains Mono 500, 10px, 0.1em tracking, uppercase):
  small field labels and table headers — the instrument register.
- **Body** (400, 14px, 1.5): all explanatory copy.
- **Mono readout** (400, 12–13px, tabular-nums): timestamps, technique IDs,
  feature names, metric values, thresholds — never headings, nav or buttons.
- **Hero number** (600, 72px, -0.02em tracking, tabular-nums, Inter): the
  peak probability — the single dominant element on the console. Turns red
  when the threshold is crossed, with a peak-vs-threshold gauge beneath.

### Named Rules
**The Mono-Is-Technical Rule.** Monospace marks a value as machine-measured.
If a string is a word a human wrote (heading, label, button, sentence), it
is Inter. If it is a number an instrument produced, it is JetBrains Mono.

## Layout

Single column inside max-w-6xl (72rem), px-6, 16px vertical rhythm
(`space-y-6`). Reading order is the analyst's question order: sticky header
(brand, nav, model status) → command bar (scenario, threshold, run —
controls sit on the ground, not in a card) →
prediction card (hero) → threshold-crossed banner (when tripped) → chart →
ATT&CK progression + attribution side by side (`lg:grid-cols-2`).

The prediction card is asymmetric on purpose: `lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]`
gives the probability + risk badge the dominant left two-thirds, with
predicted stage / lead time / threshold as three compact secondary metrics on
a divider-separated rail. The header wraps (never truncates) below ~660px so
the model status stays visible on every screen.

## Elevation & Depth

Depth is tonal: background < surface < surface-2, separated by 1px borders.
No drop shadows, no glows, no backdrop effects beyond the header's own
`backdrop-blur`. The one sanctioned tint family is semantic alpha: badges and
the tripped banner use 10% fills of their semantic color over surface.

## Shapes

- Cards: 8px radius (rounded-lg), 1px border.
- Buttons, inputs, badges, selects: 6px radius (rounded-md).
- Progress/attribution bars: fully rounded 6px-tall tracks.
- Icons: inline SVG line icons (1.75px stroke), 16px.
- The logo mark is a rounded square holding a rising amber forecast trace — the product in miniature.

## Components

### Buttons
- **Primary (Run forecast):** solid amber, background-dark text, 6px radius,
  `10px 20px` padding, `hover:bg-amber/90`, `active:translate-y-px`. Reads as
  a normal product action, not a sci-fi control.
- **Disabled:** 50% opacity.

### Badges
Tinted semantic badges: 10% background, 25% border, semantic text color.
Risk: HIGH red / ELEVATED amber / LOW green. "Predicted" tag: amber.

### Cards
Every section is a card: surface ground, 1px border, 8px radius, optional
header strip (title left, mono meta right) over a hairline divider. The
empty state uses a dashed border.

### Inputs
- **Scenario select:** surface-2 ground, 6px radius, native chevron.
- **Threshold slider:** 4px rounded track (border color), 14px amber thumb,
  mono percentage beside it, one line of context under it.
- **Focus:** blue 2px focus-visible ring globally; inputs shift border to
  blue on focus.

### Model status pill
Header-right pill: colored dot (green live / amber cached / red simulated /
gray connecting) + label + mono `thr 0.76` when live. Tooltips carry any boot
error. Always visible.

### Forecast chart
Recharts, 240px tall: observed = gray solid; forecast = amber solid with
dots; threshold = red dashed with inline label; "now" = gray vertical
divider with label. The forecast region carries a 5% amber tint
(ReferenceArea) so left/right is legible without the legend. Charts never
animate.

### ATT&CK progression
A five-row list (Reconnaissance → Exfiltration) with technique IDs in mono.
Rows before the predicted stage show a neutral check, later stages an open
circle. The predicted row gets a 5% amber wash, arrow icon, "Predicted"
badge and its peak probability. A rule-engine cross-check line runs beneath.

### Why this prediction
Attribution bars (blue) with mono feature names and values, a
plain-language summary sentence derived from the actual top two features
(never invented), and a one-line method footnote (Integrated Gradients).

### Tables
`.data-table`: mono uppercase 10px headers, 13px cells, mono tabular numerals
right-aligned, hairline row separators, hover wash, first/last cell edge
padding. The benchmarks page leads with summary cards, comparison bars and
a horizon chart; exact tables stay below for inspection.

## Do's and Don'ts

### Do:
- **Do** make the prediction visually dominant; everything else supports it.
- **Do** use sentence case; reserve uppercase for 10px mono section labels.
- **Do** keep monospace for measured values and section labels.
- **Do** distinguish model forecast from confirmed incident in every warning's copy.
- **Do** serve every number from the API verbatim; keep observed vs forecast visually distinct in every chart.

### Don't:
- **Don't** use color decoratively or introduce a fifth accent; each of amber/red/green/blue must state its semantics.
- **Don't** add corner brackets, scanlines, terminal framing, glows, or gradients-as-decoration.
- **Don't** put emoji, animated borders or tweened numbers in the interface.
- **Don't** load any font or asset from a CDN; the demo runs offline.
