"""Figures 4 and 5: DTO significance bars and the DTO-significance Venn diagrams."""

from __future__ import annotations

from typing import Any

from shiny import render, ui

from tfbpshiny.components import empty_state, scroll_row
from tfbpshiny.modules.figures.plots import dto_significance_bars, dto_venn_figure
from tfbpshiny.modules.figures.queries import (
    DTO_BINDING_ORDER,
    PR_ORDER,
    fetch_dto_significance,
    fetch_dto_significant_sets,
)
from tfbpshiny.modules.figures.server.context import FiguresContext
from tfbpshiny.modules.figures.server.shared import Shared
from tfbpshiny.utils.figure import figure_html, matplotlib_svg_html
from tfbpshiny.utils.perf import perf


def register_fig4_5(
    input: Any, session: Any, ctx: FiguresContext, shared: Shared
) -> None:
    """
    Register the outputs of figures 4 and 5.

    :param input: Shiny input object of the figures module.
    :param session: Module session.
    :param ctx: Per-session context.
    :param shared: Shared reactives.

    """
    conn = ctx.conn

    @render.ui
    def fig_dto_bars() -> ui.Tag:
        """
        DTO-significant counts and fractions.

        :trigger: none beyond the database -- DTO is not sample-filtered here.

        """
        if not ctx.schema_current:
            return shared.dto_missing()
        with perf(session.id, "figures.workspace", "fig_dto_bars"):
            df = fetch_dto_significance(conn, list(DTO_BINDING_ORDER), list(PR_ORDER))
            if df.empty:
                return empty_state(ui.p("No DTO results."))
            fig = dto_significance_bars(
                df, ctx.labels, list(DTO_BINDING_ORDER), list(PR_ORDER)
            )
            return ui.div(
                figure_html(fig, filename="fig4_dto_significance"),
                ui.p(
                    {"class": "sidebar-text"},
                    ui.tags.em(
                        "ChIP-chip is absent because the upstream DTO analysis"
                        " does not cover it."
                    ),
                ),
            )

    @render.ui
    def fig_dto_venn() -> ui.Tag:
        """
        Venn diagrams of DTO significance across the three binding datasets.

        :trigger: ``input.dto_venn_layout`` -- toggles between the default
            (exact-when-possible, else equal circles) and cost-based (approximate,
            more often proportional) layouts.

        """
        if not ctx.schema_current:
            return shared.dto_missing()
        layout = shared.read_dto_venn_layout()
        with perf(session.id, "figures.workspace", "fig_dto_venn"):
            panels = []
            for p in PR_ORDER:
                sets = fetch_dto_significant_sets(conn, list(DTO_BINDING_ORDER), p)
                if not any(sets.values()):
                    continue
                mpl_fig, _ = dto_venn_figure(
                    sets,
                    ctx.labels,
                    list(DTO_BINDING_ORDER),
                    title=ctx.labels.get(p, p),
                    layout=layout,
                )
                panels.append(
                    ui.div(
                        matplotlib_svg_html(
                            mpl_fig,
                            alt=f"DTO significance Venn, {p}",
                            filename=f"fig5_dto_venn_{p}",
                        ),
                        style="min-width: 380px; flex: 1 1 380px;",
                    )
                )
            if not panels:
                return empty_state(ui.p("No DTO results."))
            return scroll_row(*panels, gap="lg")


__all__ = ["register_fig4_5"]
