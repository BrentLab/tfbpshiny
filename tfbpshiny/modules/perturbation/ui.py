"""UI functions for the Perturbation analysis page."""

from __future__ import annotations

from shiny import module, ui

from tfbpshiny.components import sidebar_label


@module.ui
def perturbation_ui() -> ui.Tag:
    return ui.layout_sidebar(
        ui.sidebar(
            ui.h2("Perturbation"),
            sidebar_label("Column"),
            ui.input_radio_buttons(
                "col_preference",
                label=None,
                choices={"effect": "Effect", "pvalue": "P-value"},
                selected="effect",
                inline=True,
            ),
            sidebar_label("Correlation"),
            ui.input_radio_buttons(
                "corr_type",
                label=None,
                choices={"pearson": "Pearson", "spearman": "Spearman"},
                selected="pearson",
                inline=True,
            ),
            id="perturbation_sidebar",
            width=320,
            open="open",
        ),
        ui.h1("Perturbation Analysis"),
        ui.output_ui("distributions_plot"),
        ui.hr(),
        ui.output_ui("regulator_selector"),
        ui.output_ui("scatter_container"),
    )


__all__ = ["perturbation_ui"]
