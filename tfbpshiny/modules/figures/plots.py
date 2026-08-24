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
    BINDING_COLORS,
    FONT_SIZE,
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
FIG1_RANK_X: tuple[float, float] = (0.0, 100.0)

#: Figure 2, percent responsive among top-N binding targets. A percentage.
FIG2_TOPN_BOX_Y: tuple[float, float] = (0.0, 100.0)

#: Figure 3A, percent responsive over the authors' bound targets. A percentage.
FIG3A_RESPONSE_Y: tuple[float, float] = (0.0, 100.0)

#: Figure 3B, number of bound targets. A count, not a percentage, and routinely in the
#: hundreds -- so it is sized from the data plus headroom rather than pinned to 100.
#: Set FIG3B_TARGET_COUNT_Y to a tuple to pin it instead.
FIG3B_TARGET_COUNT_HEADROOM: float = 10.0
FIG3B_TARGET_COUNT_Y: tuple[float, float] | None = None

#: Figure 4A, number of DTO-significant TFs. A count: 0 to the observed max plus
#: headroom. Set FIG4A_COUNT_Y to a tuple to pin it instead.
FIG4A_COUNT_HEADROOM: float = 10.0
FIG4A_COUNT_Y: tuple[float, float] | None = None

#: Figure 4B, DTO-significant TFs as a percentage of shared TFs.
FIG4B_FRACTION_Y: tuple[float, float] = (0.0, 100.0)

#: Figure 6, log2 enrichment of top-N overlap. Note enrichment goes *negative* when an
#: overlap is smaller than chance, which a floor of 0 clips; the warning will say so.
FIG6_ENRICHMENT_Y: tuple[float, float] = (-3, 10.0)


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


def rank_response_figure(
    df: pd.DataFrame,
    labels: dict[str, str],
    binding_order: list[str],
    *,
    title: str | None = None,
    height: int = 480,
) -> go.Figure:
    """
    Response rate against binding rank for a single regulator.

    One line per binding dataset. The x axis is ``n`` -- the number of targets actually
    summarised -- rather than the nominal ``top_n``, because ties at the cutoff let more
    than ``top_n`` rows through.

    :param df: Rows for one regulator, from ``fetch_rank_response``.
    :param labels: db_name -> display label.
    :param binding_order: db_names in the order they should be drawn.
    :param title: Optional figure title.
    :param height: Pixel height.
    :returns: The figure.

    """
    fig = go.Figure()
    for db in binding_order:
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
                line=dict(width=3, color=BINDING_COLORS.get(label)),
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


def rank_response_facet(
    df: pd.DataFrame,
    labels: dict[str, str],
    binding_order: list[str],
    regulators: list[str],
    reg_labels: dict[str, str],
    *,
    n_cols: int = 6,
    panel_height: int = 200,
) -> go.Figure:
    """
    Small-multiples grid of rank-response curves, one panel per regulator.

    Drawn as a single figure with subplots rather than many separate figures: the
    intersections run to ~60-70 regulators, and one figure with N panels is markedly
    cheaper to build and render than N figures.

    :param df: All rows from ``fetch_rank_response``.
    :param labels: db_name -> display label.
    :param binding_order: db_names in draw order.
    :param regulators: Regulators to panel, in order.
    :param reg_labels: locus tag -> display label.
    :param n_cols: Panels per row.
    :param panel_height: Pixel height per row of panels.
    :returns: The figure.

    """
    if not regulators:
        return go.Figure()
    n_rows = (len(regulators) + n_cols - 1) // n_cols
    fig = make_subplots(
        rows=n_rows,
        cols=n_cols,
        subplot_titles=[reg_labels.get(r, r) for r in regulators],
        shared_yaxes=True,
        vertical_spacing=min(0.06, 1.0 / max(n_rows, 1)),
        horizontal_spacing=0.02,
    )
    for i, reg in enumerate(regulators):
        row, col = divmod(i, n_cols)
        row += 1
        col += 1
        sub_reg = df[df["regulator_locus_tag"] == reg]
        for db in binding_order:
            sub = sub_reg[sub_reg["binding_db"] == db].sort_values("n")
            if sub.empty:
                continue
            label = labels.get(db, db)
            fig.add_trace(
                go.Scatter(
                    x=sub["n"],
                    y=sub["percent_responsive"],
                    mode="lines",
                    name=label,
                    legendgroup=label,
                    # Only the first panel contributes to the legend, otherwise every
                    # dataset appears once per panel.
                    showlegend=(i == 0),
                    line=dict(width=2, color=BINDING_COLORS.get(label)),
                    hovertemplate=(
                        f"{reg_labels.get(reg, reg)}<br>{label}"
                        "<br>n=%{x}<br>%{y:.1f}%<extra></extra>"
                    ),
                ),
                row=row,
                col=col,
            )
    apply_figure_style(fig, height=panel_height * n_rows + 120)
    fig.update_annotations(font_size=FONT_SIZE - 2)
    fig.update_xaxes(
        title_text="", range=list(FIG1_RANK_X), tickfont=dict(size=FONT_SIZE - 4)
    )
    _warn_if_clipped(
        df.get("percent_responsive"),
        FIG1_RANK_RESPONSE_Y,
        "Figure 1 facets (rank vs. response)",
        "FIG1_RANK_RESPONSE_Y",
    )
    _warn_if_clipped(df.get("n"), FIG1_RANK_X, "Figure 1 facets x axis", "FIG1_RANK_X")
    fig.update_yaxes(
        title_text="",
        range=list(FIG1_RANK_RESPONSE_Y),
        tickfont=dict(size=FONT_SIZE - 4),
    )
    fig.update_layout(
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(l=50, r=20, t=90, b=40),
    )
    return fig


def percent_responsive_boxes(
    df: pd.DataFrame,
    labels: dict[str, str],
    binding_order: list[str],
    *,
    title: str | None = None,
    y_title: str = "% responsive in top 25",
    height: int = 460,
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
    :returns: The figure.

    """
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
                marker=dict(color=BINDING_COLORS.get(label), size=7),
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
) -> go.Figure:
    """
    DTO-significant regulator counts (row A) and fractions (row B).

    Two rows with one y axis each rather than a single row of twin-axis panels: a count
    and a percentage on the same panel invite reading one against the other's scale.

    :param df: Rows from ``fetch_dto_significance``.
    :param labels: db_name -> display label.
    :param binding_order: Binding db_names in draw order.
    :param pr_order: Perturbation db_names, one column each.
    :param row_height: Pixel height per row.
    :param panel_width: Pixel width per column. The dataset names are long, so the
        figure is given an explicit width rather than squeezed to its container.
    :returns: The figure.

    """
    fig = make_subplots(
        rows=2,
        cols=len(pr_order),
        subplot_titles=(
            [f"A. TFs with DTO p < 0.01 — {labels.get(p, p)}" for p in pr_order]
            + [f"B. % of shared TFs — {labels.get(p, p)}" for p in pr_order]
        ),
        shared_yaxes=True,
        vertical_spacing=0.16,
        horizontal_spacing=0.05,
    )
    for j, p_db in enumerate(pr_order, start=1):
        sub = df[df["perturbation_db"] == p_db]
        if sub.empty:
            continue
        sub = sub.set_index("binding_db").reindex(binding_order).dropna(how="all")
        names = [labels.get(b, b) for b in sub.index]
        colours = [BINDING_COLORS.get(n) for n in names]
        fig.add_trace(
            go.Bar(
                x=names,
                y=sub["n_significant"],
                marker=dict(color=colours),
                showlegend=False,
                hovertemplate="%{x}<br>%{y} TFs<extra></extra>",
            ),
            row=1,
            col=j,
        )
        fig.add_trace(
            go.Bar(
                x=names,
                y=sub["fraction_significant"] * 100,
                marker=dict(color=colours),
                showlegend=False,
                hovertemplate="%{x}<br>%{y:.1f}% of shared TFs<extra></extra>",
            ),
            row=2,
            col=j,
        )

    apply_figure_style(fig, height=row_height * 2 + 140, showlegend=False)

    # Row A is a count: 0 to the observed max plus headroom, unless pinned.
    if FIG4A_COUNT_Y is not None:
        count_range = FIG4A_COUNT_Y
        _warn_if_clipped(
            df.get("n_significant"),
            count_range,
            "Figure 4A (DTO-significant TF counts)",
            "FIG4A_COUNT_Y",
        )
    else:
        count_range = (
            0.0,
            float(df["n_significant"].max()) + FIG4A_COUNT_HEADROOM,
        )
    fig.update_yaxes(row=1, range=list(count_range))

    _warn_if_clipped(
        df["fraction_significant"] * 100 if "fraction_significant" in df else None,
        FIG4B_FRACTION_Y,
        "Figure 4B (% of shared TFs)",
        "FIG4B_FRACTION_Y",
    )
    fig.update_yaxes(row=2, range=list(FIG4B_FRACTION_Y))
    fig.update_yaxes(title_text="TFs", row=1, col=1)
    fig.update_yaxes(title_text="% of shared TFs", row=2, col=1)
    fig.update_xaxes(tickangle=-30, automargin=True)
    fig.update_annotations(font_size=AXIS_TITLE_SIZE - 2)
    fig.update_layout(
        width=panel_width * len(pr_order), margin=dict(l=80, r=40, t=110, b=130)
    )
    return fig


def dto_venn_figure(
    sets: dict[str, set[str]],
    labels: dict[str, str],
    binding_order: list[str],
    *,
    title: str = "",
) -> Any:
    """
    Three-set Venn of DTO-significant regulators, as a matplotlib figure.

    plotly has no Venn primitive, so this is the one figure rendered through
    matplotlib. The caller converts it with
    :func:`tfbpshiny.utils.figure.matplotlib_png_html`.

    :param sets: binding db_name -> set of significant locus tags.
    :param labels: db_name -> display label.
    :param binding_order: Exactly three binding db_names, in circle order.
    :param title: Figure title.
    :returns: A ``matplotlib.figure.Figure``.

    """
    import warnings

    from matplotlib.figure import Figure
    from matplotlib_venn import venn3
    from matplotlib_venn.layout.venn3 import DefaultLayoutAlgorithm

    fig = Figure(figsize=(5.5, 5.0))
    ax = fig.subplots()
    ordered = [sets.get(b, set()) for b in binding_order]
    names = tuple(labels.get(b, b) for b in binding_order)

    # Try the area-proportional layout first. For some size combinations no valid
    # three-circle arrangement exists, and matplotlib_venn warns and then draws areas
    # that do NOT match the counts -- worse than not implying proportion at all. Fall
    # back to equal circles in that case; the region counts stay correct either way.
    proportional = True
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        v = venn3(ordered, set_labels=names, ax=ax)
        if any("circle" in str(w.message).lower() for w in caught):
            proportional = False

    if not proportional:
        ax.clear()
        # Equal-area circles. `venn3_unweighted` is deprecated in matplotlib_venn
        # 1.1 and errors out, so drive the layout algorithm directly.
        v = venn3(
            ordered,
            set_labels=names,
            ax=ax,
            layout_algorithm=DefaultLayoutAlgorithm(
                fixed_subset_sizes=(1, 1, 1, 1, 1, 1, 1)
            ),
        )

    for text in ax.texts:
        text.set_fontsize(13)
    if v is not None:
        for label in v.set_labels or []:
            if label is not None:
                label.set_fontsize(14)
    suffix = "" if proportional else "  (circles not to scale)"
    ax.set_title(f"{title}{suffix}", fontsize=16)
    return fig


__all__ = [
    "agreement_box_figure",
    "agreement_curve_figure",
    "authors_bound_grid",
    "dto_significance_bars",
    "dto_venn_figure",
    "percent_responsive_boxes",
    "rank_response_facet",
    "rank_response_figure",
]


def authors_bound_grid(
    frames: dict[str, pd.DataFrame],
    labels: dict[str, str],
    binding_order: list[str],
    pr_order: list[str],
    *,
    panel_width: int = 420,
    row_height: int = 380,
) -> go.Figure:
    """
    Response rate (row A) and bound-set size (row B) over the authors' bound targets.

    Two rows, each with a single y axis, rather than one row of twin-axis panels: with
    two boxes sharing a panel it is never obvious which axis a box belongs to, and the
    two quantities have unrelated units.

    Each row shares one y range across its panels, so panel-to-panel differences are
    data rather than axis differences. A tighter authors' threshold shows as a higher
    box in row A above a lower box in row B.

    :param frames: perturbation db_name -> rows from ``fetch_authors_bound``.
    :param labels: db_name -> display label.
    :param binding_order: Peak binding db_names in draw order.
    :param pr_order: Perturbation db_names, one column each.
    :param panel_width: Pixel width per column.
    :param row_height: Pixel height per row.
    :returns: The figure.

    """
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
        shared_yaxes=True,
        vertical_spacing=0.14,
        horizontal_spacing=0.05,
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
                        marker=dict(color=BINDING_COLORS.get(label), size=7),
                        line=dict(width=2),
                        boxpoints="outliers",
                    ),
                    row=row,
                    col=j,
                )

    apply_figure_style(fig, height=row_height * 2 + 140)
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
    fig.update_yaxes(title_text="% responsive", row=1, col=1)
    fig.update_yaxes(title_text="bound targets", row=2, col=1)
    fig.update_xaxes(tickangle=-25, automargin=True)
    fig.update_annotations(font_size=AXIS_TITLE_SIZE - 2)
    fig.update_layout(
        width=panel_width * len(cols),
        legend=dict(orientation="h", yanchor="bottom", y=1.08, x=0),
        margin=dict(l=80, r=40, t=110, b=110),
    )
    return fig


def agreement_curve_figure(
    df: pd.DataFrame,
    *,
    title: str | None = None,
    height: int = 560,
) -> go.Figure:
    """
    Log enrichment of top-N overlap against N, one line per dataset pair.

    :param df: Rows for a single regulator, from ``fetch_agreement``.
    :param title: Optional figure title.
    :param height: Pixel height.
    :returns: The figure.

    """
    fig = go.Figure()
    for pair in sorted(df["pair"].unique()):
        sub = df[df["pair"] == pair].sort_values("top_n")
        fig.add_trace(
            go.Scatter(
                x=sub["top_n"],
                y=sub["log2_enrichment"],
                mode="lines+markers",
                name=pair,
                line=dict(width=3),
                marker=dict(size=8),
                hovertemplate=f"{pair}<br>N=%{{x}}<br>%{{y:.2f}}<extra></extra>",
            )
        )
    apply_figure_style(
        fig,
        title=title,
        x_title="Top N targets",
        y_title="log2 enrichment of overlap",
        height=height,
    )
    fig.update_xaxes(type="log")
    _warn_if_clipped(
        df.get("log2_enrichment"),
        FIG6_ENRICHMENT_Y,
        "Figure 6 curve (log2 overlap enrichment)",
        "FIG6_ENRICHMENT_Y",
    )
    fig.update_yaxes(range=list(FIG6_ENRICHMENT_Y))
    # Zero means "exactly what chance would give", so mark it explicitly.
    fig.add_hline(y=0, line_dash="dash", line_color="#888")
    # No explicit width: the caller sizes it to half the row. Legend inside, since
    # an outside one would eat a large share of that half.
    fig.update_layout(
        autosize=True,
        legend=inside_legend(),
        margin=dict(l=80, r=40, t=70, b=70),
    )
    return fig


def agreement_box_figure(
    df: pd.DataFrame,
    *,
    title: str | None = None,
    height: int = 560,
) -> go.Figure:
    """
    Distribution across TFs of the 1/N-weighted enrichment, one box per dataset pair.

    :param df: Rows from ``weighted_agreement``.
    :param title: Optional figure title.
    :param height: Pixel height.
    :returns: The figure.

    """
    fig = go.Figure()
    for pair in sorted(df["pair"].unique()):
        sub = df[df["pair"] == pair]
        fig.add_trace(
            go.Box(
                y=sub["weighted_enrichment"],
                name=pair,
                boxpoints="outliers",
                line=dict(width=2),
                marker=dict(size=7),
                showlegend=False,
                hovertemplate="%{y:.2f}<extra></extra>",
            )
        )
    apply_figure_style(
        fig,
        title=title,
        y_title="1/N-weighted log2 enrichment",
        height=height,
        showlegend=False,
    )
    _warn_if_clipped(
        df.get("weighted_enrichment"),
        FIG6_ENRICHMENT_Y,
        "Figure 6 box (1/N-weighted enrichment)",
        "FIG6_ENRICHMENT_Y",
    )
    fig.update_yaxes(range=list(FIG6_ENRICHMENT_Y))
    fig.add_hline(y=0, line_dash="dash", line_color="#888")
    fig.update_xaxes(tickangle=-25, automargin=True)
    fig.update_layout(autosize=True, margin=dict(l=80, r=40, t=80, b=140))
    return fig
