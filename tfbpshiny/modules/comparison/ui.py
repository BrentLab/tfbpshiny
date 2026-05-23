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
            ui.output_ui("execute_pending_style"),
            ui.input_task_button(
                "execute_analysis",
                "Execute Analysis",
                label_busy="Running...",
                type="danger",
            ),
            sidebar_label("Binding Datasets"),
            ui.output_ui("binding_selection"),
            sidebar_label("Perturbation Datasets"),
            ui.output_ui("perturbation_selection"),
            sidebar_label("Promoter Sets"),
            ui.input_checkbox_group(
                "included_promoter_sets",
                label=None,
                choices={"Kang": "Kang", "Mindel": "Mindel"},
                selected=["Kang", "Mindel"],
            ),
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
            id="comparison_sidebar",
            width=320,
            open="open",
        ),
        ui.h1("Comparison"),
        ui.div(
            {"class": "sidebar-text"},
            ui.p(
                "Select datasets, promoter sets, and thresholds in the sidebar, "
                "then click Execute Analysis to compute."
            ),
            ui.p(
                "Distributions shows the fraction of top-N binding targets that "
                "are transcriptionally responsive, grouped by promoter set. "
                "Each box plot is split by Kang and Mindel promoter annotations."
            ),
            ui.p(
                "Tables shows a summary of median percent-responsive for Kang vs "
                "Mindel promoter annotations, one table per binding dataset with a "
                "Mindel variant."
            ),
        ),
        ui.output_ui("analysis_status"),
        ui.navset_tab(
            ui.nav_panel(
                "Distributions",
                ui.output_ui("facet_by_selector"),
                ui.output_ui("topn_plot"),
            ),
            ui.nav_panel("Tables", ui.output_ui("promoter_comparison")),
            ui.nav_panel(
                "Method Comparison",
                ui.output_ui("method_facet_by_selector"),
                ui.output_ui("method_comparison"),
            ),
            id="comparison_view_tabs",
        ),
    )


__all__ = ["comparison_ui"]
