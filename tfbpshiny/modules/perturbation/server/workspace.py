"""
Workspace server for the Perturbation analysis page.

Plotly rendering strategy
-------------------------
Plots are rendered as static HTML via ``plotly.io.to_html`` + ``ui.HTML``, using
``@render.ui`` rather than ``render_widget`` / ``output_widget`` from shinywidgets.

Rationale: ``render_widget`` wraps figures as ``FigureWidget`` (an ipywidget), which
maintains a persistent comm channel between the Python server and the browser. When the
user navigates away from this module the DOM is destroyed, tearing down the comm. On
return, shinywidgets tries to re-attach the old comm ID to the new DOM nodes and fails
with a ``t.views is undefined`` / ``[anywidget] Runtime not found`` client error.

Using ``to_html`` produces a self-contained HTML+JS blob that is fully re-rendered by
the browser each time the ``@render.ui`` output updates, with no persistent state. The
resulting Plotly figures are still fully interactive client-side (hover, zoom, pan).

If server-side callbacks on plot events (click, select, hover) are ever needed, this
strategy will need to be revisited. At that point ``render_plotly`` from shinywidgets
should be evaluated, but the navigation/DOM-teardown problem will need to be solved
(e.g. by keeping widget DOM nodes alive via CSS ``display:none`` rather than removing
them, or by using Shiny's ``suspended`` panel pattern).

"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from logging import Logger
from typing import Any, Literal

import pandas as pd
import plotly.graph_objects as go
from plotly.io import to_html
from shiny import module, reactive, render, ui
from tfbpapi import VirtualDB

from tfbpshiny.modules.perturbation.queries import (
    corr_pair_sql,
    get_measurement_column,
    regulator_scatter_sql,
    regulator_symbols_query,
)


@module.server
def perturbation_workspace_server(
    input: Any,
    output: Any,
    session: Any,
    active_perturbation_datasets: reactive.Value[list[str]],
    corr_type: Callable[[], str],
    col_preference: Callable[[], str],
    dataset_filters: reactive.Value[dict[str, Any]],
    vdb: VirtualDB,
    logger: Logger,
) -> None:
    """
    Render the perturbation correlation rows: pairwise distributions
    and per-regulator plots.
    """

    display_names: dict[str, str] = {
        db_name: vdb.get_tags(db_name).get("display_name", db_name)
        for db_name in vdb.get_datasets()
    }

    @reactive.calc
    def _pairs() -> list[tuple[str, str]]:
        active = active_perturbation_datasets()
        return list(itertools.combinations(active, 2))

    @reactive.calc
    def _all_corr_data() -> dict[tuple[str, str], pd.DataFrame]:
        """Compute per-regulator correlations for every active pair."""
        pairs = _pairs()
        # TODO: get rid of the type ignore
        preference: Literal["effect", "pvalue"] = col_preference()  # type: ignore[assignment] # noqa: E501
        method = corr_type()
        filters = dataset_filters()

        if not pairs:
            return {}

        result: dict[tuple[str, str], pd.DataFrame] = {}
        for i, (db_a, db_b) in enumerate(pairs):
            try:
                col_a = get_measurement_column(db_a, preference)
                col_b = get_measurement_column(db_b, preference)
                logger.debug(
                    f"Correlating {db_a}({col_a}) vs {db_b}({col_b}) ({method})"
                )
                result[(db_a, db_b)] = corr_pair_sql(
                    vdb,
                    db_a,
                    col_a,
                    filters.get(db_a),
                    db_b,
                    col_b,
                    filters.get(db_b),
                    method,
                    prefix=f"p{i}_",
                )
            except Exception as exc:
                logger.error(
                    f"Failed to correlate {db_a} vs {db_b}: {exc}", exc_info=True
                )
                result[(db_a, db_b)] = pd.DataFrame(
                    columns=["regulator_locus_tag", "correlation"]
                )

        return result

    @render.ui
    def distributions_plot() -> ui.Tag:
        pairs = _pairs()
        corr_data = _all_corr_data()
        method = corr_type().capitalize()

        fig = go.Figure()

        if not pairs:
            fig.add_annotation(
                text="Select at least two perturbation datasets to see correlations.",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
            )
            return ui.HTML(to_html(fig, include_plotlyjs="cdn", full_html=False))

        for db_a, db_b in pairs:
            df = corr_data.get((db_a, db_b), pd.DataFrame())
            label_a = display_names.get(db_a, db_a)
            label_b = display_names.get(db_b, db_b)
            pair_label = f"{label_a}<br>vs<br>{label_b}"
            vals = (
                df["correlation"].dropna()
                if not df.empty
                else pd.Series([], dtype=float)
            )

            fig.add_trace(
                go.Box(
                    y=vals,
                    name=pair_label,
                    boxpoints="all",
                    jitter=0.4,
                    pointpos=0,
                    marker=dict(size=4, opacity=0.5),
                    line=dict(width=1.5),
                )
            )

        fig.update_layout(
            title=f"{method} correlation across regulators",
            yaxis_title=f"{method} r",
            showlegend=False,
            margin=dict(l=40, r=20, t=50, b=80),
        )
        return ui.HTML(to_html(fig, include_plotlyjs="cdn", full_html=False))

    @render.ui
    def regulator_selector() -> ui.Tag:
        """Regulator selector: union of regulators present in any pair's corr data."""
        corr_data = _all_corr_data()
        if not corr_data:
            return ui.span()

        active = active_perturbation_datasets()
        sym_map: dict[str, str] = {}
        for db in active:
            try:
                sym_df = vdb.query(regulator_symbols_query(db))
                sym_map.update(
                    zip(sym_df["regulator_locus_tag"], sym_df["regulator_symbol"])
                )
                break
            except Exception:
                pass

        all_regs: set[str] = set()
        for df in corr_data.values():
            if not df.empty:
                all_regs |= set(df["regulator_locus_tag"].dropna().unique())

        regs = sorted(all_regs)
        if not regs:
            return ui.span()
        choices = {r: sym_map.get(r, r) or r for r in regs}

        try:
            current = str(input.selected_regulator())
        except Exception:
            current = ""
        default = current if current in choices else regs[0]

        return ui.input_select(
            "selected_regulator",
            "Regulator",
            choices=choices,
            selected=default,
        )

    @render.ui
    def regulator_plots() -> ui.Tag:
        try:
            return _build_regulator_plots()
        except Exception as exc:
            logger.error(f"regulator_plots render failed: {exc}", exc_info=True)
            fig = go.Figure()
            fig.add_annotation(
                text=f"Error rendering plots: {exc}",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
            )
            return ui.HTML(to_html(fig, include_plotlyjs=False, full_html=False))

    def _build_regulator_plots() -> ui.Tag:
        from plotly.subplots import make_subplots

        try:
            reg = str(input.selected_regulator()) or None
        except Exception:
            reg = None
        pairs = list(_all_corr_data().keys())
        # TODO: get rid of the type ignore
        preference: Literal["effect", "pvalue"] = col_preference()  # type: ignore[assignment] # noqa: E501
        filters = dataset_filters()
        method = corr_type()

        fig = go.Figure()

        if not reg or not pairs:
            fig.add_annotation(
                text="Select a regulator above to see per-pair scatter plots.",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
            )
            return ui.HTML(to_html(fig, include_plotlyjs=False, full_html=False))

        n = len(pairs)
        subplot_titles = [
            f"{display_names.get(db_a, db_a)} vs {display_names.get(db_b, db_b)}"
            for db_a, db_b in pairs
        ]
        fig = make_subplots(rows=1, cols=n, subplot_titles=subplot_titles)

        for idx, (db_a, db_b) in enumerate(pairs, start=1):
            try:
                col_a = get_measurement_column(db_a, preference)
                col_b = get_measurement_column(db_b, preference)
                scatter_sql, scatter_params = regulator_scatter_sql(
                    db_a,
                    col_a,
                    filters.get(db_a),
                    db_b,
                    col_b,
                    filters.get(db_b),
                    method,
                    reg,
                    idx,
                )
                merged = vdb.query(scatter_sql, **scatter_params)
            except Exception as exc:
                logger.warning(f"Regulator plot fetch failed for {db_a}/{db_b}: {exc}")
                continue

            if merged.empty:
                continue

            r = merged["_val_a"].corr(merged["_val_b"])
            la = display_names.get(db_a, db_a)
            lb = display_names.get(db_b, db_b)

            fig.add_trace(
                go.Scatter(
                    x=merged["_val_a"],
                    y=merged["_val_b"],
                    mode="markers",
                    marker=dict(size=4, opacity=0.6, color="#4A90D9"),
                    text=merged["target_locus_tag"],
                    hovertemplate=(
                        "%{text}<br>"
                        + f"{la}: %{{x:.3f}}<br>"
                        + f"{lb}: %{{y:.3f}}<extra></extra>"
                    ),
                    name=f"r={r:.3f}",
                    showlegend=False,
                ),
                row=1,
                col=idx,
            )
            fig.update_xaxes(title_text=f"{la}: {col_a}", row=1, col=idx)
            fig.update_yaxes(title_text=f"{lb}: {col_b}", row=1, col=idx)
            fig.layout.annotations[idx - 1].text += f"  (r={r:.3f})"

        fig.update_layout(
            title=f"Regulator: {reg}",
            margin=dict(l=40, r=20, t=70, b=50),
        )
        return ui.HTML(to_html(fig, include_plotlyjs=False, full_html=False))


__all__ = ["perturbation_workspace_server"]
