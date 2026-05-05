"""Workspace server for the Comparison module."""

from __future__ import annotations

import time
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
    topn_responsive_ratio,
)
from tfbpshiny.utils.profiler import profile_span
from tfbpshiny.utils.query_cache import cached_query
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
    profile_logger: Logger,
    session_id: str = "",
) -> None:
    """Render the Top-N by Binding workspace plot."""

    _render_counts: dict[str, int] = {"topn_plot": 0}

    @reactive.calc
    def _active_binding_labels() -> dict[str, str]:
        return {db: BINDING_LABEL_MAP.get(db, db) for db in active_binding_datasets()}

    @reactive.calc
    def _active_perturbation_labels() -> dict[str, str]:
        return {
            db: PERTURBATION_LABEL_MAP.get(db, db)
            for db in active_perturbation_datasets()
        }

    # Persistent top-N data cache.  Stored as reactive.Value so it survives tab
    # switches — _topn_data was a @reactive.calc that was torn down when the
    # comparison DOM was destroyed, forcing all 12 cross-product SQL queries to
    # re-run on every tab return even when nothing had changed.
    _topn_cache: reactive.Value[tuple[tuple, pd.DataFrame]] = reactive.Value(
        ((), pd.DataFrame())
    )

    @reactive.effect
    def _fill_topn_cache() -> None:
        """
        Populate ``_topn_cache`` with top-N responsive ratio data for all active
        (binding, perturbation) pairs.

        Reads all inputs reactively so any change invalidates the effect.  Before
        running queries the inputs are hashed into a cache key; if the key matches
        what is stored the effect exits immediately.  On tab return the key always
        matches (nothing changed), so zero SQL queries run and ``topn_plot`` reads
        the cached DataFrame without waiting.

        :trigger _active_binding_labels: re-runs when binding selection changes.
        :trigger _active_perturbation_labels: re-runs when perturbation changes.
        :trigger dataset_filters: re-runs when filters change.
        :trigger top_n: re-runs when the top-N cutoff changes.
        :trigger effect_threshold: re-runs when the effect threshold changes.
        :trigger pvalue_threshold: re-runs when the p-value threshold changes.

        """
        binding_labels = _active_binding_labels()
        pert_labels = _active_perturbation_labels()
        filters = dataset_filters()
        n = top_n()
        eff = effect_threshold()
        pval = pvalue_threshold()

        key: tuple = (
            tuple(sorted(binding_labels.items())),
            tuple(sorted(pert_labels.items())),
            tuple(sorted((k, str(v)) for k, v in filters.items())),
            n,
            eff,
            pval,
        )
        with reactive.isolate():
            cached_key, _ = _topn_cache.get()
        if key == cached_key:
            logger.debug("comparison _fill_topn_cache: cache hit, skipping queries")
            return

        if not binding_labels or not pert_labels:
            _topn_cache.set((key, pd.DataFrame()))
            return

        _reg_df = get_regulator_display_name(vdb)
        reg_labels: dict[str, str] = dict(
            zip(_reg_df["regulator_locus_tag"], _reg_df["display_name"])
        )

        results: list[pd.DataFrame] = []
        for b_db, b_label in binding_labels.items():
            b_cfg = BINDING_CONFIGS.get(b_db)
            if b_cfg is None:
                logger.warning(f"No binding config for {b_db}, skipping")
                continue
            for p_db, p_label in pert_labels.items():
                p_cfg = PERTURBATION_CONFIGS.get(p_db)
                if p_cfg is None:
                    logger.warning(f"No perturbation config for {p_db}, skipping")
                    continue
                logger.debug(f"Top-{n}: {b_db} x {p_db}")
                try:
                    p_filters = (
                        None if p_cfg.get("hackett_time_filter") else filters.get(p_db)
                    )
                    sql, qparams = topn_responsive_ratio(
                        vdb=vdb,
                        binding_view=b_db,
                        perturbation_view=p_db,
                        top_n=n,
                        effect_threshold=eff,
                        pvalue_threshold=pval,
                        binding_filters=filters.get(b_db),
                        perturbation_filters=p_filters,
                        param_prefix=f"{b_db}_{p_db}",
                        sql_only=True,
                        **b_cfg,
                        **p_cfg,
                    )
                    with profile_span(
                        profile_logger,
                        "vdb.query",
                        module="comparison",
                        dataset=f"{b_db}x{p_db}",
                        context="topn_cache",
                        session_id=session_id,
                    ):
                        result = cached_query(vdb, sql, qparams)
                    assert isinstance(result, pd.DataFrame)
                    result["binding_source"] = b_label
                    result["perturbation_source"] = p_label
                    result["regulator_label"] = (
                        result["regulator_locus_tag"]
                        .map(reg_labels)
                        .fillna(result["regulator_locus_tag"])
                    )
                    results.append(result)
                except Exception as exc:
                    logger.error(
                        f"Top-N failed for {b_db} x {p_db}: {exc}", exc_info=True
                    )

        if not results:
            _topn_cache.set((key, pd.DataFrame()))
            return

        with profile_span(
            profile_logger,
            "df.concat",
            module="comparison",
            context="topn_cache",
            session_id=session_id,
        ):
            out = pd.concat(results, ignore_index=True)
        out["percent_responsive"] = out["responsive_ratio"] * 100
        _topn_cache.set((key, out))

    def _topn_data() -> pd.DataFrame:
        """
        Return the current top-N data from the persistent cache.

        Reads ``_topn_cache`` reactively so callers invalidate when new data
        arrives.  The actual queries run in ``_fill_topn_cache``.

        :returns: DataFrame with columns binding_source, perturbation_source,
            regulator_locus_tag, regulator_label, responsive_ratio,
            percent_responsive.

        """
        return _topn_cache()[1]

    @render.ui
    def topn_plot() -> ui.Tag:
        """
        Boxplot of percent-responsive for top-N binding targets, with individual points
        overlaid. Points show regulator display name on hover. The boxplot itself has no
        tooltip.

        :trigger _topn_cache: re-renders when top-N data changes. :trigger facet_by: re-
        renders when facet orientation changes.

        """
        _render_counts["topn_plot"] += 1
        t0 = time.perf_counter()
        logger.debug(f"RENDER comparison/topn_plot #{_render_counts['topn_plot']}")
        df = _topn_data()
        orientation = facet_by()

        if df.empty:
            logger.debug(
                f"RENDER_DONE comparison/topn_plot #{_render_counts['topn_plot']} "
                f"elapsed={time.perf_counter()-t0:.3f}s (empty)"
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
            logger.debug(
                f"RENDER_DONE comparison/topn_plot #{_render_counts['topn_plot']} "
                f"elapsed={time.perf_counter()-t0:.3f}s (no facets)"
            )
            return ui.div(
                {"class": "empty-state"}, ui.p("No data for selected combination.")
            )

        fig = make_subplots(
            rows=1,
            cols=len(facets),
            subplot_titles=facets,
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
        with profile_span(
            profile_logger,
            "plot.build",
            module="comparison",
            context="topn_plot",
            session_id=session_id,
        ):
            html = to_html(fig, include_plotlyjs=False, full_html=False)
        logger.debug(
            f"RENDER_DONE comparison/topn_plot #{_render_counts['topn_plot']} "
            f"elapsed={time.perf_counter()-t0:.3f}s"
        )
        return ui.HTML(html)


__all__ = ["comparison_workspace_server"]
