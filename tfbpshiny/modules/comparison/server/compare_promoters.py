"""Tab 2, Compare Promoter Definitions: top-N response across promoter sets."""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd
from shiny import reactive, render, ui

from tfbpshiny.components import empty_state, scroll_row
from tfbpshiny.modules.comparison.queries import (
    METRIC_DTO,
    PERTURBATION_LABEL_MAP,
    PROMOTER_SET_LABELS,
    PROMOTER_SET_LEVELS,
    fetch_topn_results,
)
from tfbpshiny.modules.comparison.server.context import (
    BINDING_ORDER_LABELS,
    PROMOTER_SET_ALIAS,
    PROMOTER_TOOLTIPS,
    ComparisonContext,
    cell_style,
    inputs_ready,
    read_full_overlap,
    read_metric,
    read_preset,
    read_top_n,
)
from tfbpshiny.modules.comparison.server.shared import Shared
from tfbpshiny.utils.inputs import read_input
from tfbpshiny.utils.perf import perf


def register_compare_promoters(
    input: Any, session: Any, ctx: ComparisonContext, shared: Shared
) -> None:
    """
    Register the Compare Promoter Definitions tab's reactives and outputs.

    :param input: Shiny input object of the comparison module.
    :param session: Module session.
    :param ctx: Per-session context.
    :param shared: Shared helpers.

    """
    conn = ctx.conn
    binding_index = ctx.binding_index

    @reactive.calc
    def _cp_data() -> pd.DataFrame:
        """
        TopN data for the Compare Promoter Definitions tab.

        :trigger: ``input.cp_included_promoter_sets`` — tab control.
        :trigger: ``input.top_n`` / ``input.responsiveness_preset`` /
            ``input.require_intersecting_floor`` — shared sidebar controls.
        :trigger: ``active_binding_datasets`` / ``active_perturbation_datasets`` /
            ``dataset_filters`` — committed dataset selection.

        """
        if not inputs_ready(input, "cp_included_promoter_sets"):
            return pd.DataFrame()
        b_dbs = shared.cp_binding_dbs()
        p_dbs = ctx.active_perturbation_datasets()
        if not b_dbs or not p_dbs:
            return pd.DataFrame()
        pairs = [(b, p) for b in b_dbs for p in p_dbs]
        if read_metric(input) == METRIC_DTO:
            raw = shared.dto_frame(pairs)
            if raw.empty:
                return raw
            return raw[
                ["perturbation_db", "binding_base_label", "promoter_set_id", "val"]
            ]
        filters = ctx.dataset_filters()
        n = read_top_n(input)
        preset = read_preset(input)
        floor = read_full_overlap(input)
        ctx.logger.debug("cp_data: %d pairs", len(pairs))
        with perf(session.id, "comparison.workspace", "_cp_data", kind="data"):
            try:
                raw = fetch_topn_results(
                    conn, pairs, filters, n, preset, require_full_overlap=floor
                )
            except Exception:
                ctx.logger.exception("cp_data fetch failed")
                return pd.DataFrame()
        if raw.empty:
            return pd.DataFrame()
        raw["binding_base_label"] = (
            raw["binding_db"].map(binding_index.base_label).fillna(raw["binding_db"])
        )
        # Keyed by raw promoter_set_id (not the display label) so it matches the
        # ids the sidebar checkbox group emits; the render maps to labels.
        raw["promoter_set_id"] = (
            raw["binding_db"].map(binding_index.promoter_set_id).fillna("")
        )
        return duckdb.execute(
            """
            WITH per_reg AS (
                SELECT
                    perturbation_db,
                    binding_base_label,
                    promoter_set_id,
                    regulator_locus_tag,
                    median(responsive_ratio) * 100 AS med_pct
                FROM raw
                GROUP BY perturbation_db, binding_base_label, promoter_set_id,
                    regulator_locus_tag
            )
            SELECT
                perturbation_db,
                binding_base_label,
                promoter_set_id,
                round(median(med_pct), 4) AS val
            FROM per_reg
            GROUP BY perturbation_db, binding_base_label, promoter_set_id
        """
        ).df()

    @render.ui
    def cp_promoter_table() -> ui.Tag:
        """
        Per-perturbation table comparing top-N % responsive across promoter sets.

        :trigger: ``_cp_data`` — re-renders when data changes.

        """
        if (msg := shared.dto_unavailable()) is not None:
            return msg
        with perf(session.id, "comparison.workspace", "cp_promoter_table"):
            agg = _cp_data()
            p_dbs = ctx.active_perturbation_datasets()
            if not p_dbs:
                return empty_state(
                    ui.p("No perturbation datasets selected."),
                )
            if agg.empty:
                return empty_state(
                    ui.p("No data for the selected datasets."),
                )

            selected_ps = set(
                read_input(
                    input, "cp_included_promoter_sets", list(PROMOTER_SET_ALIAS), list
                )
            )
            # Keep the canonical column order regardless of checkbox click order.
            included_ps = [ps for ps in PROMOTER_SET_LEVELS if ps in selected_ps]

            _th_style = "padding: 6px 10px; text-align: right;"

            lookup: dict[tuple[str, str, str], float] = {
                (
                    row.perturbation_db,
                    row.binding_base_label,
                    row.promoter_set_id,
                ): row.val
                for row in agg.itertuples(index=False)
            }

            cards: list[ui.Tag] = []
            for p_db in p_dbs:
                p_label = PERTURBATION_LABEL_MAP.get(p_db, p_db)
                sub_agg = agg[agg["perturbation_db"] == p_db]
                if sub_agg.empty:
                    continue

                binding_base_labels = [
                    b
                    for b in BINDING_ORDER_LABELS
                    if b in set(sub_agg["binding_base_label"])
                ]

                header_cells = [
                    ui.tags.th(
                        "Binding Dataset",
                        style="padding: 6px 10px; text-align: left;",
                    )
                ]
                for ps in included_ps:
                    header_cells.append(
                        ui.tags.th(
                            ui.tooltip(
                                ui.span(PROMOTER_SET_LABELS.get(ps, ps)),
                                PROMOTER_TOOLTIPS.get(ps, ""),
                            ),
                            style=_th_style,
                        )
                    )

                data_rows: list[ui.Tag] = []
                for base_label in binding_base_labels:
                    row_cells = [
                        ui.tags.td(
                            base_label,
                            style=(
                                "padding: 6px 10px; text-align: left; "
                                "white-space: nowrap;"
                            ),
                        )
                    ]
                    for ps in included_ps:
                        val = lookup.get((p_db, base_label, ps))
                        if val is not None and pd.notna(val):
                            row_cells.append(
                                ui.tags.td(f"{val:.1f}%", style=cell_style(val))
                            )
                        else:
                            row_cells.append(
                                ui.tags.td(
                                    "-", style="padding: 6px 10px; text-align: right;"
                                )
                            )
                    data_rows.append(ui.tags.tr(*row_cells))

                if not data_rows:
                    continue

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
                                ui.span(p_label),
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
                            ui.tags.tbody(*data_rows),
                        ),
                    )
                )

            if not cards:
                return empty_state(
                    ui.p("No data for the selected combination."),
                )

            return ui.div(
                {"style": "margin-top: 0.5rem;"}, scroll_row(*cards, gap="lg")
            )


__all__ = ["register_compare_promoters"]
