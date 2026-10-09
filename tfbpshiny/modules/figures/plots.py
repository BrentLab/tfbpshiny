"""
Pure figure factories for the Figures module.

Each function takes a tidy DataFrame and returns a plotly ``Figure`` (or a matplotlib
figure, for the Venn diagrams). No reactive code and no database access lives here, so
these can be exercised directly from a notebook or a test.

"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from tfbpshiny.utils.figure import (
    AXIS_TITLE_SIZE,
    PAIR_COLORS,
    apply_figure_style,
    inside_legend,
)

logger = logging.getLogger("shiny")

# ---------------------------------------------------------------------------
# Fixed axis ranges
# ---------------------------------------------------------------------------
# Axes are pinned rather than fitted to the data so panels stay comparable -- across
# datasets within a figure, and across sessions as the underlying data changes. The
# cost is that data outside a range is clipped silently, so every figure checks its
# values and logs a WARNING naming the constant to raise.
#
# Adjust these if a warning fires.

#: Figure 1, rank vs. response. A percentage.
FIG1_RANK_RESPONSE_Y: tuple[float, float] = (0.0, 100.0)

#: Figure 1's x axis, the number of top binding targets. Fixed so every regulator's
#: curve is read on the same scale. Note `n` can exceed the largest materialized
#: cutoff (100) when a tie spans it -- Calling Cards has regulators where 87 targets
#: share a p-value of exactly 0 -- so the warning may fire here.
FIG1_RANK_X: tuple[float, float] = (0.0, 102.0)

#: Figure 2, percent responsive among top-N binding targets. A percentage, padded by
#: 2 points each side so markers sitting at exactly 0% or 100% are drawn whole rather
#: than half clipped by the axis edge.
FIG2_TOPN_BOX_Y: tuple[float, float] = (-2.0, 102.0)

#: Figure 3A, percent responsive over the authors' bound targets. A percentage, padded
#: on both sides so a point at 0% or 100% is not clipped by the axis edge.
FIG3A_RESPONSE_Y: tuple[float, float] = (-2.0, 102.0)

#: Figure 3B, number of bound targets. A count, not a percentage, and routinely in the
#: hundreds -- so it is sized from the data plus headroom rather than pinned to 100.
#: Set FIG3B_TARGET_COUNT_Y to a tuple to pin it instead.
FIG3B_TARGET_COUNT_HEADROOM: float = 10.0
FIG3B_TARGET_COUNT_Y: tuple[float, float] | None = None

#: DTO-significant TFs as a percentage of shared TFs. Backs figure 4's bar chart and
#: figures 8/9's DTO bar grids -- all three plot the same metric.
FIG4B_FRACTION_Y: tuple[float, float] = (0.0, 100.0)

#: Figure 6, log2 enrichment of top-N overlap. Note enrichment goes *negative* when an
#: overlap is smaller than chance, which a floor of 0 clips; the warning will say so.
FIG6_ENRICHMENT_Y: tuple[float, float] = (-3, 10.0)

#: Figure 6's x axis (top-N cutoff). Pinned to start at 0 -- even though the smallest
#: materialized cutoff is 10 -- so the curve's rise from the origin is shown honestly
#: rather than cropped, and ends at the largest cutoff in
#: ``materialize.comparison.agreement.AGREEMENT_TOP_N``. Linear, not log: with only
#: 20 evenly-spaced cutoffs (10-200 by 10), a log axis compresses the (visually
#: important) low end without buying readability at the high end.
FIG6_TOP_N_X: tuple[float, float] = (0.0, 200.0)

#: Tick interval for FIG6_TOP_N_X, matching AGREEMENT_TOP_N's own step so a tick
#: lands at every cutoff that was actually computed, not an arbitrary plotly default.
FIG6_TOP_N_DTICK: int = 10

#: Figures 7 and 9 (top row), top-N percent responsive. A percentage -- same range as
#: figure 2, which plots the same quantity.
FIG7_RESPONSE_Y: tuple[float, float] = FIG2_TOPN_BOX_Y


def _warn_if_clipped(
    values: pd.Series | None,
    axis_range: tuple[float, float],
    figure: str,
    constant: str,
    axis: str = "y",
) -> None:
    """
    Log a WARNING when data falls outside a fixed axis range.

    The axis stays as configured -- the point of pinning it is that it does not move.
    This only makes the clipping visible instead of silent, and names the constant to
    change.

    :param values: The values being plotted, or ``None``.
    :param axis_range: The ``(low, high)`` the axis is pinned to.
    :param figure: Human-readable figure name for the message.
    :param constant: Name of the module constant that sets the range.
    :param axis: ``"x"`` or ``"y"``, for the message.

    """
    if values is None or len(values) == 0:
        return
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return
    low, high = axis_range
    below = int((numeric < low).sum())
    above = int((numeric > high).sum())
    if not (below or above):
        return
    logger.warning(
        "%s: %d value(s) fall outside the fixed %s axis [%g, %g] and are clipped "
        "(%d below, %d above; observed min %g, max %g). Raise %s in "
        "modules/figures/plots.py to show them.",
        figure,
        below + above,
        axis,
        low,
        high,
        below,
        above,
        numeric.min(),
        numeric.max(),
        constant,
    )


#: Binding dataset drawn last (so it renders on top of overlapping lines) in the
#: rank-response figures. Calling Cards' Poisson p-values tie heavily at the top of
#: the ranking (see the module docstring in ``ui.py``), which makes its line the one
#: most often obscured by another dataset's when curves cross.
_DRAW_LAST = "callingcards_500bp"


def _draw_order(binding_order: list[str]) -> list[str]:
    """Reorder so :data:`_DRAW_LAST` is drawn last, preserving relative order
    otherwise."""
    return sorted(binding_order, key=lambda db: db == _DRAW_LAST)


def _legend_rank_by_top_response(
    df: pd.DataFrame, binding_order: list[str], labels: dict[str, str]
) -> dict[str, int]:
    """
    Legend order for a rank-response panel: highest response rate at the smallest
    plotted ``n`` (approximately "top 10") first.

    Independent of draw order -- plotly's ``legendrank`` controls legend position
    without affecting which trace is painted on top.

    :param df: Rows for one panel (one regulator), from ``fetch_rank_response``.
    :param binding_order: db_names to consider.
    :param labels: db_name -> display label.
    :returns: label -> legend rank (0 is topmost).

    """
    rates: dict[str, float] = {}
    for db in binding_order:
        sub = df[df["binding_db"] == db]
        if sub.empty:
            continue
        smallest_n_row = sub.sort_values("n").iloc[0]
        rates[labels.get(db, db)] = float(smallest_n_row["percent_responsive"])
    ordered = sorted(rates, key=lambda label: -rates[label])
    return {label: i for i, label in enumerate(ordered)}


def rank_response_figure(
    df: pd.DataFrame,
    labels: dict[str, str],
    binding_order: list[str],
    *,
    title: str | None = None,
    height: int = 480,
    colors: dict[str, str] | None = None,
) -> go.Figure:
    """
    Response rate against binding rank for a single regulator.

    One line per binding dataset. The x axis is ``n`` -- the number of targets actually
    summarised -- rather than the nominal ``top_n``, because ties at the cutoff let more
    than ``top_n`` rows through.

    :param df: Rows for one regulator, from ``fetch_rank_response``.
    :param labels: db_name -> display label.
    :param binding_order: db_names to draw. Draw order (z-stacking) and legend order
        are each computed independently of this list's order -- see
        :func:`_draw_order` and :func:`_legend_rank_by_top_response`.
    :param title: Optional figure title.
    :param height: Pixel height.
    :param colors: Display label -> series colour (``dataset_colors``); a label
        without one falls back to plotly's default.
    :returns: The figure.

    """
    palette = colors or {}
    fig = go.Figure()
    legend_rank = _legend_rank_by_top_response(df, binding_order, labels)
    for db in _draw_order(binding_order):
        sub = df[df["binding_db"] == db].sort_values("n")
        if sub.empty:
            continue
        label = labels.get(db, db)
        fig.add_trace(
            go.Scatter(
                x=sub["n"],
                y=sub["percent_responsive"],
                mode="lines+markers",
                name=label,
                legendrank=legend_rank.get(label),
                line=dict(width=3, color=palette.get(label)),
                marker=dict(size=9),
                hovertemplate=f"{label}<br>n=%{{x}}<br>%{{y:.1f}}%<extra></extra>",
            )
        )
    apply_figure_style(
        fig,
        title=title,
        x_title="Number of top binding targets (n)",
        y_title="% responsive",
        height=height,
    )
    _warn_if_clipped(
        df.get("percent_responsive"),
        FIG1_RANK_RESPONSE_Y,
        "Figure 1 (rank vs. response)",
        "FIG1_RANK_RESPONSE_Y",
    )
    _warn_if_clipped(
        df.get("n"),
        FIG1_RANK_X,
        "Figure 1 x axis (top targets)",
        "FIG1_RANK_X",
        axis="x",
    )
    fig.update_yaxes(range=list(FIG1_RANK_RESPONSE_Y))
    fig.update_xaxes(range=list(FIG1_RANK_X))
    # Curves fall from left to right, so the top-right corner is free.
    fig.update_layout(legend=inside_legend(), margin=dict(l=70, r=30, t=60, b=60))
    return fig


#: Panels visible at once in a figure 1-style scrolling window (figure 3).
FIG1_FACET_VISIBLE = 3


def percent_responsive_boxes(
    df: pd.DataFrame,
    labels: dict[str, str],
    binding_order: list[str],
    *,
    title: str | None = None,
    y_title: str = "% responsive in top 25",
    height: int = 460,
    colors: dict[str, str] | None = None,
) -> go.Figure:
    """
    Box plot of per-regulator percent responsive, one box per binding dataset.

    Points are drawn for outliers only, per the figure spec.

    :param df: Rows from ``fetch_topn_percent_responsive``.
    :param labels: db_name -> display label.
    :param binding_order: db_names in draw order.
    :param title: Optional figure title.
    :param y_title: Y axis title.
    :param height: Pixel height.
    :param colors: Display label -> series colour (``dataset_colors``); a label
        without one falls back to plotly's default.
    :returns: The figure.

    """
    palette = colors or {}
    fig = go.Figure()
    for db in binding_order:
        sub = df[df["binding_db"] == db]
        if sub.empty:
            continue
        label = labels.get(db, db)
        fig.add_trace(
            go.Box(
                y=sub["percent_responsive"],
                name=label,
                marker=dict(color=palette.get(label), size=7),
                line=dict(width=2),
                boxpoints="outliers",
                showlegend=False,
                hovertemplate="%{y:.1f}%<extra></extra>",
            )
        )
    apply_figure_style(
        fig, title=title, y_title=y_title, height=height, showlegend=False
    )
    _warn_if_clipped(
        df.get("percent_responsive"),
        FIG2_TOPN_BOX_Y,
        "Figure 2 (% responsive in top N)",
        "FIG2_TOPN_BOX_Y",
    )
    fig.update_yaxes(range=list(FIG2_TOPN_BOX_Y))
    return fig


def dto_significance_bars(
    df: pd.DataFrame,
    labels: dict[str, str],
    binding_order: list[str],
    pr_order: list[str],
    *,
    row_height: int = 340,
    panel_width: int = 420,
    colors: dict[str, str] | None = None,
) -> go.Figure:
    """
    DTO-significant regulators as a fraction of each binding/perturbation pair's shared
    TFs.

    ``fraction_significant``'s denominator (``n_shared``) is already the two-way
    regulator intersection of that specific binding dataset and that specific
    perturbation dataset (see ``fetch_dto_significance``), so each bar is labelled
    directly above it with the raw ``n_significant/n_shared`` counts the percentage
    was computed from, rather than requiring a separate counts panel.

    :param df: Rows from ``fetch_dto_significance``.
    :param labels: db_name -> display label.
    :param binding_order: Binding db_names in draw order.
    :param pr_order: Perturbation db_names, one column each.
    :param row_height: Pixel height.
    :param panel_width: Pixel width per column. The dataset names are long, so the
        figure is given an explicit width rather than squeezed to its container.
    :param colors: Display label -> series colour (``dataset_colors``); a label
        without one falls back to plotly's default.
    :returns: The figure.

    """
    palette = colors or {}
    fig = make_subplots(
        rows=1,
        cols=len(pr_order),
        subplot_titles=[f"% of shared TFs — {labels.get(p, p)}" for p in pr_order],
        shared_yaxes=True,
        horizontal_spacing=0.05,
    )
    for j, p_db in enumerate(pr_order, start=1):
        sub = df[df["perturbation_db"] == p_db]
        if sub.empty:
            continue
        sub = sub.set_index("binding_db").reindex(binding_order).dropna(how="all")
        names = [labels.get(b, b) for b in sub.index]
        colours = [palette.get(n, "#888888") for n in names]
        fig.add_trace(
            go.Bar(
                x=names,
                y=sub["fraction_significant"] * 100,
                marker=dict(color=colours),
                showlegend=False,
                text=[
                    f"{int(sig)}/{int(shared)}"
                    for sig, shared in zip(sub["n_significant"], sub["n_shared"])
                ],
                textposition="outside",
                # Outside text on a bar near the top of a fixed-range axis would
                # otherwise be clipped by that range.
                cliponaxis=False,
                hovertemplate=(
                    "%{x}<br>%{y:.1f}% of shared TFs"
                    "<br>%{text} (DTO-significant / shared TFs)<extra></extra>"
                ),
            ),
            row=1,
            col=j,
        )

    apply_figure_style(fig, height=row_height + 70, showlegend=False)
    _warn_if_clipped(
        df["fraction_significant"] * 100 if "fraction_significant" in df else None,
        FIG4B_FRACTION_Y,
        "Figure 4 (% of shared TFs)",
        "FIG4B_FRACTION_Y",
    )
    fig.update_yaxes(range=list(FIG4B_FRACTION_Y))
    fig.update_yaxes(title_text="% of shared TFs", col=1)
    fig.update_xaxes(tickangle=-30, automargin=True)
    # yshift nudges the subplot titles up in pixels, independent of the paper-coordinate
    # position make_subplots already gave them -- without it the title sits right on top
    # of the tallest bar's "outside" text label, which itself sits just above the bar.
    fig.update_annotations(font_size=AXIS_TITLE_SIZE - 2, font_color="black", yshift=10)
    fig.update_layout(
        width=panel_width * len(pr_order), margin=dict(l=80, r=40, t=90, b=130)
    )
    return fig


#: Options for :func:`dto_venn_figure`'s ``layout`` parameter.
DTO_VENN_LAYOUT_DEFAULT = "default"
DTO_VENN_LAYOUT_COST_BASED = "cost_based"


def dto_venn_figure(
    sets: dict[str, set[str]],
    labels: dict[str, str],
    binding_order: list[str],
    *,
    title: str = "",
    layout: str = DTO_VENN_LAYOUT_DEFAULT,
    colors: dict[str, str] | None = None,
) -> tuple[Any, bool]:
    """
    Three-set Venn of regulators (or targets), as a matplotlib figure.

    plotly has no Venn primitive, so this is the one figure rendered through
    matplotlib. The caller converts it with
    :func:`tfbpshiny.utils.figure.matplotlib_svg_html`.

    :param sets: db_name -> set of locus tags (significant regulators, or top-N
        targets).
    :param labels: db_name -> display label.
    :param binding_order: Exactly three binding db_names, in circle order.
    :param title: Figure title.
    :param layout: :data:`DTO_VENN_LAYOUT_DEFAULT` (matplotlib_venn's exact "pairwise"
        geometric solver, falling back to equal-area circles when no valid
        arrangement exists for these sizes) or :data:`DTO_VENN_LAYOUT_COST_BASED` (an
        approximate optimizer that trades exactness for robustness -- it stays
        proportional on inputs the default solver cannot represent exactly, at the
        cost of the areas being an approximation rather than an exact match).
    :param colors: Display label -> colour (``dataset_colors``); a label without
        one is drawn grey.
    :returns: ``(figure, proportional)``: the ``matplotlib.figure.Figure``, and whether
        the circle areas are proportional to the set sizes (``False`` when the
        default layout had to fall back to equal circles).

    """
    import warnings

    from matplotlib.figure import Figure
    from matplotlib_venn import venn3
    from matplotlib_venn.layout.venn3 import DefaultLayoutAlgorithm, cost_based

    fig = Figure(figsize=(5.5, 5.0))
    ax = fig.subplots()
    ordered = [sets.get(b, set()) for b in binding_order]
    names = tuple(labels.get(b, b) for b in binding_order)
    # Same dataset colours as every other figure; overlaps blend automatically.
    palette = colors or {}
    set_colors = tuple(palette.get(n, "#888888") for n in names)

    if layout == DTO_VENN_LAYOUT_COST_BASED:
        # An approximate optimizer, not an exact geometric solve, per matplotlib_venn's
        # own docs: it "would nearly always succeed, even when the default algorithm
        # sometimes fails" -- so no fallback branch is needed here the way the default
        # layout needs one below.
        v = venn3(
            ordered,
            set_labels=names,
            set_colors=set_colors,
            ax=ax,
            layout_algorithm=cost_based.LayoutAlgorithm(),
        )
        proportional = True
    else:
        # Try the area-proportional layout first. For some size combinations no valid
        # three-circle arrangement exists, and matplotlib_venn warns and then draws
        # areas that do NOT match the counts -- worse than not implying proportion at
        # all. Fall back to equal circles in that case; the region counts stay correct
        # either way.
        proportional = True
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            v = venn3(ordered, set_labels=names, set_colors=set_colors, ax=ax)
            if any("circle" in str(w.message).lower() for w in caught):
                proportional = False

        if not proportional:
            ax.clear()
            # Equal-area circles. `venn3_unweighted` is deprecated in matplotlib_venn
            # 1.1 and errors out, so drive the layout algorithm directly.
            v = venn3(
                ordered,
                set_labels=names,
                set_colors=set_colors,
                ax=ax,
                layout_algorithm=DefaultLayoutAlgorithm(
                    fixed_subset_sizes=(1, 1, 1, 1, 1, 1, 1)
                ),
            )

    for text in ax.texts:
        text.set_fontsize(13)
    # Circle labels sit beside their circles, so they run into each other whenever two
    # circles are close or one is small. A legend below the diagram never overlaps.
    if v is not None:
        for label in v.set_labels or []:
            if label is not None:
                label.set_visible(False)
    from matplotlib.patches import Patch

    ax.legend(
        handles=[
            Patch(facecolor=c, edgecolor="none", alpha=0.6, label=n)
            for n, c in zip(names, set_colors)
        ],
        loc="upper center",
        bbox_to_anchor=(0.5, 0.0),
        ncol=1,
        frameon=False,
        fontsize=13,
    )
    ax.set_title(title, fontsize=16)
    return fig, proportional


__all__ = [
    "DTO_VENN_LAYOUT_COST_BASED",
    "DTO_VENN_LAYOUT_DEFAULT",
    "agreement_box_figure",
    "agreement_curve_figure",
    "authors_bound_grid",
    "binding_perturbation_bar_grid",
    "binding_perturbation_box_grid",
    "dto_significance_bars",
    "dto_venn_figure",
    "percent_responsive_boxes",
    "shared_targets_box_figure",
    "FIG1_FACET_VISIBLE",
    "rank_response_figure",
]


def authors_bound_grid(
    frames: dict[str, pd.DataFrame],
    labels: dict[str, str],
    binding_order: list[str],
    pr_order: list[str],
    *,
    row_height: int = 380,
    colors: dict[str, str] | None = None,
) -> go.Figure:
    """
    Response rate (row A) and bound-set size (row B) over the authors' bound targets.

    Two rows, each with a single y axis, rather than one row of twin-axis panels: with
    two boxes sharing a panel it is never obvious which axis a box belongs to, and the
    two quantities have unrelated units.

    Each row shares one y range across its panels, so panel-to-panel differences are
    data rather than axis differences. A tighter authors' threshold shows as a higher
    box in row A above a lower box in row B.

    The figure takes the width of its container, so the caller wraps it in
    :func:`tfbpshiny.components.scroll_viewport` sized to ``len(pr_order) /
    FIG1_FACET_VISIBLE`` windows; each column is then as wide as a figure 1 panel.

    :param frames: perturbation db_name -> rows from ``fetch_authors_bound``.
    :param labels: db_name -> display label.
    :param binding_order: Peak binding db_names in draw order.
    :param pr_order: Perturbation db_names, one column each.
    :param row_height: Pixel height per row.
    :param colors: Display label -> series colour (``dataset_colors``); a label
        without one falls back to plotly's default.
    :returns: The figure.

    """
    palette = colors or {}
    cols = [p for p in pr_order if p in frames and not frames[p].empty]
    if not cols:
        return go.Figure()

    fig = make_subplots(
        rows=2,
        cols=len(cols),
        subplot_titles=(
            [f"A. % responsive — {labels.get(p, p)}" for p in cols]
            + [f"B. Bound targets — {labels.get(p, p)}" for p in cols]
        ),
        # Every panel keeps its own y ticks so it reads on its own when the figure is
        # scrolled sideways.
        shared_yaxes=False,
        # Row B's subplot titles sit between the rows, so this has to clear row A's
        # rotated x tick labels as well as the title itself.
        vertical_spacing=0.24,
        # A fraction of the whole (wide) figure, scaled to the panel count so the gap
        # stays a fixed fraction of one visible panel.
        horizontal_spacing=min(0.2 / len(cols), 1.0 / max(len(cols) - 1, 1)),
    )
    for j, p in enumerate(cols, start=1):
        df = frames[p]
        for row, col_name in ((1, "percent_responsive"), (2, "n_bound")):
            for db in binding_order:
                sub = df[df["binding_db"] == db]
                if sub.empty:
                    continue
                label = labels.get(db, db)
                fig.add_trace(
                    go.Box(
                        y=sub[col_name],
                        name=label,
                        legendgroup=label,
                        # One legend entry per dataset, from the first panel only.
                        showlegend=(row == 1 and j == 1),
                        marker=dict(color=palette.get(label), size=7),
                        line=dict(width=2),
                        boxpoints="outliers",
                    ),
                    row=row,
                    col=j,
                )

    apply_figure_style(fig, height=row_height * 2 + 260)
    all_rows = pd.concat(frames.values())

    _warn_if_clipped(
        all_rows.get("percent_responsive"),
        FIG3A_RESPONSE_Y,
        "Figure 3A (% responsive over authors' bound targets)",
        "FIG3A_RESPONSE_Y",
    )
    fig.update_yaxes(row=1, range=list(FIG3A_RESPONSE_Y))

    # Row B is a count in the hundreds, so it is sized from the data unless pinned.
    if FIG3B_TARGET_COUNT_Y is not None:
        count_range = FIG3B_TARGET_COUNT_Y
        _warn_if_clipped(
            all_rows.get("n_bound"),
            count_range,
            "Figure 3B (bound targets)",
            "FIG3B_TARGET_COUNT_Y",
        )
    else:
        count_range = (
            0.0,
            float(all_rows["n_bound"].max()) + FIG3B_TARGET_COUNT_HEADROOM,
        )
    fig.update_yaxes(row=2, range=list(count_range))
    fig.update_yaxes(showticklabels=True)
    fig.update_yaxes(title_text="% responsive", row=1, col=1)
    fig.update_yaxes(title_text="bound targets", row=2, col=1)
    fig.update_xaxes(tickangle=-25, automargin=True)
    fig.update_annotations(font_size=AXIS_TITLE_SIZE - 2, font_color="black")
    fig.update_layout(
        legend=dict(orientation="h", yanchor="bottom", y=1.08, x=0),
        margin=dict(l=80, r=40, t=110, b=110),
    )
    return fig


def _pair_colors(pairs: list[str]) -> dict[str, str]:
    """
    Assign each dataset pair a colour from :data:`PAIR_COLORS`, cycling if needed.

    A plain function of the sorted pair list (not a running counter) so the curve and
    box panels -- called separately, but over the same set of pairs -- assign the same
    pair the same colour.

    :param pairs: Pair names (unique, any order).
    :returns: pair -> colour.

    """
    return {
        pair: PAIR_COLORS[i % len(PAIR_COLORS)] for i, pair in enumerate(sorted(pairs))
    }


def agreement_curve_figure(
    df: pd.DataFrame,
    *,
    title: str | None = None,
    height: int = 560,
    half_life: int | None = None,
) -> go.Figure:
    """
    Log enrichment of top-N overlap against N, one line per dataset pair.

    When ``half_life`` is given, a solid grey trace of the normalised weight
    ``2 ** (-N / half_life)`` -- the same weights :func:`~.queries.weighted_agreement`
    collapses each curve with -- is drawn on a secondary right-hand axis. It is
    illustrative only: it shows *how much* each cutoff counts toward the box plot's
    weighted mean, not a value on the enrichment scale, which is why it gets its own
    axis rather than sharing ``FIG6_ENRICHMENT_Y``.

    :param df: Rows for a single regulator, from ``fetch_agreement``.
    :param title: Optional figure title.
    :param height: Pixel height.
    :param half_life: Weighting half-life to illustrate, in units of N. ``None`` omits
        the weight curve.
    :returns: The figure.

    """
    fig = go.Figure()
    colors = _pair_colors(list(df["pair"].unique()))
    for pair in sorted(df["pair"].unique()):
        sub = df[df["pair"] == pair].sort_values("top_n")
        fig.add_trace(
            go.Scatter(
                x=sub["top_n"],
                y=sub["log2_enrichment"],
                mode="lines+markers",
                name=pair,
                line=dict(width=3, color=colors[pair]),
                marker=dict(size=8, color=colors[pair]),
                hovertemplate=f"{pair}<br>N=%{{x}}<br>%{{y:.2f}}<extra></extra>",
            )
        )
    if half_life is not None and not df.empty:
        cutoffs = sorted(df["top_n"].unique())
        weights = [2.0 ** (-n / half_life) for n in cutoffs]
        fig.add_trace(
            go.Scatter(
                x=cutoffs,
                y=weights,
                mode="lines",
                name=f"weight (half-life {half_life})",
                line=dict(width=2, color="#888"),
                yaxis="y2",
                hovertemplate="weight at N=%{x}: %{y:.2f}<extra></extra>",
            )
        )
    apply_figure_style(
        fig,
        title=title,
        x_title="Top N targets",
        y_title="log2 enrichment of overlap",
        height=height,
    )
    # Linear, not log: 20 evenly-spaced cutoffs (10-200 by 10) don't need a log axis,
    # and a tick at every cutoff reads more directly than a log scale's own ticks.
    # The range starts at 0 -- not the smallest cutoff (10) -- so the curve's rise
    # from the origin is shown, not cropped.
    fig.update_xaxes(type="linear", dtick=FIG6_TOP_N_DTICK, range=list(FIG6_TOP_N_X))
    # Horizontal gridlines add clutter on a line plot with several series already
    # distinguishing themselves by trend, not by reading exact values off a shared
    # scale the way the box plot's one-series-per-x-category layout benefits from.
    fig.update_yaxes(showgrid=False)
    _warn_if_clipped(
        df.get("log2_enrichment"),
        FIG6_ENRICHMENT_Y,
        "Figure 6 curve (log2 overlap enrichment)",
        "FIG6_ENRICHMENT_Y",
    )
    fig.update_yaxes(range=list(FIG6_ENRICHMENT_Y))
    if half_life is not None:
        fig.update_layout(
            yaxis2=dict(
                title=dict(text="relative weight", font=dict(color="black")),
                overlaying="y",
                side="right",
                range=[0, 1],
                tickfont=dict(color="black"),
                showgrid=False,
            )
        )
    # No explicit width: the caller sizes it to half the row. Legend inside, since
    # an outside one would eat a large share of that half.
    fig.update_layout(
        autosize=True,
        legend=inside_legend(),
        margin=dict(l=80, r=70, t=70, b=70),
    )
    return fig


def agreement_box_figure(
    df: pd.DataFrame,
    *,
    title: str | None = None,
    height: int = 560,
    half_life: int | None = None,
) -> go.Figure:
    """
    Distribution across TFs of the weighted enrichment, one box per dataset pair.

    :param df: Rows from ``weighted_agreement``.
    :param title: Optional figure title.
    :param height: Pixel height.
    :param half_life: Half-life the weights were built with, named on the y axis so a
        reader can tell two exports apart. ``None`` leaves it unstated.
    :returns: The figure.

    """
    y_title = (
        "weighted log2 enrichment"
        if half_life is None
        else f"log2 enrichment, half-life {half_life}"
    )
    fig = go.Figure()
    colors = _pair_colors(list(df["pair"].unique()))
    for pair in sorted(df["pair"].unique()):
        sub = df[df["pair"] == pair]
        fig.add_trace(
            go.Box(
                y=sub["weighted_enrichment"],
                name=pair,
                boxpoints="outliers",
                line=dict(width=2, color=colors[pair]),
                marker=dict(size=7, color=colors[pair]),
                showlegend=False,
                hovertemplate="%{y:.2f}<extra></extra>",
            )
        )
    apply_figure_style(
        fig,
        title=title,
        y_title=y_title,
        height=height,
        showlegend=False,
    )
    _warn_if_clipped(
        df.get("weighted_enrichment"),
        FIG6_ENRICHMENT_Y,
        "Figure 6 box (weighted enrichment)",
        "FIG6_ENRICHMENT_Y",
    )
    fig.update_yaxes(range=list(FIG6_ENRICHMENT_Y))
    fig.add_hline(y=0, line_dash="dash", line_color="#888")
    fig.update_xaxes(tickangle=-25, automargin=True)
    fig.update_layout(autosize=True, margin=dict(l=80, r=40, t=80, b=140))
    return fig


def shared_targets_box_figure(
    df: pd.DataFrame,
    *,
    top_n: int,
    title: str | None = None,
    height: int = 520,
) -> go.Figure:
    """
    Distribution across TFs of the targets each dataset pair shares in its top N.

    One box per dataset pair. Pair colours come from :func:`_pair_colors`, so a pair
    matches its colour in figure 6.

    :param df: Rows from ``fetch_shared_targets``.
    :param top_n: The cutoff the counts were measured at, named on the y axis.
    :param title: Optional figure title.
    :param height: Pixel height.
    :returns: The figure.

    """
    fig = go.Figure()
    colors = _pair_colors(list(df["pair"].unique()))
    for pair in sorted(df["pair"].unique()):
        sub = df[df["pair"] == pair]
        fig.add_trace(
            go.Box(
                y=sub["n_shared"],
                name=pair,
                boxpoints="outliers",
                line=dict(width=2, color=colors[pair]),
                marker=dict(size=7, color=colors[pair]),
                showlegend=False,
                hovertemplate="%{y:.0f} shared<extra></extra>",
            )
        )
    apply_figure_style(
        fig,
        title=title,
        y_title=f"Targets in common, top {top_n}",
        height=height,
        showlegend=False,
    )
    # The count is bounded by N, so the axis is pinned to it rather than fitted --
    # keeping every panel at one N comparable, and a box at the ceiling visible.
    fig.update_yaxes(range=[-0.02 * top_n, top_n * 1.02])
    fig.update_xaxes(tickangle=-25, automargin=True)
    fig.update_layout(autosize=True, margin=dict(l=80, r=40, t=80, b=140))
    return fig


def binding_perturbation_box_grid(
    panels: dict[tuple[str, str], pd.DataFrame],
    binding_order: list[str],
    pr_order: list[str],
    box_order: list[str],
    binding_labels: dict[str, str],
    pr_labels: dict[str, str],
    box_labels: dict[str, str],
    box_colors: dict[str, str],
    *,
    y_title: str,
    y_range: tuple[float, float] | None = None,
    panel_width: int = 300,
    panel_height: int = 260,
) -> go.Figure:
    """
    Grid of box plots faceted by binding dataset (rows) and perturbation dataset
    (columns), one box per ``box_key`` (a promoter set or binding method) within each
    cell.

    No existing figure in this app facets on both axes at once before this -- every
    other multi-panel figure here uses subplot rows/columns for one axis and a trace
    loop for the other. This is the first two-axis grid, shared by figure 7 and figure
    9's top (response-rate) grid. Figures 8 and 9's bottom (DTO) grid uses the sibling
    :func:`binding_perturbation_bar_grid` instead.

    :param panels: ``(binding_primary, pr_db) -> rows`` with columns ``box_key``,
        ``value``. A missing or empty entry leaves that cell blank rather than
        raising.
    :param binding_order: Binding db_names, top to bottom.
    :param pr_order: Perturbation db_names, left to right.
    :param box_order: ``box_key`` values, in legend order.
    :param binding_labels: Binding db_name -> row label.
    :param pr_labels: Perturbation db_name -> column label.
    :param box_labels: ``box_key`` -> display label (trace name).
    :param box_colors: ``box_key`` -> colour.
    :param y_title: Shared y-axis title.
    :param y_range: Fixed range, or ``None`` to leave the axis auto-scaled (the caller
        computes any data-driven headroom itself, matching figure 3B's convention).
    :param panel_width: Pixel width per column.
    :param panel_height: Pixel height per row.
    :returns: The figure.

    """
    fig = make_subplots(
        rows=len(binding_order),
        cols=len(pr_order),
        row_titles=[binding_labels.get(b, b) for b in binding_order],
        column_titles=[pr_labels.get(p, p) for p in pr_order],
        shared_yaxes=True,
        vertical_spacing=min(0.08, 1.0 / max(len(binding_order), 1)),
        horizontal_spacing=0.04,
    )
    # One legend entry per box_key, from wherever it first appears -- not simply "the
    # first panel", since a cell can legitimately be missing a box_key (e.g. no
    # regulators cleared the intersection for that one promoter set).
    shown: set[str] = set()
    for i, b_db in enumerate(binding_order, start=1):
        for j, p_db in enumerate(pr_order, start=1):
            cell = panels.get((b_db, p_db))
            if cell is None or cell.empty:
                continue
            for box_key in box_order:
                sub = cell[cell["box_key"] == box_key]
                if sub.empty:
                    continue
                label = box_labels.get(box_key, box_key)
                show = box_key not in shown
                shown.add(box_key)
                fig.add_trace(
                    go.Box(
                        y=sub["value"],
                        name=label,
                        legendgroup=label,
                        showlegend=show,
                        marker=dict(color=box_colors.get(box_key), size=5),
                        line=dict(width=1.5, color=box_colors.get(box_key)),
                        boxpoints="outliers",
                        hovertemplate=f"{label}<br>%{{y:.2f}}<extra></extra>",
                    ),
                    row=i,
                    col=j,
                )
    apply_figure_style(fig, height=panel_height * len(binding_order) + 100)
    if y_range is not None:
        fig.update_yaxes(range=list(y_range))
    # box_key identity is conveyed by colour/legend, not by an x-axis category label --
    # with up to 4 boxes per panel and up to 9 panels, per-panel tick labels would be
    # unreadable clutter.
    fig.update_xaxes(showticklabels=False)
    fig.update_annotations(font_size=AXIS_TITLE_SIZE - 2, font_color="black")
    fig.update_yaxes(title_text=y_title, col=1)
    fig.update_layout(
        width=panel_width * len(pr_order),
        margin=dict(l=90, r=100, t=60, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.06, x=0),
    )
    return fig


def binding_perturbation_bar_grid(
    panels: dict[tuple[str, str], pd.DataFrame],
    binding_order: list[str],
    pr_order: list[str],
    box_order: list[str],
    binding_labels: dict[str, str],
    pr_labels: dict[str, str],
    box_labels: dict[str, str],
    box_colors: dict[str, str],
    *,
    y_title: str = "% of shared TFs (DTO p < 0.01)",
    panel_width: int = 300,
    panel_height: int = 260,
) -> go.Figure:
    """
    Grid of bar charts faceted by binding dataset (rows) and perturbation dataset
    (columns), one bar per ``box_key`` (a promoter set or binding method) within each
    cell -- the bar-chart counterpart of :func:`binding_perturbation_box_grid`, reusing
    its grid/legend/colour conventions but plotting figure 4-style "% of shared TFs
    that are DTO-significant" bars instead of a per-TF value distribution. Used by
    figure 8 and figure 9's bottom (DTO) grid.

    :param panels: ``(binding_primary, pr_db) -> rows`` with columns ``box_key``,
        ``n_significant``, ``n_shared``, ``fraction_significant`` -- the same row
        shape :func:`~tfbpshiny.modules.figures.queries.fetch_dto_significance`
        already returns, plus a ``box_key`` column. A missing or empty entry leaves
        that cell blank rather than raising.
    :param binding_order: Binding db_names, top to bottom.
    :param pr_order: Perturbation db_names, left to right.
    :param box_order: ``box_key`` values, in legend order.
    :param binding_labels: Binding db_name -> row label.
    :param pr_labels: Perturbation db_name -> column label.
    :param box_labels: ``box_key`` -> display label (trace name / legend entry).
    :param box_colors: ``box_key`` -> colour.
    :param y_title: Shared y-axis title.
    :param panel_width: Pixel width per column.
    :param panel_height: Pixel height per row.
    :returns: The figure.

    """
    fig = make_subplots(
        rows=len(binding_order),
        cols=len(pr_order),
        row_titles=[binding_labels.get(b, b) for b in binding_order],
        column_titles=[pr_labels.get(p, p) for p in pr_order],
        shared_yaxes=True,
        vertical_spacing=min(0.08, 1.0 / max(len(binding_order), 1)),
        horizontal_spacing=0.04,
    )
    # One legend entry per box_key, from wherever it first appears -- same dedup rule
    # as binding_perturbation_box_grid (a cell can legitimately be missing a box_key,
    # e.g. no promoter variant resolved for it).
    shown: set[str] = set()
    all_pcts: list[float] = []
    for i, b_db in enumerate(binding_order, start=1):
        for j, p_db in enumerate(pr_order, start=1):
            cell = panels.get((b_db, p_db))
            if cell is None or cell.empty:
                continue
            for box_key in box_order:
                sub = cell[cell["box_key"] == box_key]
                if sub.empty:
                    continue
                row = sub.iloc[0]
                label = box_labels.get(box_key, box_key)
                show = box_key not in shown
                shown.add(box_key)
                pct = float(row["fraction_significant"]) * 100
                all_pcts.append(pct)
                # Explicit x=[label] per trace: unlike go.Box (which gets its own
                # x-slot per trace automatically from `name` when x is omitted),
                # go.Bar has no such default -- an x-less Bar trace sits at index 0
                # for every trace, so distinct box_keys would stack instead of
                # sitting side by side without this.
                fig.add_trace(
                    go.Bar(
                        x=[label],
                        y=[pct],
                        name=label,
                        legendgroup=label,
                        showlegend=show,
                        marker=dict(color=box_colors.get(box_key)),
                        text=[f"{int(row['n_significant'])}/{int(row['n_shared'])}"],
                        textposition="outside",
                        # Outside text near the top of a fixed-range axis would
                        # otherwise be clipped by that range.
                        cliponaxis=False,
                        hovertemplate=(
                            f"{label}<br>%{{y:.1f}}% of shared TFs"
                            "<br>%{text} (DTO-significant / shared TFs)"
                            "<extra></extra>"
                        ),
                    ),
                    row=i,
                    col=j,
                )
    apply_figure_style(fig, height=panel_height * len(binding_order) + 100)
    _warn_if_clipped(
        pd.Series(all_pcts) if all_pcts else None,
        FIG4B_FRACTION_Y,
        "Figures 8/9 (% of shared TFs)",
        "FIG4B_FRACTION_Y",
    )
    fig.update_yaxes(range=list(FIG4B_FRACTION_Y))
    # box_key identity is conveyed by colour/legend, not by an x-axis category label --
    # same rationale as binding_perturbation_box_grid.
    fig.update_xaxes(showticklabels=False)
    # yshift nudges the row/column titles up in pixels so they don't sit on top of the
    # tallest bar's "outside" text label -- the same fix already applied to
    # dto_significance_bars for the same reason (bars carry outside text; the box grid
    # never needed this since boxes don't produce any).
    fig.update_annotations(font_size=AXIS_TITLE_SIZE - 2, font_color="black", yshift=10)
    fig.update_yaxes(title_text=y_title, col=1)
    fig.update_layout(
        width=panel_width * len(pr_order),
        barmode="group",
        margin=dict(l=90, r=100, t=60, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.06, x=0),
    )
    return fig
