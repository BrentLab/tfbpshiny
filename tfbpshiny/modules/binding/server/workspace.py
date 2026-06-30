from __future__ import annotations

import itertools
from logging import Logger
from typing import Any

import duckdb
import pandas as pd
import plotly.graph_objects as go
from plotly.io import to_html
from shiny import module, reactive, render, ui

from tfbpshiny.modules.binding.queries import fetch_corr_pairs
from tfbpshiny.utils.correlation_matrix import build_correlation_matrix_ui
from tfbpshiny.utils.perf import perf
from tfbpshiny.utils.vdb_init import get_regulator_display_name


def _read_corr_type(input: Any) -> str:
    try:
        return str(input.corr_type())
    except Exception:
        return "spearman"


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

    :param active_binding_datasets: Reactive calc returning active binding db names.
    :param dataset_filters: Reactive value holding current filter state.
    :param conn: Read-only DuckDB connection to the materialized database.
    :param logger: Application logger.

    """
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

    # Pending UI state: updates immediately on every cell click.
    # Drives matrix cell highlights; does NOT drive distributions.
    _selected_pairs: reactive.Value[list[tuple[str, str]]] = reactive.value([])

    # Committed state: updated only on Execute or auto-reset (dataset change).
    # Drives distributions and the regulator selector dropdown.
    _committed_pairs: reactive.Value[list[tuple[str, str]]] = reactive.value([])

    # Incremented by Execute button to force a re-run of the data fetch.
    _execute_trigger: reactive.Value[int] = reactive.value(0)

    # False on load (nothing pending). True when pending changes exist.
    _needs_execute: reactive.Value[bool] = reactive.value(False)

    @reactive.effect
    @reactive.event(input.execute_analysis)
    def _on_execute() -> None:
        """
        Commit pending pair selection, force data refetch, mark button up-to-date.

        :trigger: ``input.execute_analysis`` — fires when Execute Analysis is clicked.

        """
        with reactive.isolate():
            _execute_trigger.set(_execute_trigger() + 1)
            _committed_pairs.set(list(_selected_pairs()))
        _needs_execute.set(False)

    @reactive.effect
    @reactive.event(input.corr_type, ignore_init=True)
    def _mark_needs_execute() -> None:
        """
        Mark the Execute button as needed when sidebar settings change.

        Cell clicks activate the button directly in ``_make_cell_click_effect``.
        Dataset filter changes auto-update via the reactive ``dataset_filters()``
        dep in ``_corr_data`` — no Execute required for those.
        Uses ``ignore_init=True`` so the initial render does not spuriously
        activate the button.

        :trigger: ``input.corr_type`` — fires when correlation method changes.

        """
        _needs_execute.set(True)

    @reactive.calc
    def _active_pairs() -> list[tuple[str, str]]:
        """
        Pairs of active binding datasets after applying the per-tab dataset checkbox.

        :trigger: ``active_binding_datasets`` — re-runs when dataset selection changes.
        :trigger: ``input.included_datasets`` — re-runs when the checkbox changes.

        """
        active = active_binding_datasets()
        try:
            included = set(input.included_datasets())
        except Exception:
            included = set(active)
        filtered = [db for db in active if db in included]
        return list(itertools.combinations(sorted(filtered), 2))

    @reactive.calc
    def _corr_data() -> dict[tuple[str, str], pd.DataFrame]:
        """
        Per-regulator correlation values for every active dataset pair.

        Auto-updates when the active pair set or dataset filters change.  The
        correlation method is read inside ``reactive.isolate()`` — only Execute
        applies a pending method change.

        :trigger: ``_active_pairs`` — re-runs when dataset selection changes.
        :trigger: ``dataset_filters`` — re-runs when per-dataset filters change.
        :trigger: ``_execute_trigger`` — re-runs when Execute is clicked.

        """
        _execute_trigger()
        pairs = _active_pairs()
        filters = dataset_filters()
        with reactive.isolate():
            method = _read_corr_type(input)

        if not pairs:
            return {}

        logger.debug("binding _corr_data: pairs=%s method=%s", pairs, method)
        with perf(session.id, "binding.workspace", "_corr_data", kind="data"):
            try:
                return fetch_corr_pairs(
                    conn, pairs, filters, method, comparison_type="binding"
                )
            except Exception:
                logger.exception("binding fetch_corr_pairs failed")
                return {p: pd.DataFrame() for p in pairs}

    @render.ui
    def execute_pending_style() -> ui.Tag:
        """
        Activates the Execute button when there are pending changes.

        The button carries ``btn-apply-pending--idle`` in its initial class, so
        it is dimmed by static CSS from the first paint.  This output injects an
        ID-level override (higher specificity than the class) only when the
        button should be active — avoiding a flash of the active state on load.

        :trigger: ``_needs_execute`` — re-renders when execute state changes.

        """
        if not _needs_execute():
            return ui.span()
        btn_id = session.ns("execute_analysis")
        return ui.tags.style(
            f"#{btn_id} {{ opacity: 1; pointer-events: auto; cursor: pointer; }}"
        )

    @render.ui
    def dataset_selection() -> ui.Tag:
        """
        Checkbox group for including/excluding active binding datasets.

        :trigger: ``active_binding_datasets`` — re-renders when dataset set changes.

        """
        datasets = active_binding_datasets()
        if not datasets:
            return ui.span()
        return ui.input_checkbox_group(
            "included_datasets",
            label=None,
            choices={db: display_names.get(db, db) for db in sorted(datasets)},
            selected=datasets,
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
        :trigger: ``_selected_pairs`` — re-renders to update cell highlights.

        """
        with perf(session.id, "binding.workspace", "corr_matrix_container"):
            pairs = _active_pairs()
            if not pairs:
                return ui.div(
                    {"class": "empty-state"},
                    ui.p("Click Execute Analysis after selecting datasets."),
                )
            corr_data = _corr_data()
            active = active_binding_datasets()
            return build_correlation_matrix_ui(
                all_possible_pairs=_all_possible_pairs,
                active_pairs=pairs,
                active_datasets=sorted(active),
                corr_data=corr_data,
                display_names=display_names,
                selected_pairs=set(_selected_pairs()),
                ns=session.ns,
            )

    def _make_cell_click_effect(db_a: str, db_b: str) -> None:
        btn_id = f"corrpair_{db_a}__{db_b}"
        pair = (db_a, db_b)

        @reactive.effect
        @reactive.event(input[btn_id])
        def _on_click() -> None:
            cur = list(_selected_pairs())
            if pair in cur:
                cur.remove(pair)
            else:
                cur.append(pair)
            _selected_pairs.set(cur)
            _needs_execute.set(True)

    for _db_a, _db_b in _all_possible_pairs:
        _make_cell_click_effect(_db_a, _db_b)

    @reactive.effect
    def _sync_to_active() -> None:
        """
        Auto-reset both pair values to all active pairs when the dataset set changes.

        This is NOT a pending change — it is an automatic sync that leaves the
        Execute button dimmed and shows all distributions immediately.  The
        corr_type (even if pending) is applied automatically because ``_corr_data``
        re-runs and reads ``method`` from isolate on the same flush.

        :trigger: ``_active_pairs`` — fires when datasets or checkboxes change.

        """
        pairs = list(_active_pairs())
        _selected_pairs.set(pairs)
        _committed_pairs.set(pairs)
        _needs_execute.set(False)

    @render.ui
    def regulator_selector_box() -> ui.Tag:
        """
        Dropdown of regulators for highlighting in the pair distribution plots.

        :trigger: ``_corr_data`` — re-renders when data changes.
        :trigger: ``_committed_pairs`` — re-renders when committed selection changes.

        """
        sel_pairs = _committed_pairs()
        if not sel_pairs:
            return ui.span()
        corr_data = _corr_data()
        all_regs: set[str] = set()
        for pair in sel_pairs:  # sel_pairs is from _committed_pairs()
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
    def pending_changes_banner() -> ui.Tag:
        """
        Warning banner shown when there are pending changes awaiting Execute.

        :trigger: ``_needs_execute`` — re-renders when execute state changes.

        """
        if not _needs_execute():
            return ui.span()
        return ui.div(
            {"class": "alert alert-warning pending-banner"},
            ui.p(
                ui.tags.strong("Pending changes — "),
                "click Execute Analysis to update the distributions.",
            ),
        )

    @render.ui
    def pair_box_status() -> ui.Tag:
        """
        Prompt shown when no committed pair exists yet.

        :trigger: ``_active_pairs`` — re-renders when pairs change.
        :trigger: ``_committed_pairs`` — re-renders when committed selection changes.

        """
        if not _active_pairs():
            return ui.span()
        if not _committed_pairs():
            return ui.div(
                {"class": "empty-state"},
                ui.p(
                    "Click a cell in the Correlation Matrix to view its distribution."
                ),
            )
        return ui.span()

    @render.ui
    def pair_box_container() -> ui.Tag:
        """
        Box plots for each selected dataset pair.

        :trigger: ``_committed_pairs`` — re-renders when committed selection changes.
        :trigger: ``_corr_data`` — re-renders when data changes.
        :trigger: ``input.selected_reg_box`` — re-renders to update highlight.

        """
        sel_pairs = _committed_pairs()
        if not sel_pairs:
            return ui.span()

        with perf(session.id, "binding.workspace", "pair_box_container"):
            corr_data = _corr_data()
            with reactive.isolate():
                method = _read_corr_type(input).capitalize()
            try:
                selected_reg = str(input.selected_reg_box())
            except Exception:
                selected_reg = ""

            plots: list[ui.Tag] = []
            for db_a, db_b in sel_pairs:
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
            return ui.div(
                *plots,
                style=(
                    "display: flex; flex-wrap: wrap; gap: 1rem; "
                    "align-items: flex-start;"
                ),
            )


__all__ = ["binding_workspace_server"]
