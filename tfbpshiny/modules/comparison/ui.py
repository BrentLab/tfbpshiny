"""UI functions for the Comparison module."""

from __future__ import annotations

from shiny import module, ui

from tfbpshiny.components import (
    sidebar_heading,
    sidebar_label,
    sidebar_shell,
    workspace_heading,
    workspace_shell,
)
from tfbpshiny.modules.comparison.queries import (
    DEFAULT_EFFECT_THRESHOLD,
    DEFAULT_FACET_BY,
    DEFAULT_PVALUE_THRESHOLD,
    DEFAULT_TOP_N,
)


@module.ui
def comparison_sidebar_ui() -> ui.Tag:
    # Inputs are declared statically so they keep stable DOM identity across
    # dataset-toggle re-renders. The empty-state banner is the only reactive
    # piece — see comparison/server/sidebar.py for why this matters.
    return sidebar_shell(
        "comparison-sidebar",
        header=sidebar_heading("Comparison"),
        body=ui.div(
            ui.output_ui("empty_state_message"),
            ui.input_numeric(
                "top_n",
                "Top N",
                value=DEFAULT_TOP_N,
                min=1,
                max=500,
                step=5,
            ),
            sidebar_label("Responsive threshold"),
            ui.input_slider(
                "effect_threshold",
                "Min |effect|",
                min=0.0,
                max=5.0,
                value=DEFAULT_EFFECT_THRESHOLD,
                step=0.1,
            ),
            ui.input_slider(
                "pvalue_threshold",
                "Max p-value",
                min=0.001,
                max=1.0,
                value=DEFAULT_PVALUE_THRESHOLD,
                step=0.001,
            ),
            sidebar_label("Facet by"),
            ui.input_radio_buttons(
                "facet_by",
                label=None,
                choices={
                    "binding": "Binding source",
                    "perturbation": "Perturbation source",
                },
                selected=DEFAULT_FACET_BY,
            ),
        ),
    )


@module.ui
def comparison_workspace_ui() -> ui.Tag:
    return workspace_shell(
        "comparison-workspace",
        header=workspace_heading("Comparison"),
        body=ui.div(
            ui.div(
                {"class": "workspace-section"},
                ui.h3("Top N by Binding"),
                ui.output_ui("topn_plot"),
            ),
        ),
    )


__all__ = ["comparison_sidebar_ui", "comparison_workspace_ui"]
