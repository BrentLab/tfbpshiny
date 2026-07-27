"""UI functions for the Binding analysis page."""

from __future__ import annotations

from typing import Any

from shiny import module, ui

from tfbpshiny.components import sidebar_label, workspace_heading

#: Full set of "Column" choices, keyed for ``col_preference``. ``log10pval``
#: is only valid with Pearson — Spearman is rank-based, so p-value and
#: -log10(p-value) would be redundant (and the log10pval score type isn't
#: materialized for spearman at all). The workspace server swaps this for
#: :data:`COL_PREFERENCE_CHOICES_NO_LOG10` whenever Spearman is selected.
COL_PREFERENCE_CHOICES: dict[str, Any] = {
    "log10pval": ui.tooltip(
        ui.span("-log10(p-value)"),
        "Negative log10 of the p-value. " "Values below 1e-10 are capped at 10.",
    ),
    "effect": ui.tooltip(
        ui.span("Effect"),
        "Raw effect size (e.g. enrichment score).",
    ),
    "pvalue": ui.tooltip(
        ui.span("P-value"),
        "Raw p-value. Smaller is more significant.",
    ),
}

#: ``COL_PREFERENCE_CHOICES`` without ``log10pval``, used when Spearman is selected.
COL_PREFERENCE_CHOICES_NO_LOG10: dict[str, Any] = {
    k: v for k, v in COL_PREFERENCE_CHOICES.items() if k != "log10pval"
}


@module.ui
def binding_ui() -> ui.Tag:
    return ui.layout_sidebar(
        ui.sidebar(
            ui.h2("Binding"),
            sidebar_label("Column"),
            ui.input_radio_buttons(
                "col_preference",
                label=None,
                # Default corr_type is spearman, so log10pval is excluded here
                # even though corr_type's own default choice list still allows it.
                choices=COL_PREFERENCE_CHOICES_NO_LOG10,
                selected="pvalue",
                inline=True,
            ),
            sidebar_label("Correlation"),
            ui.input_radio_buttons(
                "corr_type",
                label=None,
                choices={"pearson": "Pearson", "spearman": "Spearman"},
                selected="spearman",
                inline=True,
            ),
            id="binding_sidebar",
            width=320,
            open="open",
        ),
        ui.div(
            {"class": "workspace-centered"},
            workspace_heading("Binding Correlation"),
            ui.div(
                {"class": "sidebar-text"},
                ui.p(
                    "Select binding datasets in the shared sidebar and options "
                    "here. Correlations and distributions update automatically "
                    "as selections change."
                ),
                ui.p(
                    "The Correlation Matrix below shows median correlation for "
                    "each active dataset pair."
                ),
                ui.p(
                    "The Pair Distribution section shows the per-regulator "
                    "correlation distribution for every active pair."
                ),
            ),
            ui.output_ui("analysis_status"),
            workspace_heading("Correlation Matrix"),
            ui.output_ui("corr_matrix_container"),
            workspace_heading("Pair Distribution"),
            ui.output_ui("regulator_selector_box"),
            ui.output_ui("pair_box_container"),
        ),
    )


__all__ = [
    "binding_ui",
    "COL_PREFERENCE_CHOICES",
    "COL_PREFERENCE_CHOICES_NO_LOG10",
]
