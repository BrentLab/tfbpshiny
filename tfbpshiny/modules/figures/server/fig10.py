"""Figure 10: targets shared between two datasets within the top N."""

from __future__ import annotations

from typing import Any

from shiny import render, ui

from tfbpshiny.components import empty_state
from tfbpshiny.modules.figures.plots import dto_venn_figure, shared_targets_box_figure
from tfbpshiny.modules.figures.queries import fetch_shared_targets, fetch_target_sets
from tfbpshiny.modules.figures.server.context import (
    AGREEMENT_HEADINGS,
    TWO_PANEL_ROW,
    FiguresContext,
)
from tfbpshiny.modules.figures.server.shared import Shared
from tfbpshiny.utils.figure import (
    BINDING_COLORS,
    PERTURBATION_COLORS,
    figure_html,
    matplotlib_svg_html,
)
from tfbpshiny.utils.inputs import read_input
from tfbpshiny.utils.perf import perf


def register_fig10(
    input: Any, session: Any, ctx: FiguresContext, shared: Shared
) -> None:
    """
    Register the two shared-target outputs of figure 10.

    :param input: Shiny input object of the figures module.
    :param session: Module session.
    :param ctx: Per-session context.
    :param shared: Shared reactives.

    """
    conn = ctx.conn

    def _shared_datasets(ctype: str) -> list[str]:
        """
        Datasets figure 10 compares, matching figure 6's defaults so pair labels and
        colours agree between the two.

        Binding is the three 500bp promoter-enrichment variants; perturbation is the
        three headline datasets.

        :param ctype: ``'binding'`` or ``'perturbation'``.
        :returns: db_names present in the agreement table's registry.

        """
        available = ctx.agreement_choices.get(ctype, {})
        return [d for d in ctx.agreement_defaults[ctype] if d in available]

    def _fig_shared_targets_block(ctype: str) -> ui.Tag:
        """
        One figure-10 row: the featured TF's Venn on the left, the distribution of
        shared targets across TFs on the right -- the same order as figure 6.

        Both read ``topn_target_sets`` at the sidebar's Top N, under the app's
        dataset filters, so they describe the same samples.

        :param ctype: ``'binding'`` or ``'perturbation'``.

        """
        heading = AGREEMENT_HEADINGS[ctype]
        if not ctx.schema_current:
            return ctx.needs_rebuild("The top-N target sets")
        datasets = _shared_datasets(ctype)
        top_n = shared.read_top_n()
        filters = ctx.dataset_filters()
        tf = read_input(input, "featured_tf", "", str)
        palette = BINDING_COLORS if ctype == "binding" else PERTURBATION_COLORS
        panels = []
        sets = fetch_target_sets(conn, datasets, tf, top_n, filters) if tf else {}
        if any(sets.values()):
            mpl_fig, _ = dto_venn_figure(
                sets,
                ctx.labels,
                datasets,
                title=f"{heading} — {ctx.reg_labels.get(tf, tf)}, top {top_n}",
                colors=palette,
            )
            panels.append(
                ui.div(
                    matplotlib_svg_html(
                        mpl_fig,
                        alt=f"Top-{top_n} target Venn, {ctype}, {tf}",
                        filename=f"fig10_venn_{ctype}_{tf}_top{top_n}",
                    ),
                    style="flex: 1 1 0; min-width: 380px;",
                )
            )
        df = fetch_shared_targets(conn, ctype, datasets, top_n, filters)
        if not df.empty:
            n_tfs = df["regulator_locus_tag"].nunique()
            fig = shared_targets_box_figure(
                df, top_n=top_n, title=f"{heading} — all TFs (n={n_tfs})"
            )
            panels.append(
                ui.div(
                    figure_html(
                        fig, filename=f"fig10_shared_targets_{ctype}_top{top_n}"
                    ),
                    style="flex: 1 1 0; min-width: 520px;",
                )
            )
        if not panels:
            return empty_state(
                ui.p(f"{heading}: no target sets for these datasets."),
            )
        return ui.div(TWO_PANEL_ROW, *panels)

    @render.ui
    def fig_shared_targets_binding() -> ui.Tag:
        """
        Featured-TF Venn and shared-target boxes, binding vs. binding.

        :trigger: ``input.featured_tf`` / ``input.box_top_n`` / ``dataset_filters``.

        """
        with perf(session.id, "figures.workspace", "fig_shared_targets_binding"):
            return _fig_shared_targets_block("binding")

    @render.ui
    def fig_shared_targets_perturbation() -> ui.Tag:
        """
        Featured-TF Venn and shared-target boxes, perturbation vs. perturbation.

        :trigger: ``input.featured_tf`` / ``input.box_top_n`` / ``dataset_filters``.

        """
        with perf(session.id, "figures.workspace", "fig_shared_targets_perturbation"):
            return _fig_shared_targets_block("perturbation")


__all__ = ["register_fig10"]
