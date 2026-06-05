"""UI functions for the Comparison module."""

from __future__ import annotations

from shiny import module, ui

from tfbpshiny.components import sidebar_label
from tfbpshiny.modules.comparison.queries import DEFAULT_TOP_N


@module.ui
def comparison_ui() -> ui.Tag:
    return ui.layout_sidebar(
        ui.sidebar(
            ui.h2("Comparisons"),
            ui.output_ui("execute_pending_style"),
            ui.input_task_button(
                "execute_analysis",
                "Execute Analysis",
                label_busy="Running...",
                type="danger",
            ),
            sidebar_label("Top N"),
            ui.input_numeric(
                "top_n",
                label=None,
                value=DEFAULT_TOP_N,
                min=1,
                max=500,
                step=5,
            ),
            ui.output_ui("tab_specific_controls"),
            id="comparison_sidebar",
            width=320,
            open="open",
        ),
        ui.h1("Binding/Perturbation Comparisons"),
        ui.output_ui("analysis_status"),
        ui.navset_tab(
            # ------------------------------------------------------------------
            # Tab 1: Compare Datasets
            # ------------------------------------------------------------------
            ui.nav_panel(
                "Compare Datasets",
                ui.div(
                    {"class": "sidebar-text"},
                    ui.p(
                        "Select a binding method and promoter set in the sidebar, "
                        "then choose which binding and perturbation datasets to "
                        "include. Click Execute Analysis to compute the matrix."
                    ),
                    ui.p(
                        "Each cell shows the median percent of top-N binding targets "
                        "that are transcriptionally responsive. Click a row header to "
                        "view distributions for that binding dataset across all "
                        "perturbation datasets; click a column header to view "
                        "distributions for that perturbation dataset across all "
                        "binding datasets."
                    ),
                ),
                ui.output_ui("cd_matrix_container"),
                ui.output_ui("cd_distribution_container"),
            ),
            # ------------------------------------------------------------------
            # Tab 2: Compare Promoter Definitions
            # ------------------------------------------------------------------
            ui.nav_panel(
                "Compare Promoter Definitions",
                ui.div(
                    {"class": "sidebar-text"},
                    ui.p(
                        "Select binding datasets, perturbation datasets, and "
                        "promoter sets in the sidebar, then click Execute Analysis."
                    ),
                    ui.p(
                        "Each table is faceted by perturbation source. Rows are "
                        "binding datasets; columns are promoter set definitions. "
                        "Values are median percent-responsive across regulators."
                    ),
                ),
                ui.output_ui("cp_promoter_table"),
            ),
            # ------------------------------------------------------------------
            # Tab 3: Compare Analysis Methods
            # ------------------------------------------------------------------
            ui.nav_panel(
                "Compare Analysis Methods",
                ui.div(
                    {"class": "sidebar-text"},
                    ui.p(
                        "Select a binding dataset (ChIP-exo or ChEC-seq) and "
                        "perturbation datasets in the sidebar, then click Execute "
                        "Analysis."
                    ),
                    ui.p(
                        "Each table is faceted by perturbation source. Rows are "
                        "scoring variants (re-quantified vs original peaks); values "
                        "are median percent-responsive across regulators."
                    ),
                ),
                ui.output_ui("cm_method_table"),
            ),
            id="comparison_inner_tabs",
        ),
    )


__all__ = ["comparison_ui"]
