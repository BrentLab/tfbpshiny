"""Workspace server for the Binding analysis page."""

from __future__ import annotations

import itertools
from logging import Logger
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from shiny import module, reactive, render, ui
from shinywidgets import render_widget
from tfbpapi import VirtualDB


def _fetch_dataset(
    vdb: VirtualDB,
    db_name: str,
    col: str,
    filters: dict[str, Any] | None,
    prefix: str,
) -> pd.DataFrame:
    """
    Fetch ``regulator_locus_tag``, ``target_locus_tag``, and ``col`` for a dataset.

    :param prefix: Parameter namespace prefix to avoid collisions across datasets.

    """
    params: dict[str, Any] = {}
    where = _build_where_with_params(filters, params, prefix=prefix)
    return vdb.query(
        f"SELECT regulator_locus_tag, target_locus_tag, {col} "
        f"FROM {db_name}{where}",
        **params,
    )


def _correlate_pair(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    col: str,
    method: str,
) -> pd.DataFrame:
    """
    Compute per-regulator correlation between two datasets sharing ``col``.

    Joins on ``(regulator_locus_tag, target_locus_tag)``, computes ``method``
    correlation per ``regulator_locus_tag``.

    :return: DataFrame with columns ``regulator_locus_tag`` and ``correlation``.

    """
    col_a = col + "_a"
    col_b = col + "_b"
    merged = pd.merge(
        df_a[["regulator_locus_tag", "target_locus_tag", col]].rename(
            columns={col: col_a}
        ),
        df_b[["regulator_locus_tag", "target_locus_tag", col]].rename(
            columns={col: col_b}
        ),
        on=["regulator_locus_tag", "target_locus_tag"],
        how="inner",
    )
    if merged.empty:
        return pd.DataFrame(columns=["regulator_locus_tag", "correlation"])

    records = []
    for reg, grp in merged.groupby("regulator_locus_tag"):
        if len(grp) < 3:
            continue
        corr = grp[col_a].corr(grp[col_b], method=method)
        records.append({"regulator_locus_tag": reg, "correlation": corr})

    return pd.DataFrame(records)


@module.server
def binding_workspace_server(
    input: Any,
    output: Any,
    session: Any,
    active_binding_datasets: reactive.calc,
    corr_type: reactive.calc,
    column: reactive.calc,
    dataset_filters: reactive.Value[dict[str, Any]],
    vdb: VirtualDB,
    logger: Logger,
) -> None:
    """
    Render the binding correlation rows: pairwise distributions
    and per-regulator plots.
    """

    display_names: dict[str, str] = {
        db_name: vdb.get_tags(db_name).get("display_name", db_name)
        for db_name in vdb.get_datasets()
    }

    @reactive.calc
    def _pairs() -> list[tuple[str, str]]:
        active = active_binding_datasets()
        return list(itertools.combinations(active, 2))

    @reactive.calc
    def _all_corr_data() -> dict[tuple[str, str], pd.DataFrame]:
        """Compute per-regulator correlations for every active pair."""
        pairs = _pairs()
        col = column()
        method = corr_type()
        filters = dataset_filters()

        if not pairs or col is None:
            return {}

        # fetch each active dataset once
        active = active_binding_datasets()
        dfs: dict[str, pd.DataFrame] = {}
        for i, db in enumerate(active):
            try:
                dfs[db] = _fetch_dataset(vdb, db, col, filters.get(db), prefix=str(i))
            except Exception as exc:
                logger.warning(f"Failed to fetch {db}: {exc}")
                dfs[db] = pd.DataFrame(
                    columns=["regulator_locus_tag", "target_locus_tag", col]
                )

        result: dict[tuple[str, str], pd.DataFrame] = {}
        for db_a, db_b in pairs:
            logger.debug(f"Correlating {db_a} vs {db_b} ({method}, col={col})")
            result[(db_a, db_b)] = _correlate_pair(dfs[db_a], dfs[db_b], col, method)

        return result

    @render_widget
    def distributions_plot() -> go.Figure:
        pairs = _pairs()
        corr_data = _all_corr_data()
        col = column()
        method = corr_type().capitalize()

        fig = go.Figure()

        if not pairs or col is None:
            fig.add_annotation(
                text="Select at least two binding datasets to see correlations.",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
            )
            return fig

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

            # boxplot
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
        return fig

    @render.ui
    def regulator_selector() -> ui.Tag:
        """Regulator selector: union of regulators present in any pair's corr data."""
        corr_data = _all_corr_data()
        if not corr_data:
            return ui.span()

        # build symbol map from first available dataset
        active = active_binding_datasets()
        sym_map: dict[str, str] = {}
        for db in active:
            try:
                sym_df = vdb.query(
                    f"SELECT DISTINCT regulator_locus_tag, regulator_symbol "
                    f"FROM {db}_meta WHERE regulator_locus_tag IS NOT NULL"
                )
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

    @render_widget
    def regulator_plots() -> go.Figure:
        try:
            reg = str(input.selected_regulator()) or None
        except Exception:
            reg = None
        pairs = _pairs()
        col = column()

        n = len(pairs)
        fig = go.Figure()

        if not reg or not pairs or col is None:
            fig.add_annotation(
                text="Select a regulator above to see per-pair scatter plots.",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
            )
            return fig

        # build subplots: one column per pair
        from plotly.subplots import make_subplots

        subplot_titles = []
        for db_a, db_b in pairs:
            la = display_names.get(db_a, db_a)
            lb = display_names.get(db_b, db_b)
            subplot_titles.append(f"{la} vs {lb}")

        fig = make_subplots(rows=1, cols=n, subplot_titles=subplot_titles)

        filters = dataset_filters()
        method = corr_type()

        for idx, (db_a, db_b) in enumerate(pairs, start=1):
            col_label = col
            # fetch per-regulator data
            try:
                params_a: dict[str, Any] = {}
                where_a = _build_where_with_params(
                    filters.get(db_a), params_a, prefix=f"ra{idx}"
                )
                df_a = vdb.query(
                    f"SELECT target_locus_tag, {col} FROM {db_a}{where_a}"
                    + (" AND " if where_a else " WHERE ")
                    + "regulator_locus_tag = $reg",
                    **params_a,
                    reg=reg,
                )
                params_b: dict[str, Any] = {}
                where_b = _build_where_with_params(
                    filters.get(db_b), params_b, prefix=f"rb{idx}"
                )
                df_b = vdb.query(
                    f"SELECT target_locus_tag, {col} FROM {db_b}{where_b}"
                    + (" AND " if where_b else " WHERE ")
                    + "regulator_locus_tag = $reg",
                    **params_b,
                    reg=reg,
                )
            except Exception as exc:
                logger.warning(f"Regulator plot fetch failed for {db_a}/{db_b}: {exc}")
                continue

            merged = pd.merge(
                df_a.rename(columns={col: col + "_a"}),
                df_b.rename(columns={col: col + "_b"}),
                on="target_locus_tag",
                how="inner",
            )
            if merged.empty:
                continue

            r = merged[col + "_a"].corr(merged[col + "_b"], method=method)
            la = display_names.get(db_a, db_a)
            lb = display_names.get(db_b, db_b)

            fig.add_trace(
                go.Scatter(
                    x=merged[col + "_a"],
                    y=merged[col + "_b"],
                    mode="markers",
                    marker=dict(size=4, opacity=0.6, color="#4A90D9"),
                    text=merged["target_locus_tag"],
                    hovertemplate=(
                        "%{text}<br>"
                        + f"{la}: "
                        + "%{x:.3f}<br>"
                        + f"{lb}: "
                        + "%{y:.3f}<extra></extra>"
                    ),
                    name=f"r={r:.3f}",
                    showlegend=False,
                ),
                row=1,
                col=idx,
            )
            fig.update_xaxes(title_text=f"{la}: {col_label}", row=1, col=idx)
            fig.update_yaxes(title_text=f"{lb}: {col_label}", row=1, col=idx)
            fig.layout.annotations[idx - 1].text += f"  (r={r:.3f})"

        fig.update_layout(
            title=f"Regulator: {reg}",
            margin=dict(l=40, r=20, t=70, b=50),
        )
        return fig


def _build_where_with_params(
    filters: dict[str, Any] | None,
    params: dict[str, Any],
    prefix: str = "",
) -> str:
    """
    Build a WHERE clause string and populate ``params`` in-place.

    Uses a ``prefix`` to namespace parameter names so multiple datasets' params
    can coexist in the same call.

    """
    if not filters:
        return ""
    clauses: list[str] = []
    for field, spec in filters.items():
        kind = spec["type"]
        val = spec["value"]
        p = f"{prefix}_{field}" if prefix else field
        if kind == "categorical":
            placeholders = ", ".join(f"$cat_{p}_{i}" for i in range(len(val)))
            clauses.append(f"{field} IN ({placeholders})")
            for i, v in enumerate(val):
                params[f"cat_{p}_{i}"] = v
        elif kind == "numeric":
            clauses.append(
                f"TRY_CAST({field} AS DOUBLE) BETWEEN $num_{p}_lo AND $num_{p}_hi"
            )
            params[f"num_{p}_lo"] = val[0]
            params[f"num_{p}_hi"] = val[1]
        elif kind == "bool":
            clauses.append(f"{field} = $bool_{p}")
            params[f"bool_{p}"] = bool(val)
    return f" WHERE {' AND '.join(clauses)}" if clauses else ""


__all__ = ["binding_workspace_server"]
