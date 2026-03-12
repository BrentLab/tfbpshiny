"""Sidebar server for the Perturbation analysis page."""

from __future__ import annotations

from collections.abc import Callable
from logging import Logger
from typing import Any

from shiny import module, reactive, render, ui


@module.server
def perturbation_sidebar_server(
    input: Any,
    output: Any,
    session: Any,
    active_perturbation_datasets: reactive.Value[list[str]],
    dataset_filters: reactive.Value[dict[str, Any]],
    vdb: Any,
    logger: Logger,
) -> tuple[
    Callable[[], str],  # corr_type: "pearson" | "spearman"
    Callable[[], str],  # col_preference: "effect" | "pvalue"
]:
    """
    Render perturbation analysis sidebar controls; return reactive selections.

    :return: Tuple of (corr_type, col_preference).

    """

    @reactive.calc
    def corr_type() -> str:
        try:
            return str(input.corr_type())
        except Exception:
            return "pearson"

    @reactive.calc
    def col_preference() -> str:
        try:
            return str(input.col_preference())
        except Exception:
            return "effect"

    @render.ui
    def sidebar_controls() -> ui.Tag:
        active = active_perturbation_datasets()

        if not active:
            return ui.div(
                {"class": "empty-state compact"},
                ui.p("Select perturbation datasets from the Select Datasets page."),
            )

        return ui.div(
            ui.div(
                {"class": "sidebar-section"},
                ui.div({"class": "sidebar-section-title"}, "Column"),
                ui.input_radio_buttons(
                    "col_preference",
                    label=None,
                    choices={"effect": "Effect", "pvalue": "P-value"},
                    selected=col_preference(),
                    inline=True,
                ),
            ),
            ui.div(
                {"class": "sidebar-section"},
                ui.div({"class": "sidebar-section-title"}, "Correlation"),
                ui.input_radio_buttons(
                    "corr_type",
                    label=None,
                    choices={"pearson": "Pearson", "spearman": "Spearman"},
                    selected=corr_type(),
                    inline=True,
                ),
            ),
        )

    return corr_type, col_preference


__all__ = ["perturbation_sidebar_server"]
