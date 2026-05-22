"""UI functions for the Comparison module."""

from __future__ import annotations

from shiny import module, ui

from tfbpshiny.components import sidebar_label
from tfbpshiny.modules.comparison.queries import (
    DEFAULT_EFFECT_THRESHOLD,
    DEFAULT_PVALUE_THRESHOLD,
    DEFAULT_TOP_N,
)


@module.ui
def comparison_ui() -> ui.Tag:
    return ui.layout_sidebar(
        ui.sidebar(
            ui.h2("Comparison"),
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
                selected="binding",
            ),
            id="comparison_sidebar",
            width=320,
            open="open",
        ),
        ui.h1("Comparison"),
        ui.div(
            {"class": "workspace-section"},
            ui.h3("Top N by Binding"),
            ui.output_ui("topn_plot"),
        ),
        ui.div(
            {"class": "workspace-section"},
            ui.h3("Promoter Set Comparison"),
            ui.output_ui("promoter_comparison"),
        ),
    )


__all__ = ["comparison_ui"]
