# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Compare fixed stage totals; use the EPSM draft-1 palette without global edits."""


def plot_report(report, *, ax=None, show=False):
    """Return a figure with component bars and explicitly labelled missing values."""
    try:
        import matplotlib.pyplot as plt
    except ImportError as error:
        raise ImportError(
            "Plotting requires: python -m pip install 'epsm_lca[plot]'"
        ) from error
    rows = report.table()
    with plt.rc_context(
        {
            "axes.facecolor": "white",
            "figure.facecolor": "white",
            "text.color": "#1F2937",
            "axes.labelcolor": "#1F2937",
            "grid.color": "#E5E7EB",
            "font.family": "sans-serif",
        }
    ):
        own_axis = ax is None
        if own_axis:
            figure, ax = plt.subplots(figsize=(max(6, len(rows) * 1.25), 4.5))
        else:
            figure = ax.figure
        for field, offset, label, color, hatch in (
            ("material_so_far_kgco2e", -0.19, "Materials so far", "#E69F00", "//"),
            ("energy_kgco2e", 0.19, "Energy for the chosen period", "#0072B2", None),
        ):
            if field == "energy_kgco2e" and not report.summary()["include_energy"]:
                continue
            known = [
                (i, row[field]) for i, row in enumerate(rows) if row[field] is not None
            ]
            ax.bar(
                [i + offset for i, _ in known],
                [v for _, v in known],
                0.36,
                label=label,
                color=color,
                hatch=hatch,
            )
            for i, row in enumerate(rows):
                if row[field] is None:
                    ax.annotate(
                        "Missing",
                        (i + offset, 0),
                        rotation=90,
                        color="#6B7280",
                        va="bottom",
                    )
        for i, row in enumerate(rows):
            if row["total_kgco2e"] is None:
                ax.annotate(
                    "Total incomplete",
                    (i, 0),
                    xytext=(0, -30),
                    textcoords="offset points",
                    ha="center",
                    color="#D55E00",
                    fontsize=8,
                )
        ax.set_xticks(
            range(len(rows)),
            ["Baseline" if r["step"] == 0 else f"Step {r['step']}" for r in rows],
        )
        ax.set_ylabel("Climate impact (kg CO₂e)")
        years = report.summary()["period_years"]
        scope = (
            "materials only"
            if not report.summary()["include_energy"]
            else f"each state over {years:g} years"
        )
        ax.set_title(f"Building renovation — {scope}")
        ax.grid(axis="y", alpha=0.6)
        ax.set_axisbelow(True)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18))
        if own_axis:
            figure.tight_layout()
        if show:
            plt.show()
        return figure
