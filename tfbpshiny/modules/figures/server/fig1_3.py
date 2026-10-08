"""Figures 1-3: rank-response curves, top-N response boxes, authors' thresholds."""

from __future__ import annotations

from typing import Any

import pandas as pd
from shiny import render, ui

from tfbpshiny.components import empty_state, scroll_row
from tfbpshiny.modules.figures.plots import (
    authors_bound_grid,
    percent_responsive_boxes,
    rank_response_facet,
    rank_response_figure,
)
from tfbpshiny.modules.figures.queries import (
    AUTHORS_PEAK_BINDING,
    BINDING_ORDER,
    PR_ORDER,
    fetch_authors_bound,
    fetch_topn_percent_responsive,
)
from tfbpshiny.modules.figures.server.context import PANEL_WIDTH, FiguresContext
from tfbpshiny.modules.figures.server.shared import Shared
from tfbpshiny.utils.figure import figure_html
from tfbpshiny.utils.inputs import read_input
from tfbpshiny.utils.perf import perf


def register_fig1_3(
    input: Any, session: Any, ctx: FiguresContext, shared: Shared
) -> None:
    """
    Register the outputs of figures 1, 2 and 3.

    :param input: Shiny input object of the figures module.
    :param session: Module session.
    :param ctx: Per-session context.
    :param shared: Shared reactives.

    """
    conn = ctx.conn

    # ------------------------------------------------------------------
    # Figure 1
    # ------------------------------------------------------------------

    @render.ui
    def fig_rank_response() -> ui.Tag:
        """
        Rank-response curves for the featured TF, one panel per PR dataset.

        :trigger: ``_rank_response`` / ``input.featured_tf``.

        """
        tf = read_input(input, "featured_tf", None, str)
        if tf is None:
            return ui.span()
        data = shared.rank_response()
        with perf(session.id, "figures.workspace", "fig_rank_response"):
            panels = []
            for p in PR_ORDER:
                df = data.get(p, pd.DataFrame())
                if df.empty:
                    continue
                sub = df[df["regulator_locus_tag"] == tf]
                if sub.empty:
                    continue
                fig = rank_response_figure(
                    sub,
                    ctx.labels,
                    list(BINDING_ORDER),
                    title=f"{ctx.labels.get(p, p)} — {ctx.reg_labels.get(tf, tf)}",
                    colors=ctx.binding_colors,
                )
                panels.append(
                    ui.div(
                        figure_html(fig, filename=f"fig1_rank_response_{p}_{tf}"),
                        style=PANEL_WIDTH,
                    )
                )
            if not panels:
                return empty_state(
                    ui.p("No rank-response data for the selected TF."),
                )
            return scroll_row(*panels, gap="lg")

    @render.ui
    def fig_rank_response_facets() -> ui.Tag:
        """
        Small-multiples grid over every TF in the intersection.

        :trigger: ``input.show_facets`` / ``_rank_response``.

        """
        if not read_input(input, "show_facets", False, bool):
            return ui.span()
        data = shared.rank_response()
        sets = shared.tf_sets()
        with perf(session.id, "figures.workspace", "fig_rank_response_facets"):
            blocks = []
            for p in PR_ORDER:
                df = data.get(p, pd.DataFrame())
                tfs = sets.get(p, [])
                if df.empty or not tfs:
                    continue
                fig = rank_response_facet(
                    df,
                    ctx.labels,
                    list(BINDING_ORDER),
                    tfs,
                    ctx.reg_labels,
                    colors=ctx.binding_colors,
                )
                blocks.append(
                    ui.div(
                        ui.h4(
                            f"{ctx.labels.get(p, p)} — all {len(tfs)} TFs",
                            style="margin-top: 1.5rem;",
                        ),
                        figure_html(fig, filename=f"fig1_rank_response_all_{p}"),
                    )
                )
            if not blocks:
                return ui.span()
            return ui.div(*blocks)

    # ------------------------------------------------------------------
    # Figure 2
    # ------------------------------------------------------------------

    @render.ui
    def fig_topn_boxes() -> ui.Tag:
        """
        Percent-responsive box plots at the selected top-N cutoff.

        :trigger: ``dataset_filters`` / ``input.box_top_n``.

        """
        filters = ctx.dataset_filters()
        sets = shared.tf_sets()
        top_n = shared.read_top_n()
        preset = shared.read_scoring()
        with perf(session.id, "figures.workspace", "fig_topn_boxes"):
            panels = []
            for p in PR_ORDER:
                tfs = sets.get(p, [])
                if not tfs:
                    continue
                df = fetch_topn_percent_responsive(
                    conn, list(BINDING_ORDER), p, tfs, top_n, filters, preset
                )
                if df.empty:
                    continue
                fig = percent_responsive_boxes(
                    df,
                    ctx.labels,
                    list(BINDING_ORDER),
                    title=f"{ctx.labels.get(p, p)}  (n={len(tfs)} TFs)",
                    y_title=f"% responsive in top {top_n}",
                    colors=ctx.binding_colors,
                )
                panels.append(
                    ui.div(
                        figure_html(fig, filename=f"fig2_top{top_n}_responsive_{p}"),
                        style=PANEL_WIDTH,
                    )
                )
            if not panels:
                return empty_state(ui.p("No data for these datasets."))
            return scroll_row(*panels, gap="lg")

    # ------------------------------------------------------------------
    # Figure 3 -- authors' binding thresholds
    # ------------------------------------------------------------------

    @render.ui
    def fig_authors_bound() -> ui.Tag:
        """
        Response rate and bound-set size over the authors' bound targets.

        :trigger: ``dataset_filters``.

        """
        if not ctx.schema_current:
            return ctx.needs_rebuild("The authors'-binding-threshold data")
        filters = ctx.dataset_filters()
        preset = shared.read_scoring()
        with perf(session.id, "figures.workspace", "fig_authors_bound"):
            frames = {
                p: fetch_authors_bound(
                    conn, list(AUTHORS_PEAK_BINDING), p, filters, preset
                )
                for p in PR_ORDER
            }
            frames = {k: v for k, v in frames.items() if not v.empty}
            if not frames:
                return empty_state(ui.p("No authors'-threshold rows."))
            fig = authors_bound_grid(
                frames,
                ctx.labels,
                list(AUTHORS_PEAK_BINDING),
                list(PR_ORDER),
                colors=ctx.binding_colors,
            )
            return ui.div(figure_html(fig, filename="fig3_authors_bound"))


__all__ = ["register_fig1_3"]
