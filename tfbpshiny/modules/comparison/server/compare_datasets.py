"""Tab 1, Compare Datasets: the binding x perturbation matrix and its distributions."""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd
import plotly.graph_objects as go
from plotly.io import to_html
from shiny import reactive, render, ui

from tfbpshiny.components import empty_state
from tfbpshiny.modules.comparison.queries import (
    METRIC_DTO,
    fetch_topn_results,
)
from tfbpshiny.modules.comparison.server.context import (
    ComparisonContext,
    inputs_ready,
    read_full_overlap,
    read_metric,
    read_preset,
    read_top_n,
)
from tfbpshiny.modules.comparison.server.shared import Shared
from tfbpshiny.utils.perf import perf
from tfbpshiny.utils.topn_matrix import build_topn_matrix_ui


def register_compare_datasets(
    input: Any, session: Any, ctx: ComparisonContext, shared: Shared
) -> None:
    """
    Register the Compare Datasets tab's reactives and outputs.

    :param input: Shiny input object of the comparison module.
    :param session: Module session.
    :param ctx: Per-session context.
    :param shared: Shared helpers.

    """
    conn = ctx.conn
    binding_index = ctx.binding_index

    cd_selected_binding: reactive.Value[str | None] = reactive.value(None)
    cd_selected_perturbation: reactive.Value[str | None] = reactive.value(None)

    @reactive.calc
    def _cd_data() -> pd.DataFrame:
        """
        TopN data for the Compare Datasets tab.

        :trigger: ``input.cd_binding_method`` / ``input.cd_promoter_set`` — tab
            controls.
        :trigger: ``input.top_n`` / ``input.responsiveness_preset`` /
            ``input.require_intersecting_floor`` — shared sidebar controls.
        :trigger: ``active_binding_datasets`` / ``active_perturbation_datasets`` /
            ``dataset_filters`` — committed dataset selection.

        """
        if not inputs_ready(input, "cd_binding_method", "cd_promoter_set"):
            return pd.DataFrame()
        b_dbs = shared.cd_binding_dbs()
        p_dbs = ctx.active_perturbation_datasets()
        if not b_dbs or not p_dbs:
            return pd.DataFrame()
        pairs = [(b, p) for b in b_dbs for p in p_dbs]
        if read_metric(input) == METRIC_DTO:
            raw = shared.dto_frame(pairs)
            if raw.empty:
                return raw
            # The matrix takes a median per cell; with one row per pair that is the
            # value itself, so the renderer needs no DTO-specific branch.
            raw["percent_responsive"] = raw["val"]
            return raw
        filters = ctx.dataset_filters()
        n = read_top_n(input)
        preset = read_preset(input)
        floor = read_full_overlap(input)
        ctx.logger.debug("cd_data: %d pairs", len(pairs))
        with perf(session.id, "comparison.workspace", "_cd_data", kind="data"):
            try:
                raw = fetch_topn_results(
                    conn, pairs, filters, n, preset, require_full_overlap=floor
                )
            except Exception:
                ctx.logger.exception("cd_data fetch failed")
                return pd.DataFrame()
        if raw.empty:
            return pd.DataFrame()
        raw["binding_label"] = (
            raw["binding_db"].map(binding_index.label).fillna(raw["binding_db"])
        )
        raw["perturbation_source"] = (
            raw["perturbation_db"].map(ctx.base_label).fillna(raw["perturbation_db"])
        )
        raw["regulator_label"] = (
            raw["regulator_locus_tag"]
            .map(ctx.reg_labels)
            .fillna(raw["regulator_locus_tag"])
        )
        raw["percent_responsive"] = raw["responsive_ratio"] * 100
        return raw

    def _make_cd_row_effect(b_db: str) -> None:
        @reactive.effect
        @reactive.event(input[f"topnrow_{b_db}"])
        def _on_row() -> None:
            cd_selected_binding.set(b_db)
            cd_selected_perturbation.set(None)

    def _make_cd_col_effect(p_db: str) -> None:
        @reactive.effect
        @reactive.event(input[f"topncol_{p_db}"])
        def _on_col() -> None:
            cd_selected_perturbation.set(p_db)
            cd_selected_binding.set(None)

    for _b in ctx.all_binding_dbs:
        _make_cd_row_effect(_b)
    for _p in ctx.all_perturbation_dbs:
        _make_cd_col_effect(_p)

    @render.ui
    def cd_matrix_container() -> ui.Tag:
        """
        Binding × perturbation top-N responsive ratio matrix.

        :trigger: ``_cd_data`` — re-renders when data changes.
        :trigger: ``cd_selected_binding`` / ``cd_selected_perturbation`` — highlights.

        """
        if (msg := shared.dto_unavailable()) is not None:
            return msg
        with perf(session.id, "comparison.workspace", "cd_matrix_container"):
            df = _cd_data()
            b_dbs = shared.cd_binding_dbs()
            p_dbs = ctx.active_perturbation_datasets()
            if not b_dbs or not p_dbs:
                return empty_state(
                    ui.p("No datasets selected."),
                )

            topn_medians: dict[tuple[str, str], float | None] = {}
            if not df.empty:
                med_df = duckdb.execute(
                    """
                    SELECT binding_db, perturbation_db,
                        median(percent_responsive) AS med
                    FROM df
                    GROUP BY binding_db, perturbation_db
                """
                ).df()
                topn_medians = {
                    (row.binding_db, row.perturbation_db): (
                        float(row.med) if pd.notna(row.med) else None
                    )
                    for row in med_df.itertuples(index=False)
                }

            def _col_tooltip(p_db: str) -> str:
                note = shared.metric_note(p_db)
                return (
                    f"{note}. "
                    "Click to view distributions for this perturbation dataset."
                )

            return build_topn_matrix_ui(
                binding_datasets=b_dbs,
                perturbation_datasets=p_dbs,
                topn_medians=topn_medians,
                display_names={
                    **ctx.display_names,
                    **binding_index.label,
                    **{p: ctx.base_label.get(p, p) for p in p_dbs},
                },
                selected_binding=cd_selected_binding(),
                selected_perturbation=cd_selected_perturbation(),
                ns=session.ns,
                col_tooltip=_col_tooltip,
            )

    @render.ui
    def cd_distribution_container() -> ui.Tag:
        """
        Box plots for the selected matrix row or column.

        :trigger: ``_cd_data`` — re-renders when data changes.
        :trigger: ``cd_selected_binding`` / ``cd_selected_perturbation`` — selection.

        """
        if (msg := shared.dto_unavailable()) is not None:
            return msg
        if read_metric(input) == METRIC_DTO:
            # DTO yields one percentage per dataset pair, not a per-regulator spread,
            # so there is no distribution to draw.
            return empty_state(
                ui.p(
                    "Distributions are only available for the Top-N metric. DTO"
                    " produces a single percentage per dataset pair rather than a"
                    " per-regulator value."
                ),
            )
        with perf(session.id, "comparison.workspace", "cd_distribution_container"):
            df = _cd_data()
            if df.empty:
                return ui.span()

            b_sel = cd_selected_binding()
            p_sel = cd_selected_perturbation()

            if b_sel is None and p_sel is None:
                return empty_state(
                    ui.p(
                        "Click a row header to view distributions for a binding"
                        " dataset, or a column header to view distributions for a"
                        " perturbation dataset."
                    ),
                )

            if b_sel is not None:
                sub = df[df["binding_db"] == b_sel]
                x_col = "perturbation_source"
            else:
                sub = df[df["perturbation_db"] == p_sel]
                x_col = "binding_label"

            if sub.empty:
                return empty_state(
                    ui.p("No data for the selected datasets."),
                )

            fig = go.Figure()
            x_vals = sorted(sub[x_col].dropna().unique(), key=lambda v: str(v))
            for x_val in x_vals:
                grp = sub[sub[x_col] == x_val]
                mask = grp["percent_responsive"].notna()
                fig.add_trace(
                    go.Box(
                        x=grp.loc[mask, x_col].values,
                        y=grp.loc[mask, "percent_responsive"].values,
                        name=str(x_val),
                        text=grp.loc[mask, "regulator_label"].values,
                        hovertemplate="%{text}<br>%{y:.1f}%<extra></extra>",
                        hoveron="points",
                        boxpoints="all",
                        jitter=0.4,
                        pointpos=0,
                        marker=dict(size=4, opacity=0.5),
                        line=dict(width=1.5),
                        showlegend=False,
                    )
                )

            if not fig.data:
                return ui.span()

            y_title = (
                "% regulators with DTO p < 0.01"
                if read_metric(input) == METRIC_DTO
                else "% responsive in top N"
            )
            fig.update_yaxes(title_text=y_title, range=[0, 100])
            fig.update_layout(margin=dict(l=50, r=20, t=40, b=80))
            return ui.div(
                {"style": "margin-top: 1.5rem;"},
                ui.HTML(to_html(fig, include_plotlyjs=False, full_html=False)),
            )


__all__ = ["register_compare_datasets"]
