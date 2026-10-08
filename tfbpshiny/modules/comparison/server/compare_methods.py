"""Tab 3, Compare Analysis Methods: promoter enrichment against peak calling."""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd
from shiny import reactive, render, ui

from tfbpshiny.components import empty_state
from tfbpshiny.materialize.comparison.method_promoter_model import (
    pair_methods_on_regulators,
)
from tfbpshiny.modules.comparison.queries import (
    METHOD_LEVELS,
    METRIC_DTO,
    PROMOTER_SET_LEVELS,
    fetch_topn_results,
)
from tfbpshiny.modules.comparison.server.context import (
    ComparisonContext,
    cell_style,
    inputs_ready,
    read_common_regulators_only,
    read_full_overlap,
    read_metric,
    read_preset,
    read_top_n,
)
from tfbpshiny.modules.comparison.server.shared import Shared
from tfbpshiny.utils.perf import perf


def register_compare_methods(
    input: Any, session: Any, ctx: ComparisonContext, shared: Shared
) -> None:
    """
    Register the Compare Analysis Methods tab's reactives and outputs.

    :param input: Shiny input object of the comparison module.
    :param session: Module session.
    :param ctx: Per-session context.
    :param shared: Shared helpers.

    """
    conn = ctx.conn
    binding_index = ctx.binding_index

    @reactive.calc
    def _cm_data() -> pd.DataFrame:
        """
        TopN data for the Compare Analysis Methods tab.

        :trigger: ``input.cm_binding_dataset`` / ``input.cm_promoter_set`` /
            ``input.cm_common_regulators_only`` — tab controls.
        :trigger: ``input.top_n`` / ``input.responsiveness_preset`` /
            ``input.require_intersecting_floor`` — shared sidebar controls.
        :trigger: ``active_binding_datasets`` / ``active_perturbation_datasets`` /
            ``dataset_filters`` — committed dataset selection.

        """
        if not inputs_ready(
            input, "cm_binding_dataset", "cm_promoter_set", "cm_common_regulators_only"
        ):
            return pd.DataFrame()
        b_dbs = shared.cm_binding_dbs()
        p_dbs = ctx.active_perturbation_datasets()
        if not b_dbs or not p_dbs:
            return pd.DataFrame()
        pairs = [(b, p) for b in b_dbs for p in p_dbs]
        if read_metric(input) == METRIC_DTO:
            raw = shared.cm_dto_frame(pairs)
            if raw.empty:
                return raw
            return raw[
                [
                    "perturbation_db",
                    "promoter_set_id",
                    "binding_method_id",
                    "val",
                    "n_regulators",
                ]
            ]
        filters = ctx.dataset_filters()
        n = read_top_n(input)
        preset = read_preset(input)
        floor = read_full_overlap(input)
        common_only = read_common_regulators_only(input)
        ctx.logger.debug("cm_data: %d pairs (%s × %s)", len(pairs), b_dbs, p_dbs)
        with perf(session.id, "comparison.workspace", "_cm_data", kind="data"):
            try:
                raw = fetch_topn_results(
                    conn, pairs, filters, n, preset, require_full_overlap=floor
                )
            except Exception:
                ctx.logger.exception("cm_data fetch failed")
                return pd.DataFrame()
        if raw.empty:
            return pd.DataFrame()
        raw["promoter_set_id"] = (
            raw["binding_db"].map(binding_index.promoter_set_id).fillna("")
        )
        raw["binding_method_id"] = (
            raw["binding_db"].map(binding_index.method_id).fillna("")
        )
        # When common_only, restrict per_reg (per perturbation_db) to regulators
        # present in every promoter-set x method cell, so N is identical across
        # the whole table.
        common_filter = (
            """
            JOIN common_regs cr
                ON  per_reg.perturbation_db     = cr.perturbation_db
                AND per_reg.regulator_locus_tag = cr.regulator_locus_tag
            """
            if common_only
            else ""
        )
        per_reg = duckdb.execute(
            """
            SELECT
                perturbation_db,
                promoter_set_id,
                binding_method_id,
                regulator_locus_tag,
                median(responsive_ratio) * 100 AS med_pct
            FROM raw
            GROUP BY perturbation_db, promoter_set_id, binding_method_id,
                regulator_locus_tag
            """
        ).df()
        # Compare the two methods over the same regulators: keep a regulator within a
        # (perturbation_db, promoter_set_id) cell only where promoter enrichment AND
        # peak calling both have a row. A regulator with no usable peak-calling list is
        # dropped, not scored as zero. Grouped so promoter sets do not cross-contaminate
        # each other's regulator universe.
        per_reg = pair_methods_on_regulators(
            per_reg,
            group_cols=["perturbation_db", "promoter_set_id"],
            method_col="binding_method_id",
        )
        if per_reg.empty:
            return pd.DataFrame()

        return duckdb.execute(
            f"""
            WITH reg_cell_counts AS (
                SELECT
                    perturbation_db,
                    regulator_locus_tag,
                    COUNT(*) AS n_covered
                FROM per_reg
                GROUP BY perturbation_db, regulator_locus_tag
            ),
            cell_totals AS (
                SELECT
                    perturbation_db,
                    COUNT(DISTINCT (promoter_set_id, binding_method_id)) AS n_total
                FROM per_reg
                GROUP BY perturbation_db
            ),
            common_regs AS (
                SELECT rcc.perturbation_db, rcc.regulator_locus_tag
                FROM reg_cell_counts rcc
                JOIN cell_totals ct ON rcc.perturbation_db = ct.perturbation_db
                WHERE rcc.n_covered = ct.n_total
            )
            SELECT
                per_reg.perturbation_db,
                per_reg.promoter_set_id,
                per_reg.binding_method_id,
                round(median(per_reg.med_pct), 4) AS val,
                COUNT(DISTINCT per_reg.regulator_locus_tag) AS n_regulators
            FROM per_reg
            {common_filter}
            GROUP BY per_reg.perturbation_db, per_reg.promoter_set_id,
                per_reg.binding_method_id
        """
        ).df()

    @render.ui
    def cm_method_table() -> ui.Tag:
        """
        Per-perturbation table comparing promoter enrichment against peak calling.

        One card per perturbation dataset. Columns are the checked promoter
        definitions; rows are the two binding methods, with a shared regulator
        count footer. The original authors' peaks are excluded -- they have no
        fixed promoter window, so they do not belong to any column.

        :trigger: ``_cm_data`` — re-renders when data changes.

        """
        if (msg := shared.dto_unavailable()) is not None:
            return msg
        with perf(session.id, "comparison.workspace", "cm_method_table"):
            agg = _cm_data()
            p_dbs = ctx.active_perturbation_datasets()
            if not p_dbs:
                return empty_state(
                    ui.p("No perturbation datasets selected."),
                )
            if agg.empty:
                return empty_state(
                    ui.p("No data for the selected combination."),
                )

            binding_db = shared.cm_selected_binding_db()
            binding_label = binding_index.base_label.get(binding_db, binding_db)
            peak_note = ctx.peak_notes.get(
                binding_db,
                "Peaks called over the same promoter definition used by the"
                " promoter-enrichment row.",
            )
            _th_style = "padding: 6px 10px; text-align: right;"
            _row_label_style = (
                "padding: 6px 10px; text-align: left; white-space: nowrap;"
            )

            ps_present = [
                ps for ps in PROMOTER_SET_LEVELS if ps in set(agg["promoter_set_id"])
            ]
            methods_present = [
                m for m in METHOD_LEVELS if m in set(agg["binding_method_id"])
            ]
            if not ps_present or not methods_present:
                return ui.span()

            lookup: dict[tuple[str, str, str], float] = {}
            n_reg_lookup: dict[tuple[str, str, str], int] = {}
            for row in agg.itertuples(index=False):
                key = (
                    row.perturbation_db,
                    row.promoter_set_id,
                    row.binding_method_id,
                )
                lookup[key] = row.val
                n_reg_lookup[key] = row.n_regulators

            cards: list[ui.Tag] = []
            for p_db in p_dbs:
                p_label = ctx.base_label.get(p_db, p_db)
                sub_agg = agg[agg["perturbation_db"] == p_db]
                if sub_agg.empty:
                    continue

                header_cells = [
                    ui.tags.th(
                        "Method",
                        style="padding: 6px 10px; text-align: left;",
                    )
                ]
                for ps in ps_present:
                    header_cells.append(
                        ui.tags.th(
                            ui.tooltip(
                                ui.span(ctx.promoter_set_labels.get(ps, ps)),
                                ctx.promoter_tooltips.get(ps, ""),
                            ),
                            style=f"{_th_style} font-weight: 600;",
                        )
                    )

                data_rows_cm: list[ui.Tag] = []
                for method_id in methods_present:
                    method_label = ctx.method_labels.get(method_id, method_id)
                    color = ctx.method_colors.get(method_id, "#888888")
                    if method_id == "peak_calling":
                        label_tag: Any = ui.tooltip(
                            ui.span(method_label), peak_note, placement="right"
                        )
                    else:
                        label_tag = ui.span(method_label)
                    row_cells = [
                        ui.tags.td(
                            label_tag,
                            style=(
                                f"{_row_label_style} color: {color};"
                                " font-weight: 600;"
                            ),
                        )
                    ]
                    for ps in ps_present:
                        val = lookup.get((p_db, ps, method_id))
                        if val is not None and pd.notna(val):
                            row_cells.append(
                                ui.tags.td(f"{val:.1f}%", style=cell_style(val))
                            )
                        else:
                            row_cells.append(ui.tags.td("-", style=_th_style))
                    data_rows_cm.append(ui.tags.tr(*row_cells))

                if not data_rows_cm:
                    continue

                # Footer: regulator count per column. Identical across methods when
                # "Common regulators only" is on; otherwise show the range.
                n_footer_cells = [
                    ui.tags.td(
                        (
                            "N Shared Regulators"
                            if read_metric(input) == METRIC_DTO
                            else "N Regulators"
                        ),
                        style=(
                            "padding: 4px 10px; text-align: left;"
                            " font-size: 0.8rem; color: #666;"
                        ),
                    )
                ]
                for ps in ps_present:
                    counts = [
                        n_reg_lookup[(p_db, ps, m)]
                        for m in methods_present
                        if (p_db, ps, m) in n_reg_lookup
                    ]
                    if not counts:
                        text = "-"
                    elif min(counts) == max(counts):
                        text = str(min(counts))
                    else:
                        text = f"{min(counts)}-{max(counts)}"
                    n_footer_cells.append(
                        ui.tags.td(
                            text,
                            style=(
                                "padding: 4px 10px; text-align: right;"
                                " font-size: 0.8rem; color: #666;"
                            ),
                        )
                    )
                data_rows_cm.append(ui.tags.tr(*n_footer_cells))

                cards.append(
                    ui.div(
                        {
                            "style": (
                                "flex: 0 0 auto; min-width: 260px;"
                                " border: 1px solid #ddd;"
                                " border-radius: 4px; overflow: hidden;"
                            )
                        },
                        ui.div(
                            {
                                "style": (
                                    "padding: 6px 10px; font-weight: 600;"
                                    " font-size: 0.9rem; background-color: #f5f5f5;"
                                    " border-bottom: 1px solid #ddd;"
                                )
                            },
                            ui.tooltip(
                                ui.span(f"{p_label} — {binding_label}"),
                                shared.metric_note(p_db),
                            ),
                        ),
                        ui.tags.table(
                            {
                                "style": (
                                    "border-collapse: collapse;"
                                    " font-size: 0.9rem; width: 100%;"
                                )
                            },
                            ui.tags.thead(
                                {"style": "background-color: #f5f5f5;"},
                                ui.tags.tr(*header_cells),
                            ),
                            ui.tags.tbody(*data_rows_cm),
                        ),
                    )
                )

            if not cards:
                return empty_state(
                    ui.p("No data for the selected combination."),
                )

            return ui.div(
                {
                    "style": (
                        "margin-top: 0.5rem; display: flex;"
                        " flex-direction: column; gap: 1.5rem;"
                    )
                },
                *cards,
            )


__all__ = ["register_compare_methods"]
