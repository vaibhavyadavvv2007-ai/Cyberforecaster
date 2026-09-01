"""Generate the two deck assets for the SIH idea presentation.

Outputs (docs/assets/):
  architecture.png  - pipeline flow diagram for the Technical Approach slide
  benchmark.png     - PR-AUC comparison bar chart

Style: light surface #fcfcfb, ink #0b0b0b/#52514e, hairlines #e1e0d9,
series blue #2a78d6 (model) / orange #eb6834 (rule engine) — the validated
dataviz palette pair. Arial to match the SIH template.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
HAIR = "#e1e0d9"
BLUE = "#2a78d6"
ORANGE = "#eb6834"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial"],
    "text.color": INK,
})

OUT = Path(__file__).resolve().parents[1] / "docs" / "assets"
OUT.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------- architecture
def architecture() -> None:
    fig, ax = plt.subplots(figsize=(13.0, 4.6), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.set_xlim(0, 130)
    ax.set_ylim(0, 46)
    ax.axis("off")

    def box(x, y, w, h, title, lines, accent, title_sz=11.5, body_sz=9.5):
        ax.add_patch(FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0.6,rounding_size=1.2",
            linewidth=1.0, edgecolor=accent, facecolor="white"))
        ax.text(x + w / 2, y + h - 3.0, title, ha="center", va="top",
                fontsize=title_sz, fontweight="bold", color=INK)
        for i, ln in enumerate(lines):
            ax.text(x + w / 2, y + h - 8.0 - i * 4.2, ln, ha="center",
                    va="top", fontsize=body_sz, color=INK2)

    def arrow(x1, y1, x2, y2, color=INK2):
        ax.add_patch(FancyArrowPatch(
            (x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=14,
            linewidth=1.4, color=color, shrinkA=2, shrinkB=2))

    # inputs (left)
    box(1, 27, 24, 17, "OFFLINE DATA",
        ["CSE-CIC-IDS2018", "flow records (labelled)"], INK2)
    box(1, 2, 24, 17, "LIVE SENSOR",
        ["Npcap / scapy capture", "on the demo network"], INK2)

    # window builder (middle)
    box(31, 13, 27, 21, "WINDOW BUILDER",
        ["bidirectional flows", "30-s windows", "18 traffic features"], INK)

    # two engines
    box(64, 26, 31, 18, "RULE ENGINE",
        ["transparent ATT&CK", "stage rules — instant", "signatures (1 window)"], ORANGE)
    box(64, 2, 31, 18, "LSTM FORECASTER",
        ["10 windows in", "attack probability,", "5 steps ahead + stage"], BLUE)

    # output (right)
    box(101, 13, 27, 20, "EXPLAINED WARNING",
        ["probability trajectory", "ATT&CK stage", "per-feature attribution"], INK,
        title_sz=11.5, body_sz=9.5)

    # arrows
    arrow(25.6, 35, 30.4, 27)      # offline -> builder
    arrow(25.6, 10, 30.4, 19)      # live -> builder
    arrow(59.6, 29, 63.4, 35, ORANGE)   # builder -> rules
    arrow(59.6, 18, 63.4, 12, BLUE)     # builder -> lstm
    arrow(96.6, 35, 100.4, 28, ORANGE)  # rules -> warning
    arrow(96.6, 11, 100.4, 18, BLUE)    # lstm -> warning

    ax.text(65, 45.4, "one pipeline, two inputs, two engines, one explained warning",
            ha="center", fontsize=10, color=INK2, style="italic")

    fig.savefig(OUT / "architecture.png", facecolor=SURFACE,
                bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)


# ------------------------------------------------------------------ benchmark
def benchmark() -> None:
    fig, ax = plt.subplots(figsize=(6.2, 2.4), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    labels = ["Logistic baseline\n(same features, same split)", "LSTM forecaster (ours)"]
    vals = [0.333, 0.656]
    colors = [ORANGE, BLUE]

    bars = ax.barh(labels, vals, height=0.52, color=colors)
    for b, v in zip(bars, vals):
        ax.text(b.get_width() + 0.012, b.get_y() + b.get_height() / 2,
                f"{v:.3f}", va="center", ha="left", fontsize=13,
                fontweight="bold", color=INK)

    ax.set_xlim(0, 0.80)
    ax.set_xlabel("Test PR-AUC  (unseen attack family, chronological split)",
                  fontsize=9.5, color=INK2)
    ax.tick_params(axis="y", labelsize=10, colors=INK, length=0)
    ax.tick_params(axis="x", labelsize=9, colors=INK2)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(HAIR)
    ax.xaxis.grid(True, color=HAIR, linewidth=0.8)
    ax.set_axisbelow(True)

    fig.savefig(OUT / "benchmark.png", facecolor=SURFACE,
                bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)


if __name__ == "__main__":
    architecture()
    benchmark()
    print("wrote", OUT / "architecture.png", "and", OUT / "benchmark.png")
