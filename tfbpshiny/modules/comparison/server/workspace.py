"""Workspace server for the Comparison module."""

from __future__ import annotations

import asyncio
from logging import Logger
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from labretriever import VirtualDB
from plotly.io import to_html
from plotly.subplots import make_subplots
from shiny import reactive, render, req, ui
from shiny.reactive import extended_task
from shiny.ui import bind_task_button, input_task_button  # noqa: F401

from tfbpshiny.modules.comparison.queries import (
    BINDING_BASE_LABEL_MAP,
    BINDING_CONFIGS,
    BINDING_LABEL_MAP,
    METHOD_BASE_LABEL_MAP,
    PEAKS_VARIANT_MAP,
    PERTURBATION_CONFIGS,
    PERTURBATION_LABEL_MAP,
    PROMOTER_SET_MAP,
    PROMOTER_VARIANT_PAIRS,
    SCORING_VARIANT_COLORS,
    SCORING_VARIANT_MAP,
    SCORING_VARIANT_ORDER,
    topn_all_pairs_sql,
)
from tfbpshiny.utils.perf import reset_render_counts
from tfbpshiny.utils.vdb_init import get_regulator_display_name

# ---------------------------------------------------------------------------
# Color palettes
# ---------------------------------------------------------------------------

PROMOTER_SET_COLORS: dict[str, str] = {
    "Kang": "#4DBBD5",
    "Mindel": "#E64B35",
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

#: All db_names that can appear in the Method Comparison tab.
_METHOD_BASE_DATASETS: frozenset[str] = frozenset(METHOD_BASE_LABEL_MAP)


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
    """Render the Comparison workspace: Top-N and Promoter Set views."""

    session.on_flush(lambda: reset_render_counts(session.id))

    # All datasets registered in this VirtualDB instance — checked once at init.
    _available_datasets: frozenset[str] = frozenset(vdb.get_datasets())

    # Mindel db_names that actually exist in this instance.
    _mindel_dbs: frozenset[str] = (
        frozenset(PROMOTER_VARIANT_PAIRS.values()) & _available_datasets
    )

    # Snapshot of sidebar inputs at the time of the last Execute click.
    _last_run_snapshot: reactive.Value[tuple | None] = reactive.value(None)

    def _snapshot_current() -> tuple:
        """Return a hashable representation of the current sidebar inputs."""
        try:
            incl_b: tuple = tuple(sorted(input.included_binding() or ()))
        except Exception:
            incl_b = ()
        try:
            incl_p: tuple = tuple(sorted(input.included_perturbation() or ()))
        except Exception:
            incl_p = ()
        try:
            incl_ps: tuple = tuple(sorted(input.included_promoter_sets() or ()))
        except Exception:
            incl_ps = ()
        try:
            filters_repr = repr(
                sorted((k, repr(v)) for k, v in dataset_filters().items())
            )
        except Exception:
            filters_repr = ""
        return (
            incl_b,
            incl_p,
            incl_ps,
            input.top_n(),
            input.effect_threshold(),
            input.pvalue_threshold(),
            filters_repr,
        )

    @render.ui
    def execute_pending_style() -> ui.Tag:
        """
        Inject a ``<style>`` tag that dims the Execute Analysis button when no changes
        are pending since the last run.

        :trigger input.included_binding: re-fires when binding selection changes.
        :trigger input.included_perturbation: re-fires when perturbation selection
        changes. :trigger input.included_promoter_sets: re-fires when promoter sets
        change. :trigger input.top_n: re-fires when Top N changes. :trigger
        input.effect_threshold: re-fires when effect threshold changes. :trigger
        input.pvalue_threshold: re-fires when p-value threshold changes. :trigger
        _last_run_snapshot: re-fires after Execute to reset the indicator. :trigger
        dataset_filters: re-fires when filters change.

        """
        current = _snapshot_current()
        last = _last_run_snapshot()
        has_pending = (last is None) or (current != last)
        if has_pending:
            return ui.span()
        btn_id = session.ns("execute_analysis")
        return ui.tags.style(f"#{btn_id} {{ opacity: 0.35; }}")

    # --- Dataset selection sidebar renders ------------------------------------

    @reactive.effect
    def _gate_tab() -> None:
        """Silently block when another tab is active."""
        if active_tab is not None:
            req(active_tab() == "Comparison")

    @render.ui
    def binding_selection() -> ui.Tag:
        """
        Checkbox group for primary binding datasets (Mindel variants excluded; those are
        controlled by the Promoter Sets checkbox).

        :trigger active_binding_datasets: re-renders when binding selection changes.

        """
        primary_dbs = [
            db
            for db in active_binding_datasets()
            if db not in _mindel_dbs and BINDING_CONFIGS.get(db) is not None
        ]
        if not primary_dbs:
            return ui.span()
        return ui.input_checkbox_group(
            "included_binding",
            label=None,
            choices={db: BINDING_LABEL_MAP.get(db, db) for db in primary_dbs},
            selected=primary_dbs,
        )

    @render.ui
    def perturbation_selection() -> ui.Tag:
        """
        Checkbox group for active perturbation datasets.

        :trigger active_perturbation_datasets: re-renders when perturbation selection
        changes.

        """
        pert_dbs = [
            db
            for db in active_perturbation_datasets()
            if PERTURBATION_CONFIGS.get(db) is not None
        ]
        if not pert_dbs:
            return ui.span()
        return ui.input_checkbox_group(
            "included_perturbation",
            label=None,
            choices={db: PERTURBATION_LABEL_MAP.get(db, db) for db in pert_dbs},
            selected=pert_dbs,
        )

    # --- Execute Analysis task -----------------------------------------------

    @bind_task_button(button_id="execute_analysis")
    @extended_task
    async def _run_analysis(
        expanded_binding: list[str],
        peaks_binding: list[str],
        included_perturbation: list[str],
        included_binding_primary: list[str],
        included_promoter_sets: list[str],
        top_n: int,
        effect_threshold: float,
        pvalue_threshold: float,
        filters: dict,
    ) -> dict:
        """
        Compute top-N responsive ratios for all (binding, perturbation) pairs, derive
        the promoter-set comparison table, and compute method-comparison data for peaks-
        variant datasets, all off the main thread.

        The two SQL queries (promoter-set and method-comparison) run concurrently
        via ``asyncio.gather`` when DuckDB supports parallel reads.

        :param expanded_binding: All binding db_names to query (primary + Mindel
            variants as selected via promoter sets).
        :param peaks_binding: Peaks-variant db_names auto-derived from the
            selected primary binding datasets.
        :param included_perturbation: Perturbation db_names to query.
        :param included_binding_primary: Primary binding db_names only (used to
            derive the promoter comparison table).
        :param included_promoter_sets: Labels of selected promoter sets, e.g.
            ``["Kang", "Mindel"]``.
        :param top_n: Top-N binding targets per binding sample.
        :param effect_threshold: Minimum absolute effect size for responsiveness.
        :param pvalue_threshold: Maximum p-value for responsiveness.
        :param filters: Active dataset filters keyed by db_name.
        :returns: Dict with keys ``topn_data``, ``promoter_table_data``,
            ``method_data``, ``included_binding_primary``,
            ``included_perturbation``, ``included_promoter_sets``.

        """
        topn_pairs = [
            (b_db, p_db)
            for b_db in expanded_binding
            if BINDING_CONFIGS.get(b_db) is not None
            for p_db in included_perturbation
            if PERTURBATION_CONFIGS.get(p_db) is not None
        ]

        # Method comparison includes primary + Mindel variants already in
        # expanded_binding that belong to METHOD_BASE_LABEL_MAP, plus peaks.
        method_dbs = [
            b
            for b in (expanded_binding + peaks_binding)
            if METHOD_BASE_LABEL_MAP.get(b) and BINDING_CONFIGS.get(b)
        ]
        method_pairs = [
            (b_db, p_db)
            for b_db in method_dbs
            for p_db in included_perturbation
            if PERTURBATION_CONFIGS.get(p_db) is not None
        ]

        empty_result = {
            "topn_data": pd.DataFrame(),
            "promoter_table_data": {},
            "method_data": pd.DataFrame(),
            "included_binding_primary": included_binding_primary,
            "included_perturbation": included_perturbation,
            "included_promoter_sets": included_promoter_sets,
        }

        if not topn_pairs and not method_pairs:
            return empty_result

        _reg_df = get_regulator_display_name(vdb)
        reg_labels: dict[str, str] = dict(
            zip(_reg_df["regulator_locus_tag"], _reg_df["display_name"])
        )

        # Run both queries concurrently; DuckDB supports parallel reads in
        # read-only mode.  asyncio.gather serializes them safely if it cannot.
        combined_res: pd.DataFrame | BaseException
        method_res: pd.DataFrame | BaseException
        combined_res, method_res = await asyncio.gather(
            (
                asyncio.to_thread(
                    topn_all_pairs_sql,
                    vdb,
                    topn_pairs,
                    filters,
                    top_n,
                    effect_threshold,
                    pvalue_threshold,
                )
                if topn_pairs
                else asyncio.to_thread(lambda: pd.DataFrame())
            ),
            (
                asyncio.to_thread(
                    topn_all_pairs_sql,
                    vdb,
                    method_pairs,
                    filters,
                    top_n,
                    effect_threshold,
                    pvalue_threshold,
                )
                if method_pairs
                else asyncio.to_thread(lambda: pd.DataFrame())
            ),
            return_exceptions=True,
        )

        if isinstance(combined_res, Exception):
            logger.error("topn_all_pairs_sql failed: %s", combined_res, exc_info=True)
            combined_res = pd.DataFrame()
        if isinstance(method_res, Exception):
            logger.error(
                "method topn_all_pairs_sql failed: %s", method_res, exc_info=True
            )
            method_res = pd.DataFrame()

        combined: pd.DataFrame = combined_res  # type: ignore[assignment]
        method_combined: pd.DataFrame = method_res  # type: ignore[assignment]

        # Build topn_data with promoter-set columns.
        topn_data = pd.DataFrame()
        if not combined.empty and "pair_key" in combined.columns:
            results: list[pd.DataFrame] = []
            for b_db in expanded_binding:
                for p_db in included_perturbation:
                    pair_key = f"{b_db}__{p_db}"
                    subset = (
                        combined[combined["pair_key"] == pair_key]
                        .drop(columns=["pair_key"])
                        .reset_index(drop=True)
                        .copy()
                    )
                    if subset.empty:
                        continue
                    subset["binding_base_label"] = BINDING_BASE_LABEL_MAP.get(
                        b_db, b_db
                    )
                    subset["promoter_set"] = PROMOTER_SET_MAP.get(b_db, "Kang")
                    subset["perturbation_source"] = PERTURBATION_LABEL_MAP.get(
                        p_db, p_db
                    )
                    subset["regulator_label"] = (
                        subset["regulator_locus_tag"]
                        .map(reg_labels)
                        .fillna(subset["regulator_locus_tag"])
                    )
                    results.append(subset)
            if results:
                topn_data = pd.concat(results, ignore_index=True)
                topn_data["percent_responsive"] = topn_data["responsive_ratio"] * 100

        # Derive promoter comparison table from topn_data.
        promoter_table_data: dict[str, pd.DataFrame] = {}
        if not topn_data.empty:
            if "Kang" in included_promoter_sets and "Mindel" in included_promoter_sets:
                for primary_db in included_binding_primary:
                    mindel_db = PROMOTER_VARIANT_PAIRS.get(primary_db)
                    if mindel_db is None:
                        continue
                    base_label = BINDING_BASE_LABEL_MAP.get(primary_db, primary_db)
                    sub_b = topn_data[topn_data["binding_base_label"] == base_label]
                    if sub_b.empty:
                        continue
                    rows: dict[str, dict[str, float]] = {}
                    for p_db in included_perturbation:
                        p_label = PERTURBATION_LABEL_MAP.get(p_db, p_db)
                        sub_p = sub_b[sub_b["perturbation_source"] == p_label]
                        if sub_p.empty:
                            continue
                        row: dict[str, float] = {}
                        for ps_label in ("Kang", "Mindel"):
                            sub_ps = sub_p[sub_p["promoter_set"] == ps_label]
                            if sub_ps.empty:
                                continue
                            per_reg = sub_ps.groupby("regulator_locus_tag")[
                                "percent_responsive"
                            ].median()
                            row[ps_label] = float(per_reg.median())
                        if row:
                            rows[p_label] = row
                    if rows:
                        df_t = pd.DataFrame(rows).T.reindex(columns=["Kang", "Mindel"])
                        df_t.index.name = "Perturbation"
                        promoter_table_data[primary_db] = df_t

        # Build method_data with scoring-variant columns.
        method_data = pd.DataFrame()
        if not method_combined.empty and "pair_key" in method_combined.columns:
            method_results: list[pd.DataFrame] = []
            for b_db in method_dbs:
                for p_db in included_perturbation:
                    pair_key = f"{b_db}__{p_db}"
                    subset = (
                        method_combined[method_combined["pair_key"] == pair_key]
                        .drop(columns=["pair_key"])
                        .reset_index(drop=True)
                        .copy()
                    )
                    if subset.empty:
                        continue
                    subset["method_base_label"] = METHOD_BASE_LABEL_MAP.get(b_db, b_db)
                    subset["scoring_variant"] = SCORING_VARIANT_MAP.get(b_db, b_db)
                    subset["perturbation_source"] = PERTURBATION_LABEL_MAP.get(
                        p_db, p_db
                    )
                    subset["regulator_label"] = (
                        subset["regulator_locus_tag"]
                        .map(reg_labels)
                        .fillna(subset["regulator_locus_tag"])
                    )
                    method_results.append(subset)
            if method_results:
                method_data = pd.concat(method_results, ignore_index=True)
                method_data["percent_responsive"] = (
                    method_data["responsive_ratio"] * 100
                )

        return {
            "topn_data": topn_data,
            "promoter_table_data": promoter_table_data,
            "method_data": method_data,
            "included_binding_primary": included_binding_primary,
            "included_perturbation": included_perturbation,
            "included_promoter_sets": included_promoter_sets,
        }

    @reactive.effect
    @reactive.event(input.execute_analysis)
    def _on_execute() -> None:
        """
        Read current sidebar state and invoke the analysis task.

        :trigger input.execute_analysis: fires when Execute Analysis is clicked.

        """
        # Primary binding datasets currently active (Mindel variants excluded
        # from the selector; they are added below based on promoter-set choice).
        all_primary = [
            db
            for db in active_binding_datasets()
            if db not in _mindel_dbs and BINDING_CONFIGS.get(db) is not None
        ]
        try:
            included_binding_primary = [
                db for db in all_primary if db in set(input.included_binding())
            ]
        except Exception:
            included_binding_primary = all_primary

        all_pert = [
            db
            for db in active_perturbation_datasets()
            if PERTURBATION_CONFIGS.get(db) is not None
        ]
        try:
            included_perturbation = [
                db for db in all_pert if db in set(input.included_perturbation())
            ]
        except Exception:
            included_perturbation = all_pert

        try:
            included_promoter_sets = list(input.included_promoter_sets())
        except Exception:
            included_promoter_sets = ["Kang", "Mindel"]

        # Expand primary binding to Mindel variants when requested.
        expanded_binding: list[str] = []
        for b_db in included_binding_primary:
            if "Kang" in included_promoter_sets:
                expanded_binding.append(b_db)
            if "Mindel" in included_promoter_sets:
                mindel_db = PROMOTER_VARIANT_PAIRS.get(b_db)
                if mindel_db and mindel_db in _available_datasets:
                    expanded_binding.append(mindel_db)

        # Auto-derive peaks variants for the Method Comparison tab.  No sidebar
        # toggle needed; peaks are always included for eligible primary datasets.
        peaks_binding: list[str] = [
            pk_db
            for b_db in included_binding_primary
            for pk_db in PEAKS_VARIANT_MAP.get(b_db, [])
            if pk_db in _available_datasets
        ]

        _run_analysis.invoke(
            expanded_binding,
            peaks_binding,
            included_perturbation,
            included_binding_primary,
            included_promoter_sets,
            input.top_n(),
            input.effect_threshold(),
            input.pvalue_threshold(),
            dataset_filters(),
        )
        # Capture snapshot so _update_pending_indicator dims the button.
        _last_run_snapshot.set(_snapshot_current())

    # --- Status render --------------------------------------------------------

    @render.ui
    def analysis_status() -> ui.Tag:
        """
        User feedback while the task is running or has errored.

        :trigger _run_analysis.status: re-renders when the task state changes.

        """
        status = _run_analysis.status()
        if status == "running":
            return ui.div(
                {"class": "empty-state"},
                ui.p(
                    "Computing correlations. This typically takes less than 5 seconds."
                    " Thank you for your patience."
                ),
            )
        if status == "error":
            return ui.div(
                {"class": "empty-state"},
                ui.p(f"Error: {_run_analysis.error()}"),
            )
        return ui.span()

    # --- Distributions tab controls -------------------------------------------

    @render.ui
    def facet_by_selector() -> ui.Tag:
        """
        Inline radio-button control for choosing the facet axis.

        Rendered inside the Distributions tab (not the sidebar) because changing the
        facet orientation only affects the visualisation, not the underlying data, so it
        does not require re-running Execute Analysis.

        Appears only after analysis has completed successfully.

        :trigger _run_analysis.status: re-renders when the task completes.

        """
        if _run_analysis.status() != "success":
            return ui.span()
        return ui.input_radio_buttons(
            "facet_by",
            "Facet by",
            choices={
                "binding": "Binding source",
                "perturbation": "Perturbation source",
            },
            selected="binding",
            inline=True,
        )

    # --- Top-N box-plot render ------------------------------------------------

    @render.ui
    def topn_plot() -> ui.Tag:
        """
        Boxplot of percent-responsive, faceted by binding or perturbation source, with
        one box per promoter set (Kang/Mindel) at each x position.

        Facet orientation is reactive (``input.facet_by``); all data comes from the
        frozen task result so changing orientation does not re-run any queries.

        :trigger _run_analysis.status: re-renders when the task completes.
        :trigger input.facet_by: re-renders when the facet orientation changes.

        """
        status = _run_analysis.status()
        if status != "success":
            if status == "initial":
                return ui.div(
                    {"class": "empty-state"},
                    ui.p("Click Execute Analysis to compute."),
                )
            return ui.span()

        result = _run_analysis.result()
        df: pd.DataFrame = result["topn_data"]
        included_promoter_sets: list[str] = result["included_promoter_sets"]
        orientation = input.facet_by()

        if df.empty:
            return ui.div(
                {"class": "empty-state"},
                ui.p("No top-N data available for the selected datasets."),
            )

        if orientation == "binding":
            facet_col = "binding_base_label"
            x_col = "perturbation_source"
            facet_order = _BINDING_ORDER
            x_order = _PERT_ORDER
        else:
            facet_col = "perturbation_source"
            x_col = "binding_base_label"
            facet_order = _PERT_ORDER
            x_order = _BINDING_ORDER

        facets = [f for f in facet_order if f in df[facet_col].unique()]
        xs = [x for x in x_order if x in df[x_col].unique()]

        if not facets or not xs:
            return ui.div(
                {"class": "empty-state"},
                ui.p("No data for the selected combination."),
            )

        fig = make_subplots(
            rows=1,
            cols=len(facets),
            subplot_titles=facets,
            shared_yaxes=True,
        )

        # Track which promoter-set labels have appeared in the legend so each
        # gets exactly one entry on its first occurrence across all subplots.
        # Cannot rely on col_idx == 1 because the first subplot may lack data
        # for a given promoter set (e.g., Harbison has no Mindel variant).
        _legend_shown: set[str] = set()

        for col_idx, facet_val in enumerate(facets, start=1):
            sub = df[df[facet_col] == facet_val]
            for ps_label in included_promoter_sets:
                color = PROMOTER_SET_COLORS.get(ps_label, "#888888")
                sub_ps = sub[sub["promoter_set"] == ps_label]
                if sub_ps.empty:
                    continue
                mask = sub_ps["percent_responsive"].notna()
                vals = sub_ps.loc[mask, "percent_responsive"]
                x_vals = sub_ps.loc[mask, x_col]
                reg_col = sub_ps.loc[mask, "regulator_label"]

                show = ps_label not in _legend_shown
                _legend_shown.add(ps_label)

                fig.add_trace(
                    go.Box(
                        x=x_vals.values,
                        y=vals.values,
                        name=ps_label,
                        marker_color=color,
                        boxpoints="all",
                        jitter=0.4,
                        pointpos=0,
                        marker=dict(size=4, opacity=0.5),
                        line=dict(width=1.2),
                        legendgroup=ps_label,
                        showlegend=show,
                        hoveron="points",
                        text=reg_col.values,
                        hovertemplate="%{text}<br>%{y:.1f}%<extra></extra>",
                    ),
                    row=1,
                    col=col_idx,
                )

            fig.update_xaxes(
                categoryorder="array",
                categoryarray=xs,
                row=1,
                col=col_idx,
                tickangle=30,
            )

        fig.update_yaxes(
            title_text="% responsive in top N", range=[0, 100], row=1, col=1
        )
        fig.update_layout(
            legend_title="Promoter set",
            boxmode="group",
            margin=dict(l=50, r=20, t=80, b=80),
        )
        return ui.HTML(to_html(fig, include_plotlyjs=False, full_html=False))

    # --- Promoter set comparison table render ---------------------------------

    @render.ui
    def promoter_comparison() -> ui.Tag:
        """
        Summary tables comparing Kang vs Mindel promoter annotations.

        One table per active primary binding dataset that has a Mindel variant. Only
        rendered when both Kang and Mindel were selected for the last run.

        :trigger _run_analysis.status: re-renders when the task completes.

        """
        status = _run_analysis.status()
        if status != "success":
            if status == "initial":
                return ui.div(
                    {"class": "empty-state"},
                    ui.p("Click Execute Analysis to compute."),
                )
            return ui.span()

        result = _run_analysis.result()
        tables_data: dict[str, pd.DataFrame] = result["promoter_table_data"]
        included_promoter_sets: list[str] = result["included_promoter_sets"]

        if not tables_data:
            if (
                "Kang" not in included_promoter_sets
                or "Mindel" not in included_promoter_sets
            ):
                return ui.div(
                    {"class": "empty-state"},
                    ui.p(
                        "Select both Kang and Mindel promoter sets to see the"
                        " comparison table."
                    ),
                )
            return ui.div(
                {"class": "empty-state"},
                ui.p("No promoter-set comparison available for the selected datasets."),
            )

        def _cell_style(val: float) -> str:
            """HSL green scale: 0 % -> white, 100 % -> full green."""
            clamped = max(0.0, min(100.0, val))
            lightness = 100 - clamped * 0.5
            return (
                f"background-color: hsl(120, 60%, {lightness:.0f}%);"
                " padding: 6px 10px; text-align: right;"
            )

        _th_style = "padding: 6px 10px; text-align: right;"
        _header = ui.tags.tr(
            ui.tags.th("Perturbation", style="padding: 6px 10px; text-align: left;"),
            ui.tags.th("Kang", style=_th_style),
            ui.tags.th("Mindel", style=_th_style),
        )

        table_tags: list[ui.Tag] = []
        for primary_db, df_t in tables_data.items():
            data_rows: list[ui.Tag] = []
            for pert_label, row in df_t.iterrows():
                kang_val = row.get("Kang")
                mindel_val = row.get("Mindel")
                data_rows.append(
                    ui.tags.tr(
                        ui.tags.td(
                            str(pert_label),
                            style=(
                                "padding: 6px 10px;"
                                " text-align: left; white-space: nowrap;"
                            ),
                        ),
                        ui.tags.td(
                            (
                                f"{kang_val:.1f}%"
                                if kang_val is not None and not pd.isna(kang_val)
                                else "-"
                            ),
                            style=(
                                _cell_style(kang_val)
                                if kang_val is not None and not pd.isna(kang_val)
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
                        BINDING_BASE_LABEL_MAP.get(primary_db, primary_db),
                    ),
                    ui.tags.table(
                        {
                            "style": (
                                "border-collapse: collapse; font-size: 0.9rem;"
                                " width: 100%;"
                            )
                        },
                        ui.tags.thead({"style": "background-color: #f5f5f5;"}, _header),
                        ui.tags.tbody(*data_rows),
                    ),
                )
            )

        return ui.div(
            {
                "style": (
                    "display: flex; flex-wrap: wrap; gap: 1.5rem; margin-top: 0.5rem;"
                )
            },
            *table_tags,
        )

    # --- Method Comparison tab controls ----------------------------------------

    @render.ui
    def method_facet_by_selector() -> ui.Tag:
        """
        Inline radio-button control for choosing the facet axis in the Method Comparison
        tab.

        Appears only after analysis has completed successfully.

        :trigger _run_analysis.status: re-renders when the task completes.

        """
        if _run_analysis.status() != "success":
            return ui.span()
        result = _run_analysis.result()
        if result["method_data"].empty:
            return ui.span()
        return ui.input_radio_buttons(
            "method_facet_by",
            "Facet by",
            choices={
                "binding": "Binding source",
                "perturbation": "Perturbation source",
            },
            selected="binding",
            inline=True,
        )

    # --- Method Comparison box-plot render ------------------------------------

    @render.ui
    def method_comparison() -> ui.Tag:
        """
        Boxplots comparing percent-responsive across scoring variants for each base
        dataset that has a peaks counterpart.

        Facets by ``method_base_label``; boxes within each facet are grouped by
        ``scoring_variant``.  Facet orientation is controlled by
        ``input.method_facet_by`` and does not require re-running the analysis.

        :trigger _run_analysis.status: re-renders when the task completes.
        :trigger input.method_facet_by: re-renders when the facet axis changes.

        """
        status = _run_analysis.status()
        if status != "success":
            if status == "initial":
                return ui.div(
                    {"class": "empty-state"},
                    ui.p("Click Execute Analysis to compute."),
                )
            return ui.span()

        result = _run_analysis.result()
        df: pd.DataFrame = result["method_data"]

        if df.empty:
            return ui.div(
                {"class": "empty-state"},
                ui.p(
                    "No method-comparison data for the selected datasets. "
                    "Select Rossi 2021 ChIP-exo or Mahendrawada 2025 ChEC-seq "
                    "to see scoring-variant comparisons."
                ),
            )

        orientation = input.method_facet_by()
        if orientation == "binding":
            facet_col, x_col = "method_base_label", "perturbation_source"
            facet_order = _BINDING_ORDER
            x_order = _PERT_ORDER
        else:
            facet_col, x_col = "perturbation_source", "method_base_label"
            facet_order = _PERT_ORDER
            x_order = _BINDING_ORDER

        facets = [f for f in facet_order if f in df[facet_col].unique()]
        xs = [x for x in x_order if x in df[x_col].unique()]

        if not facets or not xs:
            return ui.div(
                {"class": "empty-state"},
                ui.p("No data for the selected combination."),
            )

        # Scoring variants present in the data, in display order.
        variants_present = [
            v for v in SCORING_VARIANT_ORDER if v in df["scoring_variant"].unique()
        ]

        fig = make_subplots(
            rows=1,
            cols=len(facets),
            subplot_titles=facets,
            shared_yaxes=True,
        )

        _legend_shown: set[str] = set()

        for col_idx, facet_val in enumerate(facets, start=1):
            sub = df[df[facet_col] == facet_val]
            for variant in variants_present:
                color = SCORING_VARIANT_COLORS.get(variant, "#888888")
                sub_v = sub[sub["scoring_variant"] == variant]
                if sub_v.empty:
                    continue
                mask = sub_v["percent_responsive"].notna()
                vals = sub_v.loc[mask, "percent_responsive"]
                x_vals = sub_v.loc[mask, x_col]
                reg_col = sub_v.loc[mask, "regulator_label"]

                show = variant not in _legend_shown
                _legend_shown.add(variant)

                fig.add_trace(
                    go.Box(
                        x=x_vals.values,
                        y=vals.values,
                        name=variant,
                        marker_color=color,
                        boxpoints="all",
                        jitter=0.4,
                        pointpos=0,
                        marker=dict(size=4, opacity=0.5),
                        line=dict(width=1.2),
                        legendgroup=variant,
                        showlegend=show,
                        hoveron="points",
                        text=reg_col.values,
                        hovertemplate="%{text}<br>%{y:.1f}%<extra></extra>",
                    ),
                    row=1,
                    col=col_idx,
                )

            fig.update_xaxes(
                categoryorder="array",
                categoryarray=xs,
                row=1,
                col=col_idx,
                tickangle=30,
            )

        fig.update_yaxes(
            title_text="% responsive in top N", range=[0, 100], row=1, col=1
        )
        fig.update_layout(
            legend_title="Scoring variant",
            boxmode="group",
            margin=dict(l=50, r=20, t=80, b=80),
        )
        return ui.HTML(to_html(fig, include_plotlyjs=False, full_html=False))


__all__ = ["comparison_workspace_server"]
