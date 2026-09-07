#!/usr/bin/env python3
"""Plot saved discovery statistics; no engine imports or execution."""

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/petacat-episodic-matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, FixedFormatter


def plot(directory):
    analysis = json.loads((directory / "analysis.json").read_text())
    protocol = json.loads((directory / "protocol.json").read_text())
    problems = {p["name"]: p["strings"] for p in protocol["problems"]}
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.edgecolor": "#8a8a8a", "axes.labelcolor": "#333333",
                         "text.color": "#222222", "savefig.facecolor": "white"})
    fig, axes = plt.subplots(2, 2, figsize=(12, 8.5), sharex=True, sharey=True)
    styles = {"best_a": ("#007f70", "o", "Best A: native quality"),
              "best_b": ("#af3a76", "s", "Best B: native conceptual preference")}
    maximum = max((point["f1_over_N"] or 0 for result in analysis["results"]
                   for data in result["definitions"].values() for point in data["checkpoints"]), default=0)
    for ax, result in zip(axes.flat, analysis["results"]):
        for definition, data in result["definitions"].items():
            color, marker, label = styles[definition]
            points = data["checkpoints"]
            ax.plot([p["episodes"] for p in points],
                    [float("nan") if p["f1_over_N"] is None else p["f1_over_N"] for p in points],
                    color=color, marker=marker, markersize=5, linewidth=1.7,
                    markerfacecolor="none" if definition == "best_b" else color, label=label)
        initial, modified, target = problems[result["problem"]]
        ax.set_title(f"{result['problem']}: {initial} -> {modified}; {target} -> ?", fontsize=11, pad=12)
        ax.set_yscale("symlog", linthresh=0.0001, linscale=0.4)
        ax.set_ylim(-0.00002, max(0.012, maximum * 1.7))
        ax.set_xlim(75, 1025)
        ax.set_xticks([100, 300, 500, 700, 1000])
        ax.yaxis.set_major_locator(FixedLocator([0, 0.0001, 0.001, 0.01, 0.1]))
        ax.yaxis.set_major_formatter(FixedFormatter(["0", "0.0001", "0.001", "0.01", "0.1"]))
        ax.axhline(protocol["singleton_threshold"], color="#787878", linewidth=1, linestyle="--", zorder=0)
        ax.grid(axis="y", color="#dddddd", linewidth=0.6, alpha=0.8)
        ax.set_axisbelow(True)
    for ax in axes[1]:
        ax.set_xlabel("Episode assignments (8-run horizon)", labelpad=8)
    for ax in axes[:, 0]:
        ax.set_ylabel("Singleton fraction f1 / N", labelpad=10)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.925), ncol=2, frameon=False)
    fig.suptitle("Episodic Best-Answer Discovery", fontsize=19, y=0.975)
    fig.text(0.5, 0.045,
             "Earliest reached answer breaks ties. N counts answered, complete episodes. Dashed line: target 0.0001.\n"
             "The vertical scale is logarithmic above 0.0001 and linear near zero. A zero estimate is not a confidence guarantee.",
             ha="center", va="center", fontsize=9, color="#444444")
    fig.subplots_adjust(left=0.09, right=0.98, top=0.835, bottom=0.135, hspace=0.35, wspace=0.15)
    fig.savefig(directory / "discovery-curves.png", dpi=160)
    fig.savefig(directory / "discovery-curves.pdf")
    plt.close(fig)
    print(f"Plotted {sum(len(d['checkpoints']) for r in analysis['results'] for d in r['definitions'].values())} saved curve points; zero engine executions")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    plot(parser.parse_args().directory)
