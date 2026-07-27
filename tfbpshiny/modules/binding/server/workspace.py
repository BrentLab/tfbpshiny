from __future__ import annotations

import itertools
from logging import Logger
from typing import Any

import duckdb
import pandas as pd
import plotly.graph_objects as go
from plotly.io import to_html
from shiny import module, reactive, render, ui

from tfbpshiny.components import scroll_row
from tfbpshiny.modules.binding.queries import fetch_corr_pairs
from tfbpshiny.modules.binding.ui import (
    COL_PREFERENCE_CHOICES,
    COL_PREFERENCE_CHOICES_NO_LOG10,
)
from tfbpshiny.utils.correlation_matrix import build_correlation_matrix_ui
from tfbpshiny.utils.perf import perf, reset_render_counts
from tfbpshiny.utils.vdb_init import get_regulator_display_name


def _read_corr_type(input: Any) -> str:
    try:
        return str(input.corr_type())
    except Exception:
        return "spearman"


def _read_col_preference(input: Any) -> str:
    try:
        return str(input.col_preference())
    except Exception:
        return "log10pval"


@module.server
def binding_workspace_server(
    input: Any,
    output: Any,
    session: Any,
    active_binding_datasets: reactive.Calc_[list[str]],
    dataset_filters: reactive.Value[dict[str, Any]],
    conn: duckdb.DuckDBPyConnection,
    logger: Logger,
) -> None:
    """
    Render the binding correlation workspace: matrix, pair distribution box plots.

    All active binding dataset pairs are always shown — there is no per-pair
    selection. Correlation matrix and distributions update automatically as
    the active dataset set, correlation method, or score type change.

    :param active_binding_datasets: Reactive calc returning active binding db names.
    :param dataset_filters: Reactive value holding current filter state.
    :param conn: Read-only DuckDB connection to the materialized database.
    :param logger: Application logger.

    """
    session.on_flush(lambda: reset_render_counts(session.id))

    _display_df = conn.execute(
        "SELECT db_name, display_name FROM dataset_registry"
    ).df()
    display_names: dict[str, str] = dict(
        zip(_display_df["db_name"], _display_df["display_name"])
    )

    _reg_df = get_regulator_display_name(conn)
    _sym_lookup: dict[str, str] = {}
    for _, row in _reg_df.iterrows():
        tag = str(row["regulator_locus_tag"])
        sym = str(row.get("regulator_symbol", ""))
        if sym and sym != "nan" and sym != tag:
            _sym_lookup[tag] = f"{sym} ({tag})"
        else:
            _sym_lookup[tag] = tag

    _binding_dbs_df = conn.execute(
        "SELECT db_name FROM dataset_registry "
        "WHERE data_type = 'binding' ORDER BY db_name"
    ).df()
    _all_possible_pairs: list[tuple[str, str]] = list(
        itertools.combinations(_binding_dbs_df["db_name"].tolist(), 2)
    )

    @reactive.calc
    def _active_pairs() -> list[tuple[str, str]]:
        """
        Pairs of all active binding datasets.

        :trigger: ``active_binding_datasets`` — re-runs when dataset selection changes.

        """
        active = active_binding_datasets()
        return list(itertools.combinations(sorted(active), 2))

    @reactive.calc
    def _corr_data() -> dict[tuple[str, str], pd.DataFrame]:
        """
        Per-regulator correlation values for every active dataset pair.

        :trigger: ``_active_pairs`` — re-runs when dataset selection changes.
        :trigger: ``dataset_filters`` — re-runs when per-dataset filters change.
        :trigger: ``input.corr_type`` — re-runs when correlation method changes.
        :trigger: ``input.col_preference`` — re-runs when score type changes.

        """
        pairs = _active_pairs()
        filters = dataset_filters()
        method = _read_corr_type(input)
        score_type = _read_col_preference(input)

        if not pairs:
            return {}

        logger.debug(
            "binding _corr_data: pairs=%s method=%s score_type=%s",
            pairs,
            method,
            score_type,
        )
        with perf(session.id, "binding.workspace", "_corr_data", kind="data"):
            try:
                return fetch_corr_pairs(
                    conn,
                    pairs,
                    filters,
                    method,
                    score_type,
                    comparison_type="binding",
                )
            except Exception:
                logger.exception("binding fetch_corr_pairs failed")
                return {p: pd.DataFrame() for p in pairs}

    @reactive.effect
    @reactive.event(input.corr_type)
    def _sync_col_preference_choices() -> None:
        """
        Hide -log10(p-value) from the Column choices when Spearman is selected.

        Spearman is rank-based, so p-value and -log10(p-value) are
        mathematically redundant; the ``log10pval`` score type is not
        materialized for spearman at all, so offering it as a choice would
        silently return empty correlations.

        :trigger: ``input.corr_type`` — re-runs (incl. on session start) when
            the correlation method changes.

        """
        current = _read_col_preference(input)
        if _read_corr_type(input) == "spearman":
            selected = "pvalue" if current == "log10pval" else current
            ui.update_radio_buttons(
                "col_preference",
                choices=COL_PREFERENCE_CHOICES_NO_LOG10,
                selected=selected,
                inline=True,
            )
        else:
            ui.update_radio_buttons(
                "col_preference",
                choices=COL_PREFERENCE_CHOICES,
                selected=current,
                inline=True,
            )

    @render.ui
    def analysis_status() -> ui.Tag:
        """
        Status message when no pairs are available.

        :trigger: ``_active_pairs`` — re-renders when pair list changes.

        """
        if not _active_pairs():
            return ui.div(
                {"class": "empty-state"},
                ui.p("Select at least two binding datasets to see correlations."),
            )
        return ui.span()

    @render.ui
    def corr_matrix_container() -> ui.Tag:
        """
        Pairwise correlation matrix table.

        :trigger: ``_active_pairs`` — re-renders when pairs change.
        :trigger: ``_corr_data`` — re-renders when data is refreshed.

        """
        with perf(session.id, "binding.workspace", "corr_matrix_container"):
            pairs = _active_pairs()
            if not pairs:
                return ui.div(
                    {"class": "empty-state"},
                    ui.p("Select at least two binding datasets to see correlations."),
                )
            corr_data = _corr_data()
            active = active_binding_datasets()
            return build_correlation_matrix_ui(
                all_possible_pairs=_all_possible_pairs,
                active_pairs=pairs,
                active_datasets=sorted(active),
                corr_data=corr_data,
                display_names=display_names,
            )

    @render.ui
    def regulator_selector_box() -> ui.Tag:
        """
        Dropdown of regulators for highlighting in the pair distribution plots.

        :trigger: ``_corr_data`` — re-renders when data changes.
        :trigger: ``_active_pairs`` — re-renders when active pairs change.

        """
        pairs = _active_pairs()
        if not pairs:
            return ui.span()
        corr_data = _corr_data()
        all_regs: set[str] = set()
        for pair in pairs:
            df = corr_data.get(pair, pd.DataFrame())
            if not df.empty and "regulator_locus_tag" in df.columns:
                all_regs |= set(df["regulator_locus_tag"].dropna().astype(str))
        if not all_regs:
            return ui.span()
        choices = {r: _sym_lookup.get(r, r) for r in all_regs}
        choices = dict(sorted(choices.items(), key=lambda kv: kv[1].lower()))
        try:
            cur = str(input.selected_reg_box())
        except Exception:
            cur = ""
        default = cur if cur in choices else next(iter(choices))
        return ui.input_selectize(
            "selected_reg_box", "Highlight regulator", choices=choices, selected=default
        )

    @render.ui
    def pair_box_container() -> ui.Tag:
        """
        Box plots for every active dataset pair.

        :trigger: ``_active_pairs`` — re-renders when active pairs change.
        :trigger: ``_corr_data`` — re-renders when data changes.
        :trigger: ``input.selected_reg_box`` — re-renders to update highlight.

        """
        pairs = _active_pairs()
        if not pairs:
            return ui.span()

        with perf(session.id, "binding.workspace", "pair_box_container"):
            corr_data = _corr_data()
            method = _read_corr_type(input).capitalize()
            try:
                selected_reg = str(input.selected_reg_box())
            except Exception:
                selected_reg = ""

            plots: list[ui.Tag] = []
            for db_a, db_b in pairs:
                df = corr_data.get((db_a, db_b), pd.DataFrame())
                label_a = display_names.get(db_a, db_a)
                label_b = display_names.get(db_b, db_b)
                pair_label = f"{label_a} vs {label_b}"

                fig = go.Figure()
                all_x: list[str] = []
                all_y: list[float] = []
                all_tags: list[str] = []
                all_hover: list[str] = []

                if not df.empty and "correlation" in df.columns:
                    df_clean = df.dropna(subset=["correlation"])
                    for tag, corr in zip(
                        df_clean["regulator_locus_tag"], df_clean["correlation"]
                    ):
                        all_x.append(pair_label)
                        all_y.append(float(corr))
                        all_tags.append(str(tag))
                        all_hover.append(_sym_lookup.get(str(tag), str(tag)))

                fig.add_trace(
                    go.Box(
                        x=all_x,
                        y=all_y,
                        text=all_hover,
                        customdata=all_tags,
                        hovertemplate="%{text}<br>r = %{y:.3f}<extra></extra>",
                        hoveron="points",
                        boxpoints="all",
                        jitter=0.4,
                        pointpos=0,
                        marker=dict(size=4, opacity=0.5),
                        line=dict(width=1.5),
                        showlegend=False,
                    )
                )

                if selected_reg:
                    sel_idx = [i for i, t in enumerate(all_tags) if t == selected_reg]
                    if sel_idx:
                        fig.add_trace(
                            go.Scatter(
                                x=[all_x[i] for i in sel_idx],
                                y=[all_y[i] for i in sel_idx],
                                mode="markers",
                                text=[all_hover[i] for i in sel_idx],
                                hovertemplate="%{text}<br>r = %{y:.3f}<extra></extra>",
                                marker=dict(size=10, color="black", symbol="circle"),
                                showlegend=False,
                            )
                        )

                fig.update_layout(
                    title=pair_label,
                    yaxis_title=f"{method} r",
                    margin=dict(l=40, r=20, t=50, b=60),
                )
                plots.append(
                    ui.div(
                        ui.HTML(to_html(fig, include_plotlyjs="cdn", full_html=False)),
                        style="flex: 0 0 auto; min-width: 400px;",
                    )
                )

            if not plots:
                return ui.span()
            return scroll_row(*plots)


__all__ = ["binding_workspace_server"]
