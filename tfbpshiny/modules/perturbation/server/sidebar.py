"""Sidebar server for the Perturbation analysis page."""

from __future__ import annotations

from collections.abc import Callable
from logging import Logger
from typing import Any

from shiny import module, reactive, render, ui

from tfbpshiny.components import empty_state
from tfbpshiny.modules.perturbation.queries import (
    DEFAULT_COL_PREFERENCE,
    DEFAULT_CORR_TYPE,
)


@module.server
def perturbation_sidebar_server(
    input: Any,
    output: Any,
    session: Any,
    active_perturbation_datasets: reactive.Calc_[list[str]],
    dataset_filters: reactive.Value[dict[str, Any]],
    vdb: Any,
    logger: Logger,
) -> tuple[
    Callable[[], str],  # corr_type: "pearson" | "spearman"
    Callable[[], str],  # col_preference: "effect" | "pvalue"
]:
    """
    Wire up reactive accessors for the statically-declared perturbation sidebar controls
    and render the empty-state banner.

    The actual input widgets (``corr_type``, ``col_preference``) are declared
    in ``perturbation_sidebar_ui`` so their DOM identity persists across
    dataset-toggle re-renders. This server only exposes reactive accessors for
    those inputs and conditionally renders the dataset-required banner.

    :return: Tuple of (corr_type, col_preference).

    """

    @reactive.calc
    def corr_type() -> str:
        """
        Currently selected correlation method.

        :trigger input.corr_type: fires when the user changes the Correlation
            radio button in the sidebar.
        :returns: ``"pearson"`` or ``"spearman"``; defaults to ``"pearson"``
            before the input is rendered.

        """
        try:
            return str(input.corr_type())
        except Exception:
            return DEFAULT_CORR_TYPE

    @reactive.calc
    def col_preference() -> str:
        """
        Currently selected measurement column preference.

        :trigger input.col_preference: fires when the user changes the Column
            radio button in the sidebar.
        :returns: ``"effect"`` or ``"pvalue"``; defaults to ``"effect"``
            before the input is rendered.

        """
        try:
            return str(input.col_preference())
        except Exception:
            return DEFAULT_COL_PREFERENCE

    @render.ui
    def empty_state_message() -> ui.Tag | None:
        """
        Empty-state banner shown when no perturbation datasets are selected.

        :trigger active_perturbation_datasets: re-runs on dataset selection change.
        :returns: The banner div, or ``None`` when at least one dataset is active.

        """
        if not active_perturbation_datasets():
            return empty_state(
                ui.p("Select perturbation datasets from the Select Datasets page."),
                compact=True,
            )
        return None

    return corr_type, col_preference


__all__ = ["perturbation_sidebar_server"]
