"""Sidebar outputs of the Comparison page: metric controls and per-tab controls."""

from __future__ import annotations

from typing import Any

from shiny import render, ui

from tfbpshiny.components import empty_state, sidebar_label
from tfbpshiny.datasets import PRESET_NAMES
from tfbpshiny.modules.comparison.queries import (
    DEFAULT_DTO_RANKING_COLUMN,
    DEFAULT_TOP_N,
    DTO_RANKING_COLUMNS,
    METRIC_DTO,
    PROMOTER_SET_LEVELS,
    TOP_N_CHOICES,
)
from tfbpshiny.modules.comparison.server.context import (
    PRESET_HELP,
    PROMOTER_SET_ALIAS,
    PROMOTER_TOOLTIPS,
    ComparisonContext,
    read_metric,
)
from tfbpshiny.modules.comparison.server.shared import Shared
from tfbpshiny.utils.vdb_init import DEFAULT_RESPONSIVENESS_PRESET


def register_sidebar(
    input: Any, session: Any, ctx: ComparisonContext, shared: Shared
) -> None:
    """
    Register the sidebar outputs.

    :param input: Shiny input object of the comparison module.
    :param session: Module session.
    :param ctx: Per-session context.
    :param shared: Shared helpers.

    """
    binding_index = ctx.binding_index

    @render.ui
    def metric_controls() -> ui.Tag:
        """
        Sidebar controls belonging to the selected metric.

        Top-N and DTO share no parameters, so rather than showing both sets and
        ignoring half, only the relevant ones are rendered.

        :trigger: ``input.metric`` — re-renders when the metric changes.

        """
        if read_metric(input) == METRIC_DTO:
            return ui.div(
                sidebar_label("Perturbation Ranking"),
                ui.input_radio_buttons(
                    "dto_ranking_column",
                    label=None,
                    choices={
                        c: ui.tooltip(
                            ui.span(c),
                            "Which perturbation ranking the DTO run used. Only"
                            " log2fc exists for Overexpression and both Hughes"
                            " sets; TFKO, Hu and Degron carry both.",
                            placement="right",
                        )
                        for c in DTO_RANKING_COLUMNS
                    },
                    selected=DEFAULT_DTO_RANKING_COLUMN,
                    inline=True,
                ),
            )
        return ui.div(
            sidebar_label("Top N"),
            ui.input_radio_buttons(
                "top_n",
                label=None,
                choices={str(n): str(n) for n in TOP_N_CHOICES},
                selected=str(DEFAULT_TOP_N),
                inline=True,
            ),
            ui.input_switch(
                "require_intersecting_floor",
                ui.tooltip(
                    ui.span("Require full overlap"),
                    "When on, only shows regulator/sample pairs whose top-N list is"
                    " complete: at least the selected Top N targets remain after"
                    " ties are resolved (a tie group counts only if its average rank"
                    " is within N). A regulator with too few scored targets, or a"
                    " large tie group around rank N, is excluded. Turn off to keep"
                    " shorter lists.",
                    placement="right",
                ),
                value=True,
            ),
            sidebar_label("Responsiveness"),
            ui.input_radio_buttons(
                "responsiveness_preset",
                label=None,
                choices={
                    name: ui.tooltip(
                        ui.span(name), PRESET_HELP[name], placement="right"
                    )
                    for name in PRESET_NAMES
                },
                selected=DEFAULT_RESPONSIVENESS_PRESET,
                inline=True,
            ),
        )

    @render.ui
    def tab_specific_controls() -> ui.Tag:
        """
        Sidebar controls specific to the active inner tab.

        :trigger: ``input.comparison_inner_tabs`` — re-renders when tab changes.

        """
        tab = shared.inner_tab()
        active = ctx.active_binding_datasets()

        if tab == "Compare Datasets":
            return ui.div(
                sidebar_label("Binding Method"),
                ui.input_select(
                    "cd_binding_method",
                    label=None,
                    choices={
                        "Promoter Enrichment": "Promoter Enrichment",
                        "Peaks": "Peaks",
                    },
                    selected="Promoter Enrichment",
                ),
                sidebar_label("Promoter Set"),
                ui.input_select(
                    "cd_promoter_set",
                    label=None,
                    choices={k: PROMOTER_SET_ALIAS[k] for k in PROMOTER_SET_ALIAS},
                    selected="kang",
                ),
            )

        if tab == "Compare Promoter Definitions":
            return ui.div(
                sidebar_label("Promoter Sets"),
                ui.input_checkbox_group(
                    "cp_included_promoter_sets",
                    label=None,
                    choices={
                        ps: ui.tooltip(
                            ui.span(PROMOTER_SET_ALIAS[ps]),
                            PROMOTER_TOOLTIPS[ps],
                            placement="right",
                        )
                        for ps in PROMOTER_SET_ALIAS
                    },
                    selected=list(PROMOTER_SET_ALIAS.keys()),
                ),
            )

        if tab == "Compare Analysis Methods":
            eligible = [
                db for db in active if binding_index.supports_method_comparison(db)
            ]
            method_choices = {
                db: binding_index.base_label.get(db, db) for db in eligible
            }
            return ui.div(
                sidebar_label("Binding Dataset"),
                ui.input_select(
                    "cm_binding_dataset",
                    label=None,
                    choices=method_choices,
                    selected=next(iter(method_choices), None),
                ),
                sidebar_label("Promoter Set"),
                ui.input_checkbox_group(
                    "cm_promoter_set",
                    label=None,
                    choices={k: PROMOTER_SET_ALIAS[k] for k in PROMOTER_SET_ALIAS},
                    selected=list(PROMOTER_SET_LEVELS),
                ),
                ui.input_switch(
                    "cm_common_regulators_only",
                    ui.tooltip(
                        ui.span("Common regulators only"),
                        "When on, each perturbation table is restricted to"
                        " regulators present in every promoter set x method cell,"
                        " computed separately per perturbation dataset -- so"
                        " percentages across the table are always comparable"
                        " apples-to-apples instead of over different N.",
                        placement="right",
                    ),
                    value=False,
                ),
            )

        return ui.span()

    @render.ui
    def analysis_status() -> ui.Tag:
        """
        Status message when dataset selection is incomplete.

        :trigger: ``active_binding_datasets`` / ``active_perturbation_datasets``.

        """
        if not ctx.active_binding_datasets() or not ctx.active_perturbation_datasets():
            return empty_state(
                ui.p("Select at least one binding and one perturbation dataset."),
            )
        return ui.span()


__all__ = ["register_sidebar"]
