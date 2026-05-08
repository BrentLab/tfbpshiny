"""Sidebar server for the Binding analysis page."""

from __future__ import annotations

from collections.abc import Callable
from logging import Logger
from typing import Any

from labretriever import VirtualDB
from shiny import module, reactive, render, ui

from tfbpshiny.components import sidebar_label
from tfbpshiny.utils.perf import perf, reset_render_counts


@module.server
def binding_sidebar_server(
    input: Any,
    output: Any,
    session: Any,
    active_binding_datasets: reactive.Calc_[list[str]],
    dataset_filters: reactive.Value[dict[str, Any]],
    vdb: VirtualDB,
    logger: Logger,
) -> tuple[
    Callable[[], str],  # corr_type: "pearson" | "spearman"
    Callable[[], str],  # col_preference: "effect" | "pvalue"
]:
    """
    Render binding analysis sidebar controls; return reactive selections.

    :return: Tuple of (corr_type, col_preference).

    """

    session.on_flush(lambda: reset_render_counts(session.id))

    @reactive.calc
    def corr_type() -> str:
        """
        Currently selected correlation method.

        :trigger input.corr_type: fires when the user changes the Correlation
            radio button in the sidebar.
        :returns: ``"pearson"`` or ``"spearman"``; defaults to ``"pearson"``
            before the input is rendered.

        """
        with perf(session.id, "binding.sidebar", "corr_type"):
            try:
                return str(input.corr_type())
            except Exception:
                return "pearson"

    @reactive.calc
    def col_preference() -> str:
        """
        Currently selected measurement column preference.

        :trigger input.col_preference: fires when the user changes the Column
            radio button in the sidebar.
        :returns: ``"effect"`` or ``"pvalue"``; defaults to ``"effect"``
            before the input is rendered.

        """
        with perf(session.id, "binding.sidebar", "col_preference"):
            try:
                return str(input.col_preference())
            except Exception:
                return "effect"

    @render.ui
    def sidebar_controls() -> ui.Tag:
        active = active_binding_datasets()

        if not active:
            return ui.div(
                {"class": "empty-state compact"},
                ui.p("Select binding datasets from the Select Datasets page."),
            )

        # Use isolate() so the render does not take a reactive dependency on
        # col_preference/corr_type. Without this, the first DOM render sends
        # back initial input values which re-invalidates both calcs and causes
        # _all_corr_data to run twice per navigation.
        with reactive.isolate():
            current_col = col_preference()
            current_corr = corr_type()

        return ui.div(
            sidebar_label("Column"),
            ui.input_radio_buttons(
                "col_preference",
                label=None,
                choices={"effect": "Effect", "pvalue": "P-value"},
                selected=current_col,
                inline=True,
            ),
            sidebar_label("Correlation"),
            ui.input_radio_buttons(
                "corr_type",
                label=None,
                choices={"pearson": "Pearson", "spearman": "Spearman"},
                selected=current_corr,
                inline=True,
            ),
        )

    return corr_type, col_preference


__all__ = ["binding_sidebar_server"]
