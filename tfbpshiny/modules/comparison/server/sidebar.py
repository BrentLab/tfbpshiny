"""Sidebar server for the Comparison module."""

from __future__ import annotations

from collections.abc import Callable
from logging import Logger
from typing import Any

from labretriever import VirtualDB
from shiny import module, reactive, render, ui

from tfbpshiny.components import empty_state
from tfbpshiny.modules.comparison.queries import (
    DEFAULT_EFFECT_THRESHOLD,
    DEFAULT_FACET_BY,
    DEFAULT_PVALUE_THRESHOLD,
    DEFAULT_TOP_N,
)


@module.server
def comparison_sidebar_server(
    input: Any,
    output: Any,
    session: Any,
    active_binding_datasets: reactive.Calc_[list[str]],
    active_perturbation_datasets: reactive.Calc_[list[str]],
    vdb: VirtualDB,
    logger: Logger,
) -> tuple[
    Callable[[], int],  # top_n
    Callable[[], float],  # effect_threshold
    Callable[[], float],  # pvalue_threshold
    Callable[[], str],  # facet_by: "binding" | "perturbation"
]:
    """
    Render comparison sidebar controls and return reactive selections.

    :returns: Tuple of (top_n, effect_threshold, pvalue_threshold, facet_by).

    """

    @reactive.calc
    def top_n() -> int:
        """
        Number of top binding targets to keep per sample.

        :trigger input.top_n: fires when the user changes the numeric input.
        :returns: Integer >= 1; defaults to ``DEFAULT_TOP_N``.

        """
        try:
            val = int(input.top_n())
            return max(1, val)
        except Exception:
            return DEFAULT_TOP_N

    @reactive.calc
    def effect_threshold() -> float:
        """
        Minimum absolute effect size for a perturbation target to be responsive.

        :trigger input.effect_threshold: fires when the slider changes.
        :returns: Float >= 0; defaults to ``DEFAULT_EFFECT_THRESHOLD``.

        """
        try:
            return float(input.effect_threshold())
        except Exception:
            return DEFAULT_EFFECT_THRESHOLD

    @reactive.calc
    def pvalue_threshold() -> float:
        """
        Maximum p-value for a perturbation target to be responsive.

        :trigger input.pvalue_threshold: fires when the slider changes.
        :returns: Float in (0, 1]; defaults to ``DEFAULT_PVALUE_THRESHOLD``.

        """
        try:
            return float(input.pvalue_threshold())
        except Exception:
            return DEFAULT_PVALUE_THRESHOLD

    @reactive.calc
    def facet_by() -> str:
        """
        Controls which dimension forms the facets vs the color grouping.

        :trigger input.facet_by: fires when the user changes the radio button.
        :returns:``"binding"`` (binding = facets, perturbation = color) or
            ``"perturbation"`` (perturbation = facets, binding = color).

        """
        try:
            return str(input.facet_by())
        except Exception:
            return DEFAULT_FACET_BY

    @render.ui
    def empty_state_message() -> ui.Tag | None:
        """
        Empty-state banner shown when either dataset axis is empty.

        :trigger active_binding_datasets: re-runs on dataset selection change.
        :trigger active_perturbation_datasets: re-runs on dataset selection change.
        :returns: The banner div, or ``None`` when both axes have selections.

        """
        if not active_binding_datasets() or not active_perturbation_datasets():
            return empty_state(
                ui.p(
                    "Select at least one binding and one perturbation dataset "
                    "from the Select Datasets page."
                ),
                compact=True,
            )
        return None

    return top_n, effect_threshold, pvalue_threshold, facet_by


__all__ = ["comparison_sidebar_server"]
