"""Figure 6: agreement between datasets as top-N overlap enrichment."""

from __future__ import annotations

from typing import Any

import pandas as pd
from shiny import reactive, render, ui

from tfbpshiny.components import empty_state, sidebar_label
from tfbpshiny.modules.figures.plots import (
    agreement_box_figure,
    agreement_curve_figure,
)
from tfbpshiny.modules.figures.queries import (
    AGREEMENT_HALF_LIFE_DEFAULT,
    AGREEMENT_PAIR_WARN,
    fetch_agreement,
    weighted_agreement,
)
from tfbpshiny.modules.figures.server.context import (
    AGREEMENT_HEADINGS,
    TWO_PANEL_ROW,
    FiguresContext,
)
from tfbpshiny.modules.figures.server.shared import Shared
from tfbpshiny.utils.figure import figure_html
from tfbpshiny.utils.inputs import read_input
from tfbpshiny.utils.perf import perf


def register_fig6(
    input: Any, session: Any, ctx: FiguresContext, shared: Shared
) -> None:
    """
    Register the dataset picker and the two agreement outputs of figure 6.

    :param input: Shiny input object of the figures module.
    :param session: Module session.
    :param ctx: Per-session context.
    :param shared: Shared reactives.

    """
    conn = ctx.conn

    @render.ui
    def agreement_dataset_picker() -> ui.Tag:
        """
        Checkbox groups choosing which datasets figure 6 compares.

        Rendered rather than static so the choices come from ``dataset_registry``
        instead of a hand-maintained list that could drift from the database.

        :trigger: none -- the registry is fixed for the session.

        """
        groups = []
        for ctype, heading in (
            ("binding", "Binding"),
            ("perturbation", "Perturbation"),
        ):
            choices = ctx.agreement_choices.get(ctype, {})
            if not choices:
                continue
            selected = [d for d in ctx.agreement_defaults[ctype] if d in choices]
            groups.append(
                ui.div(
                    sidebar_label(heading),
                    ui.input_checkbox_group(
                        f"agreement_{ctype}",
                        label=None,
                        choices=choices,
                        selected=selected,
                    ),
                    style="flex: 1 1 260px;",
                )
            )
        if not groups:
            return ui.div()
        return ui.div(
            *groups,
            style="display: flex; gap: 2rem; flex-wrap: wrap;",
        )

    def _agreement_selection(ctype: str) -> list[str]:
        """
        Datasets selected for one panel, falling back to the default.

        :param ctype: ``'binding'`` or ``'perturbation'``.
        :returns: db_names, empty when fewer than two are selected.

        """
        choices = ctx.agreement_choices.get(ctype, {})
        chosen: list[str] = list(read_input(input, f"agreement_{ctype}", [], list))
        if not chosen:
            chosen = list(ctx.agreement_defaults[ctype])
        return [d for d in chosen if d in choices]

    @reactive.calc
    def _agreement() -> dict[str, pd.DataFrame]:
        """
        Overlap enrichment for binding-vs-binding and perturbation-vs-perturbation.

        :trigger: ``input.agreement_binding`` / ``input.agreement_perturbation`` --
            every pair among the selected datasets is drawn -- and ``dataset_filters``.

        """
        if not ctx.schema_current:
            return {}
        filters = ctx.dataset_filters()
        with perf(session.id, "figures.workspace", "_agreement", kind="data"):
            out: dict[str, pd.DataFrame] = {}
            for ctype in ("binding", "perturbation"):
                selected = _agreement_selection(ctype)
                n_pairs = len(selected) * (len(selected) - 1) // 2
                if n_pairs > AGREEMENT_PAIR_WARN:
                    ctx.logger.warning(
                        "figures: %s agreement has %d dataset pairs selected"
                        " (%d datasets); above %d the lines and boxes overlap"
                        " too much to separate",
                        ctype,
                        n_pairs,
                        len(selected),
                        AGREEMENT_PAIR_WARN,
                    )
                out[ctype] = fetch_agreement(conn, ctype, selected, filters)
            return out

    def _read_half_life(ctype: str) -> int:
        """
        The selected exponential weighting half-life for one panel, in units of N.

        Binding and perturbation have separate sliders -- they are ranked on
        different quantities (rank column vs. absolute effect) and need not decay at
        the same rate. Falls back to the default before the slider has registered.

        :param ctype: ``'binding'`` or ``'perturbation'``.

        """
        return read_input(
            input, f"agreement_half_life_{ctype}", AGREEMENT_HALF_LIFE_DEFAULT, int
        )

    def _agreement_empty_note(ctype: str, heading: str) -> ui.Tag | None:
        """
        Explain why one panel of figure 6 drew nothing.

        Emitted per panel rather than for the figure as a whole: the perturbation
        datasets have no promoter variants and so were always materialized, and its
        panel rendering would otherwise hide the binding panel's absence entirely.

        :param ctype: ``'binding'`` or ``'perturbation'``.
        :param heading: Panel heading to name in the message.
        :returns: An empty-state div, or ``None`` when nothing needs saying.

        """
        selected = _agreement_selection(ctype)
        if len(selected) < 2:
            return empty_state(
                ui.p(f"{heading}: select at least two datasets to compare."),
            )
        return empty_state(
            ui.p(
                ui.strong(f"{heading}: no overlap rows for these datasets."),
                " Databases built before figure 6 gained its dataset selector"
                " cover only the four primary binding datasets. Rebuild with ",
                ui.tags.code("tfbpshiny materialize"),
                " to compare promoter definitions and calling methods.",
            ),
        )

    def _fig_agreement_block(ctype: str) -> ui.Tag:
        """
        One figure-6 block (curve + weighted box) for one comparison type.

        Factored out of a single combined render so the binding and perturbation
        blocks can sit in separate ``ui.output_ui`` slots -- each with its own
        weighting-half-life slider immediately above it, rather than both sliders
        stacked above both plots.

        :param ctype: ``'binding'`` or ``'perturbation'``.

        """
        heading = AGREEMENT_HEADINGS[ctype]
        if not ctx.schema_current:
            return ctx.needs_rebuild("The dataset-agreement table")
        tf = read_input(input, "featured_tf", "", str)
        half_life = _read_half_life(ctype)
        df = _agreement().get(ctype, pd.DataFrame())
        if df.empty:
            note = _agreement_empty_note(ctype, heading)
            return note if note is not None else ui.div()
        curve_src = df[df["regulator_locus_tag"] == tf] if tf else df
        panels = []
        if not curve_src.empty:
            panels.append(
                ui.div(
                    figure_html(
                        agreement_curve_figure(
                            curve_src,
                            title=(f"{heading} — {ctx.reg_labels.get(tf, tf)}"),
                            half_life=half_life,
                        ),
                        filename=f"fig6_agreement_curve_{ctype}_{tf}",
                    ),
                    style="flex: 1 1 0; min-width: 520px;",
                )
            )
        weighted = weighted_agreement(df, half_life=half_life)
        if not weighted.empty:
            panels.append(
                ui.div(
                    figure_html(
                        agreement_box_figure(
                            weighted,
                            title=f"{heading} — all TFs",
                            half_life=half_life,
                        ),
                        filename=f"fig6_agreement_weighted_{ctype}_hl{half_life}",
                    ),
                    style="flex: 1 1 0; min-width: 520px;",
                )
            )
        if not panels:
            return empty_state(ui.p("No agreement results."))
        return ui.div(TWO_PANEL_ROW, *panels)

    @render.ui
    def fig_agreement_binding() -> ui.Tag:
        """
        Overlap enrichment vs N, binding vs. binding.

        :trigger: ``_agreement`` / ``input.featured_tf`` /
            ``input.agreement_half_life_binding``.

        """
        with perf(session.id, "figures.workspace", "fig_agreement_binding"):
            return _fig_agreement_block("binding")

    @render.ui
    def fig_agreement_perturbation() -> ui.Tag:
        """
        Overlap enrichment vs N, perturbation vs. perturbation.

        :trigger: ``_agreement`` / ``input.featured_tf`` /
            ``input.agreement_half_life_perturbation``.

        """
        with perf(session.id, "figures.workspace", "fig_agreement_perturbation"):
            return _fig_agreement_block("perturbation")


__all__ = ["register_fig6"]
