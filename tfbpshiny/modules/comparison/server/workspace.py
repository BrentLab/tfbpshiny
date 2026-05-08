"""Workspace server for the Comparison module."""

from __future__ import annotations

from collections.abc import Callable
from logging import Logger
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from labretriever import VirtualDB
from plotly.io import to_html
from plotly.subplots import make_subplots
from shiny import module, reactive, render, ui

from tfbpshiny.modules.comparison.queries import (
    BINDING_CONFIGS,
    BINDING_LABEL_MAP,
    PERTURBATION_CONFIGS,
    PERTURBATION_LABEL_MAP,
    topn_all_pairs_sql,
)
from tfbpshiny.utils.perf import perf, reset_render_counts
from tfbpshiny.utils.ratelimit import debounce
from tfbpshiny.utils.vdb_init import get_regulator_display_name

# color palettes
BINDING_COLORS: dict[str, str] = {
    "2004 ChIP-chip": "#E64B35",
    "2021 ChIPexo": "#F39B7F",
    "2025 Chec-seq": "#00A087",
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
    "2021 ChIPexo",
    "2025 Chec-seq",
    "2026 Calling Cards",
]


@module.server
def comparison_workspace_server(
    input: Any,
    output: Any,
    session: Any,
    active_binding_datasets: reactive.Calc_[list[str]],
    active_perturbation_datasets: reactive.Calc_[list[str]],
    dataset_filters: reactive.Value[dict[str, Any]],
    top_n: Callable[[], int],
    effect_threshold: Callable[[], float],
    pvalue_threshold: Callable[[], float],
    facet_by: Callable[[], str],
    vdb: VirtualDB,
    logger: Logger,
) -> None:
    """Render the Top-N by Binding workspace plot."""

    session.on_flush(lambda: reset_render_counts(session.id))

    @reactive.calc
    def _active_binding_labels() -> dict[str, str]:
        with perf(session.id, "comparison.workspace", "_active_binding_labels"):
            return {
                db: BINDING_LABEL_MAP.get(db, db) for db in active_binding_datasets()
            }

    @reactive.calc
    def _active_perturbation_labels() -> dict[str, str]:
        with perf(session.id, "comparison.workspace", "_active_perturbation_labels"):
            return {
                db: PERTURBATION_LABEL_MAP.get(db, db)
                for db in active_perturbation_datasets()
            }

    @debounce(0.3)
    @reactive.calc
    def _topn_data() -> pd.DataFrame:
        """
        Compute top-N responsive ratio for all active (binding, perturbation) pairs.

        :trigger _active_binding_labels: re-runs when binding selection changes.
        :trigger _active_perturbation_labels: re-runs when perturbation changes.
        :trigger dataset_filters: re-runs when filters are applied or reset. :trigger
        top_n: re-runs when the top-N cutoff changes. :trigger effect_threshold: re-runs
        when the effect threshold changes. :trigger pvalue_threshold: re-runs when the
        p-value threshold changes.

        """
        with perf(session.id, "comparison.workspace", "_topn_data"):
            binding_labels = _active_binding_labels()
            pert_labels = _active_perturbation_labels()
            filters = dataset_filters()
            n = top_n()
            eff = effect_threshold()
            pval = pvalue_threshold()

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
        orientation = facet_by()

        if df.empty:
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
        return ui.HTML(to_html(fig, include_plotlyjs="cdn", full_html=False))


__all__ = ["comparison_workspace_server"]
