"""Workspace server for the Comparison module."""

from __future__ import annotations

from logging import Logger
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from labretriever import VirtualDB
from plotly.io import to_html
from plotly.subplots import make_subplots
from shiny import reactive, render, req, ui

from tfbpshiny.modules.comparison.queries import (
    BINDING_CONFIGS,
    BINDING_LABEL_MAP,
    DEFAULT_EFFECT_THRESHOLD,
    DEFAULT_PVALUE_THRESHOLD,
    DEFAULT_TOP_N,
    PERTURBATION_CONFIGS,
    PERTURBATION_LABEL_MAP,
    PROMOTER_VARIANT_PAIRS,
    topn_all_pairs_sql,
)
from tfbpshiny.utils.perf import perf, reset_render_counts
from tfbpshiny.utils.vdb_init import get_regulator_display_name

# color palettes
BINDING_COLORS: dict[str, str] = {
    "2004 ChIP-chip": "#E64B35",
    "2021 ChIP-exo": "#F39B7F",
    "2025 ChEC-seq": "#00A087",
    "2026 Calling Cards": "#3C5488",
}

PERTURBATION_COLORS: dict[str, str] = {
    "2006 Overexpression": "#F39B7F",
    "2006 TFKO": "#00A087",
    "2007 TFKO": "#8491B4",
    "2014 TFKO": "#4DBBD5",
    "2020 Overexpression": "#91D1C2",
    "2025 Degron": "#B09C85",
}

_PERT_ORDER = [
    "2006 Overexpression",
    "2006 TFKO",
    "2007 TFKO",
    "2014 TFKO",
    "2020 Overexpression",
    "2025 Degron",
]

_BINDING_ORDER = [
    "2004 ChIP-chip",
    "2021 ChIP-exo",
    "2025 ChEC-seq",
    "2026 Calling Cards",
]


def comparison_workspace_server(
    input: Any,
    output: Any,
    session: Any,
    active_binding_datasets: reactive.Calc_[list[str]],
    active_perturbation_datasets: reactive.Calc_[list[str]],
    dataset_filters: reactive.Value[dict[str, Any]],
    vdb: VirtualDB,
    logger: Logger,
    active_tab: reactive.Calc_[str] | None = None,
) -> None:
    """Render the Top-N by Binding workspace plot."""

    session.on_flush(lambda: reset_render_counts(session.id))

    # Stable reactive value for query params; only invalidates downstream when values
    # actually change, breaking the input-echo double-run on tab switch.
    _query_params: reactive.Value[tuple[int, float, float]] = reactive.value(
        (DEFAULT_TOP_N, DEFAULT_EFFECT_THRESHOLD, DEFAULT_PVALUE_THRESHOLD)
    )

    @reactive.effect
    def _sync_query_params() -> None:
        """
        Write sidebar param values to ``_query_params`` only when they change.

        :trigger top_n: re-fires when the top-N input changes. :trigger
        effect_threshold: re-fires when the effect threshold changes. :trigger
        pvalue_threshold: re-fires when the p-value threshold changes.

        """
        new = (input.top_n(), input.effect_threshold(), input.pvalue_threshold())
        with reactive.isolate():
            if new != _query_params():
                _query_params.set(new)

    # Stable binding labels — updated only when the active binding dataset set changes.
    _active_binding_labels_val: reactive.Value[dict[str, str]] = reactive.value({})

    @reactive.effect
    def _sync_active_binding_labels() -> None:
        """
        Write binding labels to ``_active_binding_labels_val`` only when they change.

        :trigger active_binding_datasets: re-fires when binding selection changes.
        :trigger active_tab: silently blocks when another tab is active.

        """
        if active_tab is not None:
            req(active_tab() == "Comparison")
        with perf(session.id, "comparison.workspace", "_active_binding_labels"):
            new = {
                db: BINDING_LABEL_MAP.get(db, db) for db in active_binding_datasets()
            }
        with reactive.isolate():
            if new != _active_binding_labels_val():
                _active_binding_labels_val.set(new)

    @reactive.calc
    def _active_perturbation_labels() -> dict[str, str]:
        """:trigger active_perturbation_datasets: re-runs when perturbation selection
        changes."""
        with perf(session.id, "comparison.workspace", "_active_perturbation_labels"):
            return {
                db: PERTURBATION_LABEL_MAP.get(db, db)
                for db in active_perturbation_datasets()
            }

    @reactive.calc
    def _topn_data() -> pd.DataFrame:
        """
        Compute top-N responsive ratio for all active (binding, perturbation) pairs.

        :trigger _active_binding_labels_val: re-runs when binding selection changes;
        only invalidated when the label dict content actually changes, so returning
        to this tab without changing datasets hits the cache. :trigger
        _active_perturbation_labels: re-runs when perturbation changes. :trigger
        dataset_filters: re-runs when filters are applied or reset. :trigger
        _query_params: re-runs when top-N, effect, or p-value thresholds     actually
        change (stable value, does not re-fire on input echo).

        """
        with perf(session.id, "comparison.workspace", "_topn_data"):
            binding_labels = _active_binding_labels_val()
            pert_labels = _active_perturbation_labels()
            filters = dataset_filters()
            n, eff, pval = _query_params()

            if not binding_labels or not pert_labels:
                return pd.DataFrame()

            _reg_df = get_regulator_display_name(vdb)
            reg_labels: dict[str, str] = dict(
                zip(_reg_df["regulator_locus_tag"], _reg_df["display_name"])
            )

            pairs = [
                (b_db, p_db)
                for b_db in binding_labels
                if BINDING_CONFIGS.get(b_db) is not None
                for p_db in pert_labels
                if PERTURBATION_CONFIGS.get(p_db) is not None
            ]

            skipped_binding = [
                b for b in binding_labels if BINDING_CONFIGS.get(b) is None
            ]
            skipped_pert = [
                p for p in pert_labels if PERTURBATION_CONFIGS.get(p) is None
            ]
            for b in skipped_binding:
                logger.warning(f"No binding config for {b}, skipping")
            for p in skipped_pert:
                logger.warning(f"No perturbation config for {p}, skipping")

            if not pairs:
                return pd.DataFrame()

            try:
                combined = topn_all_pairs_sql(vdb, pairs, filters, n, eff, pval)
            except Exception as exc:
                logger.error(f"topn_all_pairs_sql failed: {exc}", exc_info=True)
                return pd.DataFrame()

            if combined.empty or "pair_key" not in combined.columns:
                return pd.DataFrame()

            results: list[pd.DataFrame] = []
            for b_db, p_db in pairs:
                pair_key = f"{b_db}__{p_db}"
                subset = (
                    combined[combined["pair_key"] == pair_key]
                    .drop(columns=["pair_key"])
                    .reset_index(drop=True)
                    .copy()
                )
                if subset.empty:
                    continue
                subset["binding_source"] = binding_labels[b_db]
                subset["perturbation_source"] = pert_labels[p_db]
                subset["regulator_label"] = (
                    subset["regulator_locus_tag"]
                    .map(reg_labels)
                    .fillna(subset["regulator_locus_tag"])
                )
                results.append(subset)

            if not results:
                return pd.DataFrame()
            out = pd.concat(results, ignore_index=True)
            out["percent_responsive"] = out["responsive_ratio"] * 100
            return out

    @render.ui
    def topn_plot() -> ui.Tag:
        """
        Boxplot of percent-responsive for top-N binding targets, with individual points
        overlaid. Points show regulator display name on hover. The boxplot itself has no
        tooltip.

        :trigger _topn_data: re-renders when top-N data changes. :trigger facet_by: re-
        renders when facet orientation changes. :trigger top_n: re-renders when the
        top-N cutoff changes.

        """
        df = _topn_data()
        orientation = input.facet_by()

        if df.empty:
            no_binding = not _active_binding_labels_val()
            no_perturbation = not _active_perturbation_labels()
            if no_binding or no_perturbation:
                return ui.div(
                    {"class": "empty-state"},
                    ui.p(
                        "Select at least one binding and one perturbation dataset "
                        "from the Select Datasets page."
                    ),
                )
            return ui.div(
                {"class": "empty-state"},
                ui.p("No top-N data available for the selected datasets."),
            )

        if orientation == "binding":
            facet_col = "binding_source"
            x_col = "perturbation_source"
            facet_order = [
                b for b in _BINDING_ORDER if b in df["binding_source"].unique()
            ]
            x_order = [
                p for p in _PERT_ORDER if p in df["perturbation_source"].unique()
            ]
            palette = PERTURBATION_COLORS
            legend_title = "Perturbation source"
        else:
            facet_col = "perturbation_source"
            x_col = "binding_source"
            facet_order = [
                p for p in _PERT_ORDER if p in df["perturbation_source"].unique()
            ]
            x_order = [b for b in _BINDING_ORDER if b in df["binding_source"].unique()]
            palette = BINDING_COLORS
            legend_title = "Binding source"

        facets = [f for f in facet_order if f in df[facet_col].unique()]
        xs = [x for x in x_order if x in df[x_col].unique()]

        if not facets or not xs:
            return ui.div(
                {"class": "empty-state"}, ui.p("No data for selected combination.")
            )

        subplot_titles = facets

        fig = make_subplots(
            rows=1,
            cols=len(facets),
            subplot_titles=subplot_titles,
            shared_yaxes=True,
        )

        for col_idx, facet_val in enumerate(facets, start=1):
            sub = df[df[facet_col] == facet_val]
            for x_val in xs:
                color = palette.get(x_val, "#888888")
                grp = sub.loc[sub[x_col] == x_val].copy()
                vals = grp["percent_responsive"].dropna()
                reg_labels_col = grp.loc[
                    grp["percent_responsive"].notna(), "regulator_label"
                ]

                # Single Box trace: boxpoints="all" renders the individual
                # points with jitter. hoveron="points" disables the tooltip on
                # the box and whiskers and keeps it only on the dots.
                # text is used as the hover label for each point.
                fig.add_trace(
                    go.Box(
                        y=vals,
                        name=x_val,
                        marker_color=color,
                        boxpoints="all",
                        jitter=0.4,
                        pointpos=0,
                        marker=dict(size=4, opacity=0.5),
                        line=dict(width=1.2),
                        legendgroup=x_val,
                        showlegend=(col_idx == 1),
                        hoveron="points",
                        text=reg_labels_col.values,
                        hovertemplate="%{text}<br>%{y:.1f}%<extra></extra>",
                    ),
                    row=1,
                    col=col_idx,
                )

            fig.update_xaxes(showticklabels=False, row=1, col=col_idx)

        fig.update_yaxes(
            title_text="% responsive in top N", range=[0, 100], row=1, col=1
        )
        fig.update_layout(
            legend_title=legend_title,
            margin=dict(l=50, r=20, t=80, b=30),
        )
        return ui.HTML(to_html(fig, include_plotlyjs=False, full_html=False))

    # Detect which Mindel variants are available in this VirtualDB instance once.
    _available_datasets: frozenset[str] = frozenset(vdb.get_datasets())

    @reactive.calc
    def _promoter_table_data() -> dict[str, pd.DataFrame]:
        """
        Compute per-cell median % responsive for primary/Mindel promoter variant pairs.

        For each active binding dataset that has a registered Mindel variant, queries
        ``topn_all_pairs_sql`` for both the primary and Mindel binding views crossed
        with all active perturbation datasets. Returns a dict keyed by primary db_name
        where each value is a DataFrame with perturbation labels as the index and
        [primary_label, mindel_label] as columns.

        :trigger _active_binding_labels_val: re-runs when binding selection changes.
        :trigger _active_perturbation_labels: re-runs when perturbation selection
            changes.
        :trigger dataset_filters: re-runs when filters change.
        :trigger _query_params: re-runs when top-N or threshold params change.
        :returns: Dict mapping primary db_name to summary DataFrame, or empty dict when
            no variants are active.

        """
        binding_labels = _active_binding_labels_val()
        pert_labels = _active_perturbation_labels()
        filters = dataset_filters()
        n, eff, pval = _query_params()

        result: dict[str, pd.DataFrame] = {}

        for primary_db, mindel_db in PROMOTER_VARIANT_PAIRS.items():
            if primary_db not in binding_labels:
                continue
            if mindel_db not in _available_datasets:
                continue
            if not pert_labels:
                continue

            pairs = []
            for p_db in pert_labels:
                if PERTURBATION_CONFIGS.get(p_db) is None:
                    continue
                pairs.append((primary_db, p_db))
                pairs.append((mindel_db, p_db))

            if not pairs:
                continue

            try:
                combined = topn_all_pairs_sql(vdb, pairs, filters, n, eff, pval)
            except Exception as exc:
                logger.error(
                    f"promoter table query failed for {primary_db}: {exc}",
                    exc_info=True,
                )
                continue

            if combined.empty or "pair_key" not in combined.columns:
                continue

            primary_label = BINDING_LABEL_MAP.get(primary_db, primary_db)
            mindel_label = BINDING_LABEL_MAP.get(mindel_db, mindel_db)

            rows: dict[str, dict[str, float]] = {}
            for p_db, p_label in pert_labels.items():
                if PERTURBATION_CONFIGS.get(p_db) is None:
                    continue
                row: dict[str, float] = {}
                for b_db, col_label in (
                    (primary_db, primary_label),
                    (mindel_db, mindel_label),
                ):
                    pair_key = f"{b_db}__{p_db}"
                    subset = combined[combined["pair_key"] == pair_key]
                    if subset.empty:
                        continue
                    # Per-regulator median across all sample combinations, then
                    # median across regulators to get one scalar per cell.
                    per_reg = (
                        subset.groupby("regulator_locus_tag")[
                            "responsive_ratio"
                        ].median()
                        * 100
                    )
                    row[col_label] = float(per_reg.median())
                if row:
                    rows[p_label] = row

            if not rows:
                continue

            df = pd.DataFrame(rows).T.reindex(columns=[primary_label, mindel_label])
            df.index.name = "Perturbation"
            result[primary_db] = df

        return result

    @render.ui
    def promoter_comparison() -> ui.Tag:
        """
        HTML summary tables comparing primary vs Mindel promoter variants.

        Renders one table per active binding dataset that has a Mindel variant. Tables
        are arranged in a flex-wrap row so they sit side-by-side on wide viewports and
        stack on narrow ones.

        :trigger _promoter_table_data: re-renders when table data changes.

        """
        tables_data = _promoter_table_data()
        if not tables_data:
            return ui.span()

        def _cell_style(val: float) -> str:
            """HSL green scale: 0% -> white, 100% -> full green."""
            clamped = max(0.0, min(100.0, val))
            lightness = 100 - clamped * 0.5
            return (
                f"background-color: hsl(120, 60%, {lightness:.0f}%);"
                " padding: 6px 10px; text-align: right;"
            )

        _th_style = "padding: 6px 10px; text-align: right;"
        _header = ui.tags.tr(
            ui.tags.th("Perturbation", style="padding: 6px 10px; text-align: left;"),
            ui.tags.th("Kang promoters", style=_th_style),
            ui.tags.th("Mindel promoters", style=_th_style),
        )

        table_tags: list[ui.Tag] = []
        for primary_db, df in tables_data.items():
            primary_label, mindel_label = df.columns[0], df.columns[1]
            header = _header
            data_rows: list[ui.Tag] = []
            for pert_label, row in df.iterrows():
                primary_val = row.get(primary_label)
                mindel_val = row.get(mindel_label)
                data_rows.append(
                    ui.tags.tr(
                        ui.tags.td(
                            str(pert_label),
                            style=(
                                "padding: 6px 10px; text-align: left;"
                                " white-space: nowrap;"
                            ),
                        ),
                        ui.tags.td(
                            (
                                f"{primary_val:.1f}%"
                                if primary_val is not None and not pd.isna(primary_val)
                                else "-"
                            ),
                            style=(
                                _cell_style(primary_val)
                                if primary_val is not None and not pd.isna(primary_val)
                                else "padding: 6px 10px; text-align: right;"
                            ),
                        ),
                        ui.tags.td(
                            (
                                f"{mindel_val:.1f}%"
                                if mindel_val is not None and not pd.isna(mindel_val)
                                else "-"
                            ),
                            style=(
                                _cell_style(mindel_val)
                                if mindel_val is not None and not pd.isna(mindel_val)
                                else "padding: 6px 10px; text-align: right;"
                            ),
                        ),
                    )
                )
            table_tags.append(
                ui.div(
                    {
                        "style": (
                            "flex: 1 1 0; border: 1px solid #ddd; border-radius: 4px;"
                            " overflow: hidden;"
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
                        primary_label,
                    ),
                    ui.tags.table(
                        {
                            "style": (
                                "border-collapse: collapse; font-size: 0.9rem;"
                                " width: 100%;"
                            )
                        },
                        ui.tags.thead(
                            {"style": "background-color: #f5f5f5;"},
                            header,
                        ),
                        ui.tags.tbody(*data_rows),
                    ),
                )
            )

        return ui.div(
            {
                "style": (
                    "display: flex; flex-wrap: wrap; gap: 1.5rem;"
                    " margin-top: 0.5rem;"
                )
            },
            *table_tags,
        )


__all__ = ["comparison_workspace_server"]
