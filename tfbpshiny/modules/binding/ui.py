"""UI functions for the Binding analysis page."""

from __future__ import annotations

from shiny import module, ui

from tfbpshiny.components import sidebar_label


@module.ui
def binding_ui() -> ui.Tag:
    return ui.layout_sidebar(
        ui.sidebar(
            ui.h2("Binding"),
            ui.output_ui("execute_pending_style"),
            ui.input_task_button(
                "execute_analysis",
                "Execute Analysis",
                label_busy="Running...",
                type="danger",
            ),
            sidebar_label("Datasets"),
            ui.output_ui("dataset_selection"),
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
            id="binding_sidebar",
            width=320,
            open="open",
        ),
        ui.h1("Binding Correlation"),
        ui.div(
            {"class": "sidebar-text"},
            ui.p(
                "Select binding datasets and options in the sidebar, then click "
                "Execute Analysis to compute pairwise correlations across shared "
                "regulators."
            ),
            ui.p(
                "The Distributions tab shows one box plot per dataset pair. "
                "Each point represents the correlation for a single regulator. "
                "Click a point to select that regulator and highlight it across "
                "all plots."
            ),
            ui.p(
                "The Scatter tab shows per-target binding scores for the selected "
                "regulator in each pair. Use the dropdown to change the active "
                "regulator."
            ),
        ),
        ui.output_ui("analysis_status"),
        ui.navset_tab(
            ui.nav_panel(
                "Distributions",
                ui.output_ui("box_plot_container"),
            ),
            ui.nav_panel(
                "Scatter",
                ui.output_ui("scatter_status"),
                ui.output_ui("regulator_selector"),
                ui.output_ui("scatter_container"),
            ),
            id="binding_view_tabs",
        ),
    )


__all__ = ["binding_ui"]
