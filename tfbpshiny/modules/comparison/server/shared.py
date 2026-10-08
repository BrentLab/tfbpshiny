"""
Helpers shared by the Comparison tabs.

``register_shared`` resolves the binding datasets each tab works over and builds the
DTO frames both metric branches use. The tab modules receive the result as a
:class:`Shared`; the sidebar outputs live in ``sidebar.py``.

"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd
from shiny import ui

from tfbpshiny.components import empty_state
from tfbpshiny.modules.comparison.queries import (
    DTO_PVALUE_THRESHOLD,
    METHOD_LEVELS,
    METRIC_DTO,
    PROMOTER_SET_LEVELS,
    fetch_dto_results,
    fetch_dto_results_method_intersected,
)
from tfbpshiny.modules.comparison.server.context import (
    ComparisonContext,
    read_dto_ranking,
    read_metric,
    read_preset_name,
)
from tfbpshiny.utils.inputs import read_input
from tfbpshiny.utils.perf import perf
from tfbpshiny.utils.vdb_init import get_responsiveness_label


@dataclass(frozen=True)
class Shared:
    """The callables the tab modules depend on."""

    inner_tab: Callable[[], str]
    cd_binding_dbs: Callable[[], list[str]]
    cp_binding_dbs: Callable[[], list[str]]
    cm_selected_binding_db: Callable[[], str]
    cm_binding_dbs: Callable[[], list[str]]
    dto_unavailable: Callable[[], ui.Tag | None]
    metric_note: Callable[[str], str]
    dto_frame: Callable[[list[tuple[str, str]]], pd.DataFrame]
    cm_dto_frame: Callable[[list[tuple[str, str]]], pd.DataFrame]


def register_shared(input: Any, session: Any, ctx: ComparisonContext) -> Shared:
    """
    Create the shared helpers and the sidebar outputs.

    :param input: Shiny input object of the comparison module.
    :param session: Module session.
    :param ctx: Per-session context.
    :returns: The shared callables.

    """
    conn = ctx.conn
    binding_index = ctx.binding_index

    # ---------------------------------------------------------------------------
    # Inner tab helper
    # ---------------------------------------------------------------------------

    def _inner_tab() -> str:
        return read_input(input, "comparison_inner_tabs", "Compare Datasets", str)

    # ---------------------------------------------------------------------------
    # Binding db resolution helpers
    # ---------------------------------------------------------------------------

    def _cd_binding_dbs() -> list[str]:
        """
        Resolve binding db_names for the Compare Datasets tab.

        Maps primary binding datasets to variant db_names based on the selected Binding
        Method and Promoter Set controls.

        """
        method = read_input(input, "cd_binding_method", "Promoter Enrichment", str)
        ps_id = read_input(input, "cd_promoter_set", "kang", str)

        method_id = "peak_calling" if method == "Peaks" else "promoter_enrichment"
        result: list[str] = []
        for b_db in ctx.active_binding_datasets():
            # resolve_or_self, not resolve: Harbison's regions are microarray probes,
            # so no promoter set names it and a strict resolve would drop it from
            # every column of this tab.
            db = binding_index.resolve_or_self(b_db, ps_id, method_id)
            if db:
                result.append(db)
        return result

    def _cp_binding_dbs() -> list[str]:
        """
        All binding db_names (primary + variants) for the Compare Promoter tab.

        Builds the set of all active primary datasets plus all their promoter-set
        variant db_names, filtered to only the promoter sets the user has checked in the
        sidebar.

        """
        included_ps = list(
            read_input(
                input, "cp_included_promoter_sets", list(PROMOTER_SET_LEVELS), list
            )
        )

        result: list[str] = []
        for b_db in ctx.active_binding_datasets():
            for ps_id in PROMOTER_SET_LEVELS:
                if ps_id not in included_ps:
                    continue
                db = binding_index.resolve(b_db, ps_id, "promoter_enrichment")
                if db:
                    result.append(db)
        return result

    def _cm_selected_binding_db() -> str:
        """
        The primary binding dataset driving the Compare Methods tab.

        Falls back to the first active dataset that has both a promoter-enrichment and a
        peak-calling variant.

        """
        cm_binding_db = read_input(input, "cm_binding_dataset", "", str)
        active = ctx.active_binding_datasets()
        if cm_binding_db in active:
            return cm_binding_db
        eligible = [db for db in active if binding_index.supports_method_comparison(db)]
        return eligible[0] if eligible else ""

    def _cm_binding_dbs() -> list[str]:
        """
        Binding db_names for the Compare Methods tab.

        For the selected dataset, returns both the promoter-enrichment and the peak-
        calling variant of every checked promoter set. The original authors' peaks are
        excluded -- they have no fixed promoter window, so they are not comparable
        across promoter set columns.

        """
        cm_binding_db = _cm_selected_binding_db()
        if not cm_binding_db:
            return []

        cm_ps = list(
            read_input(input, "cm_promoter_set", list(PROMOTER_SET_LEVELS), list)
        )

        result: list[str] = []
        for ps_id in PROMOTER_SET_LEVELS:
            if ps_id not in cm_ps:
                continue
            for method_id in METHOD_LEVELS:
                db = binding_index.resolve(cm_binding_db, ps_id, method_id)
                if db:
                    result.append(db)
        return result

    # ---------------------------------------------------------------------------
    # DTO branch shared by the tabs
    # ---------------------------------------------------------------------------

    def _dto_unavailable() -> ui.Tag | None:
        """
        Empty state shown when the DTO metric is selected but not materialized.

        Returns ``None`` when there is nothing to report, so callers can use it as a
        guard: ``if (msg := _dto_unavailable()) is not None: return msg``.

        """
        if read_metric(input) != METRIC_DTO or ctx.dto_available:
            return None
        return empty_state(
            ui.p(
                ui.strong("DTO results are not in this database."),
                " The `dto` and `sample_regulator` tables are missing, which means"
                " the database predates DTO materialization.",
            ),
            ui.p(
                "Rebuild it with ",
                ui.tags.code("tfbpshiny materialize"),
                " to enable this metric, or switch back to Top-N.",
            ),
        )

    def _metric_note(p_db: str) -> str:
        """Tooltip describing how the displayed value was computed, per metric."""
        if read_metric(input) == METRIC_DTO:
            return (
                f"Percent of shared regulators with DTO empirical p <"
                f" {DTO_PVALUE_THRESHOLD} ({read_dto_ranking(input)} ranking)."
                " Denominator is every regulator present in both datasets."
            )
        thresh = get_responsiveness_label(read_preset_name(input), p_db)
        return f"Responsive threshold: {thresh}"

    def _attach_labels(raw: pd.DataFrame) -> pd.DataFrame:
        """The label columns the tab renderers key on, derived from the registry."""
        raw["binding_label"] = (
            raw["binding_db"].map(binding_index.label).fillna(raw["binding_db"])
        )
        raw["binding_base_label"] = (
            raw["binding_db"].map(binding_index.base_label).fillna(raw["binding_db"])
        )
        raw["promoter_set_id"] = (
            raw["binding_db"].map(binding_index.promoter_set_id).fillna("")
        )
        raw["binding_method_id"] = (
            raw["binding_db"].map(binding_index.method_id).fillna("")
        )
        raw["perturbation_source"] = (
            raw["perturbation_db"].map(ctx.base_label).fillna(raw["perturbation_db"])
        )
        raw["val"] = raw["percent_significant"].round(4)
        raw["n_regulators"] = raw["n_intersect"]
        return raw

    def _dto_frame(pairs: list[tuple[str, str]]) -> pd.DataFrame:
        """
        Fetch DTO percentages for `pairs` and attach the label columns the tabs need.

        Produces the same key columns the Top-N calcs emit -- ``binding_base_label``,
        ``promoter_set_id``, ``binding_method_id`` -- so the table renderers work
        unchanged. ``n_intersect`` becomes ``n_regulators`` (the metric's denominator)
        and ``n_covered`` is carried through so the tested/shared gap stays visible.

        """
        filters = ctx.dataset_filters()
        ranking = read_dto_ranking(input)
        with perf(session.id, "comparison.workspace", "_dto_fetch", kind="data"):
            try:
                raw = fetch_dto_results(conn, pairs, filters, ranking)
            except Exception:
                ctx.logger.exception("dto fetch failed")
                return pd.DataFrame()
        if raw.empty:
            return raw
        return _attach_labels(raw)

    def _cm_dto_frame(pairs: list[tuple[str, str]]) -> pd.DataFrame:
        """
        DTO branch of ``_cm_data`` (Compare Analysis Methods tab).

        Like :func:`_dto_frame`, but this tab always varies method, and DTO
        significance can't be recomputed for a regulator missing from one method's
        binding data -- so instead of each ``(binding_db, perturbation_db)`` pair
        drawing its own pairwise regulator intersection, every sibling
        (promoter_enrichment, peak_calling) pair at the same promoter set shares one
        3-way-intersected universe (see
        ``fetch_dto_results_method_intersected``), so the two bars stay directly
        comparable.

        """
        filters = ctx.dataset_filters()
        ranking = read_dto_ranking(input)
        cells: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for b_db, p_db in pairs:
            primary = binding_index.primary.get(b_db, b_db)
            ps_id = binding_index.promoter_set_id.get(b_db, "")
            key = (primary, ps_id, p_db)
            if key in seen:
                continue
            seen.add(key)
            pe_db = binding_index.resolve(primary, ps_id, "promoter_enrichment")
            pc_db = binding_index.resolve(primary, ps_id, "peak_calling")
            if pe_db and pc_db:
                cells.append((pe_db, pc_db, p_db))
        with perf(session.id, "comparison.workspace", "_cm_dto_fetch", kind="data"):
            try:
                raw = fetch_dto_results_method_intersected(
                    conn, cells, filters, ranking
                )
            except Exception:
                ctx.logger.exception("cm dto fetch failed")
                return pd.DataFrame()
        if raw.empty:
            return raw
        return _attach_labels(raw)

    return Shared(
        inner_tab=_inner_tab,
        cd_binding_dbs=_cd_binding_dbs,
        cp_binding_dbs=_cp_binding_dbs,
        cm_selected_binding_db=_cm_selected_binding_db,
        cm_binding_dbs=_cm_binding_dbs,
        dto_unavailable=_dto_unavailable,
        metric_note=_metric_note,
        dto_frame=_dto_frame,
        cm_dto_frame=_cm_dto_frame,
    )


__all__ = ["Shared", "register_shared"]
