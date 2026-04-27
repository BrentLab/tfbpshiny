"""UI functions for the Perturbation analysis page."""

from __future__ import annotations

from shiny import module, ui

from tfbpshiny.components import (
    sidebar_heading,
    sidebar_label,
    sidebar_shell,
    workspace_heading,
    workspace_shell,
)
from tfbpshiny.modules.perturbation.queries import (
    DEFAULT_COL_PREFERENCE,
    DEFAULT_CORR_TYPE,
)


@module.ui
def perturbation_sidebar_ui() -> ui.Tag:
    # Inputs are declared statically so they keep stable DOM identity across
    # dataset-toggle re-renders. The empty-state banner is the only reactive
    # piece — see perturbation/server/sidebar.py for why this matters.
    return sidebar_shell(
        "perturbation-sidebar",
        header=sidebar_heading("Perturbation"),
        body=ui.div(
            ui.output_ui("empty_state_message"),
            sidebar_label("Column"),
            ui.input_radio_buttons(
                "col_preference",
                label=None,
                choices={"effect": "Effect", "pvalue": "P-value"},
                selected=DEFAULT_COL_PREFERENCE,
                inline=True,
            ),
            sidebar_label("Correlation"),
            ui.input_radio_buttons(
                "corr_type",
                label=None,
                choices={"pearson": "Pearson", "spearman": "Spearman"},
                selected=DEFAULT_CORR_TYPE,
                inline=True,
            ),
        ),
    )


@module.ui
def perturbation_workspace_ui() -> ui.Tag:
    return workspace_shell(
        "perturbation-workspace",
        header=workspace_heading("Perturbation Analysis"),
        body=ui.div(
            ui.output_ui("distributions_plot"),
            ui.hr(),
            ui.output_ui("regulator_selector"),
            ui.output_ui("regulator_plots"),
        ),
    )


__all__ = ["perturbation_sidebar_ui", "perturbation_workspace_ui"]
