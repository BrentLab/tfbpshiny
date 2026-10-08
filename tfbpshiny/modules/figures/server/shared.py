"""
Reactives and sidebar outputs shared by several figures.

``register_shared`` creates the TF-set calcs, the rank-response data calc, the input
readers and the two sidebar outputs, and returns them in a :class:`Shared` so the
per-figure modules can depend on them without re-creating them.

"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd
from shiny import reactive, render, ui

from tfbpshiny.components import sidebar_text
from tfbpshiny.datasets import DEFAULT_PRESET, DEFAULT_TOP_N
from tfbpshiny.modules.figures.plots import DTO_VENN_LAYOUT_DEFAULT
from tfbpshiny.modules.figures.queries import (
    BINDING_ORDER,
    DTO_BINDING_ORDER,
    METHOD_COMPARISON_BINDING,
    PR_ORDER,
    fetch_rank_response,
    regulator_intersection,
    sort_regulators_by_symbol,
)
from tfbpshiny.modules.figures.server.context import FiguresContext
from tfbpshiny.utils.inputs import read_input
from tfbpshiny.utils.perf import perf

#: Default featured TF (GZF3), used when present in the intersection. Picked as a
#: representative example rather than for any statistical reason; falls back to
#: the first TF alphabetically if a future intersection ever excludes it.
DEFAULT_FEATURED_TF = "YJL110C"


@dataclass(frozen=True)
class Shared:
    """
    The reactives and readers other figures call.

    Every field is a callable: the ``reactive.calc`` objects are invoked like functions
    inside a reactive context, and the readers return the current input value or its
    default.

    """

    tf_sets: Callable[[], dict[str, list[str]]]
    featured_tfs: Callable[[], list[str]]
    fig7_tf_sets: Callable[[], dict[str, list[str]]]
    fig9_tf_sets: Callable[[], dict[str, list[str]]]
    rank_response: Callable[[], dict[str, pd.DataFrame]]
    read_scoring: Callable[[], str]
    read_top_n: Callable[[], int]
    read_dto_venn_layout: Callable[[], str]
    dto_missing: Callable[[], ui.Tag]


def register_shared(input: Any, session: Any, ctx: FiguresContext) -> Shared:
    """
    Create the shared reactives and the sidebar outputs.

    :param input: Shiny input object of the figures module.
    :param session: Module session.
    :param ctx: Per-session context.
    :returns: The shared callables.

    """
    conn = ctx.conn

    @reactive.calc
    def _tf_sets() -> dict[str, list[str]]:
        """
        Regulators in (all four binding datasets) ∩ each perturbation dataset.

        :trigger: none -- depends only on the database, so computed once per session.

        """
        return {
            p: regulator_intersection(conn, list(BINDING_ORDER) + [p]) for p in PR_ORDER
        }

    @reactive.calc
    def _featured_tfs() -> list[str]:
        """Regulators present in all four binding datasets and all three PR datasets."""
        return regulator_intersection(conn, list(BINDING_ORDER) + list(PR_ORDER))

    @reactive.calc
    def _fig7_tf_sets() -> dict[str, list[str]]:
        """
        Regulators in (Calling Cards, Rossi, ChEC-seq) ∩ each perturbation dataset, for
        figures 7 and 9's top-N response-rate grids.

        Deliberately not ``_tf_sets()``: that one intersects over ``BINDING_ORDER``,
        which includes Harbison -- Harbison has no promoter-set variants at all, so
        including it would only shrink this population for no reason.

        :trigger: none -- depends only on the database.

        """
        return {
            p: regulator_intersection(conn, list(DTO_BINDING_ORDER) + [p])
            for p in PR_ORDER
        }

    @reactive.calc
    def _fig9_tf_sets() -> dict[str, list[str]]:
        """
        Regulators in (Rossi, ChEC-seq) ∩ each perturbation dataset, for figure 9's top
        grid -- the two binding primaries with a peak-calling arm.

        :trigger: none -- depends only on the database.

        """
        return {
            p: regulator_intersection(conn, list(METHOD_COMPARISON_BINDING) + [p])
            for p in PR_ORDER
        }

    def _read_scoring() -> str:
        """
        The selected responsiveness preset.

        Falls back to Relaxed, which every build has.

        """
        return read_input(input, "scoring", DEFAULT_PRESET, str)

    def _read_top_n() -> int:
        return read_input(input, "box_top_n", DEFAULT_TOP_N, int)

    def _read_dto_venn_layout() -> str:
        return read_input(input, "dto_venn_layout", DTO_VENN_LAYOUT_DEFAULT, str)

    @reactive.calc
    def _rank_response() -> dict[str, pd.DataFrame]:
        """
        Rank-response rows per perturbation dataset.

        :trigger: ``dataset_filters`` -- sample filters change which samples the
            median is taken over.
        :trigger: ``input.scoring`` -- selects which responsiveness definition to
            read; the table stores several per key.

        """
        filters = ctx.dataset_filters()
        sets = _tf_sets()
        preset = _read_scoring()
        with perf(session.id, "figures.workspace", "_rank_response", kind="data"):
            return {
                p: fetch_rank_response(
                    conn,
                    list(BINDING_ORDER),
                    p,
                    sets.get(p, []),
                    filters,
                    preset,
                )
                for p in PR_ORDER
            }

    def _dto_missing() -> ui.Tag:
        return ctx.needs_rebuild("DTO results")

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------

    @render.ui
    def tf_selector() -> ui.Tag:
        """
        Selector for the TF featured in figure 1.

        :trigger: ``_featured_tfs``.

        """
        tfs = sort_regulators_by_symbol(_featured_tfs(), ctx.reg_symbols)
        if not tfs:
            return ui.span()
        default = DEFAULT_FEATURED_TF if DEFAULT_FEATURED_TF in tfs else tfs[0]
        return ui.div(
            ui.tags.label("Featured TF", class_="form-label mt-3 mb-1"),
            ui.input_select(
                "featured_tf",
                label=None,
                choices={t: ctx.reg_labels.get(t, t) for t in tfs},
                selected=default,
            ),
        )

    @render.ui
    def figure_status() -> ui.Tag:
        """
        Summary of the TF sets the figures are drawn over.

        :trigger: ``_tf_sets``.

        """
        sets = _tf_sets()
        parts = ", ".join(
            f"{ctx.labels.get(p, p)}: {len(sets.get(p, []))}" for p in PR_ORDER
        )
        note = (
            ""
            if ctx.schema_current
            else " DTO tables are absent from this database, so figures 4 and 5"
            " cannot be drawn -- rebuild with `tfbpshiny materialize`."
        )
        return sidebar_text(
            ui.p(
                ui.strong("TFs per figure: "),
                f"all four binding datasets intersected with each perturbation"
                f" dataset -- {parts}."
                f" Figure 1's featured TF is drawn from the "
                f"{len(_featured_tfs())} TFs present in all seven datasets.{note}",
            ),
        )

    return Shared(
        tf_sets=_tf_sets,
        featured_tfs=_featured_tfs,
        fig7_tf_sets=_fig7_tf_sets,
        fig9_tf_sets=_fig9_tf_sets,
        rank_response=_rank_response,
        read_scoring=_read_scoring,
        read_top_n=_read_top_n,
        read_dto_venn_layout=_read_dto_venn_layout,
        dto_missing=_dto_missing,
    )


__all__ = ["DEFAULT_FEATURED_TF", "Shared", "register_shared"]
