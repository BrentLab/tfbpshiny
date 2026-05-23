from __future__ import annotations

import asyncio
import itertools
from logging import Logger
from typing import Any, Literal

import pandas as pd
import plotly.graph_objects as go
from labretriever import VirtualDB
from plotly.io import to_html
from shiny import reactive, render, req, ui
from shiny.reactive import extended_task
from shiny.ui import (  # noqa: F401 (bind_task_button used as decorator)
    bind_task_button,
    input_task_button,
)
from shinywidgets import output_widget, render_plotly

from tfbpshiny.modules.perturbation.queries import (
    corr_all_pairs_sql,
    get_measurement_column,
    regulator_scatter_sql,
)
from tfbpshiny.utils.perf import reset_render_counts
from tfbpshiny.utils.vdb_init import AppDatasets, get_regulator_display_name


def perturbation_workspace_server(
    input: Any,
    output: Any,
    session: Any,
    active_perturbation_datasets: reactive.Calc_[list[str]],
    dataset_filters: reactive.Value[dict[str, Any]],
    vdb: VirtualDB,
    app_datasets: AppDatasets,
    logger: Logger,
    active_tab: reactive.Calc_[str] | None = None,
) -> None:
    """
    Render the perturbation correlation workspace: per-pair box plots and
    per-regulator scatter plots, gated on an explicit Execute Analysis button.

    :param active_perturbation_datasets: Reactive calc returning the list of active
        perturbation dataset names from the select-datasets module.
    :param dataset_filters: Reactive value holding the current filter state.
    :param vdb: Application VirtualDB instance.
    :param app_datasets: App-level dataset metadata.
    :param logger: Application logger.
    :param active_tab: Optional reactive calc for the currently active tab name.

    """

    session.on_flush(lambda: reset_render_counts(session.id))

    display_names: dict[str, str] = {
        db_name: vdb.get_tags(db_name).get("display_name", db_name)
        for db_name in vdb.get_datasets()
    }

    _reg_df = get_regulator_display_name(vdb)
    sym_map: dict[str, str] = dict(
        zip(_reg_df["regulator_locus_tag"], _reg_df["display_name"])
    )

    # Currently selected regulator locus tag — shared across box and scatter renders.
    selected_reg: reactive.Value[str] = reactive.value("")

    # Box render-phase tracking: reset on Execute, incremented inside each
    # render_plotly closure so analysis_status can bridge the gap between task
    # completion and final plot appearance.
    _boxes_rendered: reactive.Value[int] = reactive.value(0)
    _boxes_expected: reactive.Value[int] = reactive.value(0)

    # Scatter render-phase tracking — bumped on each regulator change; each
    # _scatter_plot closure captures the epoch at render-start so stale async
    # completions from a previous selection don't advance the current counter.
    _scatter_epoch: reactive.Value[int] = reactive.value(0)
    _scatter_rendered: reactive.Value[int] = reactive.value(0)
    _scatter_expected: reactive.Value[int] = reactive.value(0)

    # Plain dicts mutated by render closures and _update_all_highlights.
    # Not reactive — intentionally updated in-place to avoid triggering re-renders.
    _box_widgets: dict[tuple[str, str], go.FigureWidget | None] = {}
    _box_data: dict[tuple[str, str], dict] = {}

    # Stable pair list — updated only when the active dataset set actually changes.
    _active_pairs: reactive.Value[list[tuple[str, str]]] = reactive.value([])

    # Snapshot of sidebar inputs at the time of the last Execute click.
    _last_run_snapshot: reactive.Value[tuple | None] = reactive.value(None)

    def _snapshot_current() -> tuple:
        """Return a hashable representation of the current sidebar inputs."""
        try:
            filters_repr = repr(
                sorted((k, repr(v)) for k, v in dataset_filters().items())
            )
        except Exception:
            filters_repr = ""
        return (
            tuple(sorted(_active_pairs())),
            input.col_preference(),
            input.corr_type(),
            filters_repr,
        )

    @reactive.effect
    def _sync_pairs() -> None:
        """
        Write the pair list to ``_active_pairs`` only when it actually changes.

        :trigger active_perturbation_datasets: re-fires when the dataset selection
        changes. :trigger active_tab: silently blocks when another tab is active.

        """
        if active_tab is not None:
            req(active_tab() == "Perturbation")
        active = active_perturbation_datasets()
        new = list(itertools.combinations(sorted(active), 2))
        with reactive.isolate():
            if new != _active_pairs():
                _active_pairs.set(new)

    @render.ui
    def execute_pending_style() -> ui.Tag:
        """
        Inject a ``<style>`` tag that dims the Execute Analysis button when no changes
        are pending since the last run.

        :trigger _active_pairs: re-fires when dataset selection changes. :trigger
        input.col_preference: re-fires on column change. :trigger input.corr_type: re-
        fires on correlation-method change. :trigger _last_run_snapshot: re-fires after
        Execute to reset the indicator. :trigger dataset_filters: re-fires when filters
        change.

        """
        current = _snapshot_current()
        last = _last_run_snapshot()
        has_pending = (last is None) or (current != last)
        if has_pending:
            return ui.span()
        btn_id = session.ns("execute_analysis")
        return ui.tags.style(f"#{btn_id} {{ opacity: 0.35; }}")

    # --- Execute Analysis task --------------------------------------------------

    @bind_task_button(button_id="execute_analysis")
    @extended_task
    async def _run_analysis(
        pairs: list[tuple[str, str]],
        col_map: dict[str, str],
        filters: dict,
        method: str,
    ) -> dict:
        """
        Compute per-regulator pairwise correlations off the main thread.

        :param pairs: Dataset pairs to compute.
        :param col_map: Mapping from db_name to measurement column name.
        :param filters: Active dataset filters at execute time.
        :param method: Correlation method (``"pearson"`` or ``"spearman"``).
        :returns: Dict with keys ``corr_data``, ``pairs``, ``col_map``, ``method``,
            and ``filters``.

        """
        empty_cols = [
            "db_a",
            "db_a_id",
            "db_b",
            "db_b_id",
            "regulator_locus_tag",
            "correlation",
        ]
        if not pairs:
            return {
                "corr_data": {},
                "pairs": [],
                "col_map": col_map,
                "method": method,
                "filters": filters,
            }

        try:
            combined = await asyncio.to_thread(
                corr_all_pairs_sql, vdb, pairs, col_map, filters, method
            )
        except Exception as exc:
            logger.error("corr_all_pairs_sql failed: %s", exc, exc_info=True)
            combined = pd.DataFrame(columns=empty_cols + ["pair_key"])

        corr_data: dict[tuple[str, str], pd.DataFrame] = {}
        for db_a, db_b in pairs:
            key = f"{db_a}__{db_b}"
            if combined.empty or "pair_key" not in combined.columns:
                corr_data[(db_a, db_b)] = pd.DataFrame(columns=empty_cols)
            else:
                subset = (
                    combined[combined["pair_key"] == key]
                    .drop(columns=["pair_key"])
                    .reset_index(drop=True)
                )
                corr_data[(db_a, db_b)] = subset

        return {
            "corr_data": corr_data,
            "pairs": pairs,
            "col_map": col_map,
            "method": method,
            "filters": filters,
        }

    @reactive.effect
    @reactive.event(input.execute_analysis)
    def _on_execute() -> None:
        """
        Read current sidebar state and invoke the analysis task.

        :trigger input.execute_analysis: fires when Execute Analysis is clicked.

        """
        pairs = _active_pairs()
        method = input.corr_type()
        preference: Literal["effect", "pvalue"] = (
            input.col_preference()  # type: ignore[assignment]
        )
        filters = dataset_filters()

        col_map = {
            db: get_measurement_column(db, preference) for pair in pairs for db in pair
        }
        _boxes_rendered.set(0)
        _boxes_expected.set(len(pairs))
        # Scatter counters reset here; _init_selected_reg or _reset_scatter_epoch
        # will set _scatter_expected once the task succeeds.
        _scatter_rendered.set(0)
        _scatter_expected.set(0)
        _run_analysis.invoke(pairs, col_map, filters, method)
        # Capture snapshot so _update_pending_indicator dims the button.
        _last_run_snapshot.set(_snapshot_current())

    # --- Eager regulator initialization and scatter epoch tracking ---------------

    @reactive.effect
    def _init_selected_reg() -> None:
        """
        Set ``selected_reg`` as soon as the task succeeds so scatter plots start
        computing in parallel with box-plot renders.

        Preserves the current selection if still valid; falls back to the
        alphabetically first entry otherwise. When the selection is already valid,
        bumps the scatter epoch directly because ``_reset_scatter_epoch`` only fires
        on reg *changes*.

        :trigger _run_analysis.status: fires when the task state changes to success.

        """
        if _run_analysis.status() != "success":
            return
        result = _run_analysis.result()
        all_regs: set[str] = set()
        for df in result["corr_data"].values():
            if not df.empty:
                all_regs |= set(df["regulator_locus_tag"].dropna().unique())
        if not all_regs:
            return
        choices = dict(
            sorted(
                {r: sym_map.get(r, r) for r in all_regs}.items(),
                key=lambda kv: kv[1].lower(),
            )
        )
        default = next(iter(choices))
        with reactive.isolate():
            cur = selected_reg()
        if cur not in choices:
            # Changing selected_reg triggers _reset_scatter_epoch automatically.
            selected_reg.set(default)
        else:
            # Reg is unchanged; manually bump the epoch so the "preparing" message
            # fires and scatter plots start counting from zero for this run.
            with reactive.isolate():
                _scatter_epoch.set(_scatter_epoch() + 1)
                _scatter_rendered.set(0)
                _scatter_expected.set(len(result["pairs"]))

    @reactive.effect
    def _reset_scatter_epoch() -> None:
        """
        Bump the scatter render epoch whenever ``selected_reg`` changes.

        Reading ``_run_analysis`` under ``reactive.isolate`` means this effect fires
        only on ``selected_reg`` changes, not on task-status transitions.

        :trigger selected_reg: fires when the user selects a different regulator.

        """
        reg = selected_reg()
        if not reg:
            return
        with reactive.isolate():
            if _run_analysis.status() != "success":
                return
            result = _run_analysis.result()
            _scatter_epoch.set(_scatter_epoch() + 1)
            _scatter_rendered.set(0)
            _scatter_expected.set(len(result["pairs"]))

    # --- Status render ----------------------------------------------------------

    @render.ui
    def analysis_status() -> ui.Tag:
        """
        User feedback spanning both phases: task computation and plot rendering.

        Phase 1 (task running): shown while ``_run_analysis`` is off-thread.
        Phase 2 (rendering): shown after the task succeeds but before all
        ``render_plotly`` closures have completed.

        :trigger _run_analysis.status: re-renders when the task state changes.
        :trigger _boxes_rendered: re-renders as each box plot finishes building.

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
        if status == "success" and _boxes_rendered() < _boxes_expected():
            return ui.div(
                {"class": "empty-state"},
                ui.p("Building visualizations, please wait..."),
            )
        return ui.span()

    # --- Box plot helpers -------------------------------------------------------

    def _highlight_one(
        fig: go.FigureWidget,
        pair: tuple[str, str],
        reg: str,
    ) -> None:
        """
        Mutate trace 1 of ``fig`` in-place to highlight ``reg``'s points.

        Sends a ``_py2js_restyle`` delta via ``batch_update``; the box trace is
        never touched, so no full figure re-render occurs.

        :param fig: The FigureWidget to update.
        :param pair: ``(db_a, db_b)`` key into ``_box_data``.
        :param reg: Regulator locus tag to highlight, or ``""`` to clear.

        """
        data = _box_data.get(pair)
        if data is None or not reg:
            sel_x: list = []
            sel_y: list = []
            sel_hover: list = []
        else:
            all_x = data["all_x"]
            all_y = data["all_y"]
            all_tags = data["all_tags"]
            all_hover = data["all_hover"]
            idx = [i for i, t in enumerate(all_tags) if t == reg]
            sel_x = [all_x[i] for i in idx]
            sel_y = [all_y[i] for i in idx]
            sel_hover = [all_hover[i] for i in idx]
        with fig.batch_update():
            fig.data[1].x = sel_x
            fig.data[1].y = sel_y
            fig.data[1].hovertext = sel_hover

    @reactive.effect
    def _update_all_highlights() -> None:
        """
        In-place update of the highlight trace in every live box FigureWidget.

        Never calls any render function; only the delta for trace 1 is sent to the
        client.

        :trigger selected_reg: fires when the user clicks a point or picks from
        dropdown.

        """
        reg = selected_reg()
        for pair, fig in _box_widgets.items():
            if fig is not None:
                _highlight_one(fig, pair, reg)

    # --- All possible pairs (fixed at init) ------------------------------------

    _all_possible_pairs: list[tuple[str, str]] = list(
        itertools.combinations(
            sorted(
                db
                for db in vdb.get_datasets()
                if vdb.get_tags(db).get("data_type") == "perturbation"
            ),
            2,
        )
    )

    # --- Box plot container ----------------------------------------------------

    @render.ui
    def box_plot_container() -> ui.Tag:
        """
        Flex container of one ``output_widget`` slot per active pair.

        :trigger _run_analysis.status: re-renders when the task completes.

        """
        status = _run_analysis.status()
        if status != "success":
            if status == "initial":
                return ui.div(
                    {"class": "empty-state"},
                    ui.p(
                        "Click Execute Analysis to compute pairwise perturbation"
                        " correlations."
                    ),
                )
            return ui.span()

        result = _run_analysis.result()
        pairs: list[tuple[str, str]] = result["pairs"]
        if not pairs:
            return ui.div(
                {"class": "empty-state"},
                ui.p(
                    "No active perturbation dataset pairs. Select at least two"
                    " datasets on the Select Datasets page."
                ),
            )

        slots = [
            ui.div(
                output_widget(f"box_{db_a}__{db_b}"),
                style="flex: 0 0 auto;",
            )
            for db_a, db_b in _all_possible_pairs
            if (db_a, db_b) in pairs
        ]
        return ui.div(
            *slots,
            style="display: flex; flex-wrap: wrap; gap: 1rem; align-items: flex-start;",
        )

    # --- Per-pair box plot renders ---------------------------------------------

    def _make_box_render(db_a: str, db_b: str) -> None:
        """
        Register a ``render_plotly`` for one dataset pair's box plot.

        The returned FigureWidget is stored in ``_box_widgets`` so
        ``_update_all_highlights`` can mutate it in-place when the selected
        regulator changes without triggering a re-render.

        :param db_a: First dataset name.
        :param db_b: Second dataset name.

        """

        @output(id=f"box_{db_a}__{db_b}")
        @render_plotly
        def _box_plot() -> go.FigureWidget:
            """
            Box + jittered-points plot of per-regulator correlations for one pair.

            Returns an empty FigureWidget when the task has not succeeded or this
            pair is not in the current result. On success, stores references in
            ``_box_widgets`` and ``_box_data`` for in-place highlight updates.

            :trigger _run_analysis.status: re-renders when the task completes.

            """

            def _count_rendered() -> None:
                """Increment the render counter without creating a reactive dep."""
                with reactive.isolate():
                    _boxes_rendered.set(_boxes_rendered() + 1)

            if _run_analysis.status() != "success":
                return go.FigureWidget()

            result = _run_analysis.result()
            if (db_a, db_b) not in result["pairs"]:
                _box_widgets[(db_a, db_b)] = None
                _count_rendered()
                return go.FigureWidget()

            df = result["corr_data"].get((db_a, db_b), pd.DataFrame())
            method = result["method"]
            label_a = display_names.get(db_a, db_a)
            label_b = display_names.get(db_b, db_b)

            all_x: list[str] = []
            all_y: list[float] = []
            all_tags: list[str] = []
            all_hover: list[str] = []

            if not df.empty:
                df_clean = df.dropna(subset=["correlation"])
                for tag, corr in zip(
                    df_clean["regulator_locus_tag"],
                    df_clean["correlation"],
                ):
                    all_x.append(f"{label_a}\nvs\n{label_b}")
                    all_y.append(float(corr))
                    all_tags.append(tag)
                    all_hover.append(sym_map.get(tag, tag))

            fig = go.FigureWidget()
            fig.add_trace(
                go.Box(
                    x=all_x,
                    y=all_y,
                    text=all_hover,
                    customdata=all_tags,
                    hovertemplate="%{text}<extra></extra>",
                    hoveron="points",
                    boxpoints="all",
                    jitter=0.4,
                    pointpos=0,
                    marker=dict(size=4, opacity=0.5),
                    line=dict(width=1.5),
                    showlegend=False,
                )
            )
            # Trace 1: highlight overlay — populated by _highlight_one in-place.
            fig.add_trace(
                go.Scatter(
                    x=[],
                    y=[],
                    mode="markers",
                    hovertext=[],
                    hovertemplate="%{hovertext}<extra></extra>",
                    marker=dict(size=10, color="black", symbol="circle"),
                    showlegend=False,
                )
            )

            fig.update_layout(
                title=dict(
                    text=f"{label_a}<br>vs<br>{label_b}", x=0.5, xanchor="center"
                ),
                yaxis=dict(title=f"{method.capitalize()} r", range=[-1, 1]),
                showlegend=False,
                margin=dict(l=50, r=20, t=100, b=60),
                width=380,
                height=420,
            )

            _box_data[(db_a, db_b)] = {
                "all_x": all_x,
                "all_y": all_y,
                "all_tags": all_tags,
                "all_hover": all_hover,
            }
            _box_widgets[(db_a, db_b)] = fig

            # Register click handler: sets selected_reg reactive value.
            def _on_click(trace: Any, points: Any, state: Any) -> None:
                if not points.point_inds:
                    return
                reg = all_tags[points.point_inds[0]]
                selected_reg.set(reg)

            fig.data[0].on_click(_on_click)

            # Pre-populate highlight for any already-selected regulator.
            with reactive.isolate():
                cur = selected_reg()
            if cur:
                _highlight_one(fig, (db_a, db_b), cur)

            _count_rendered()
            return fig

    for _db_a, _db_b in _all_possible_pairs:
        _make_box_render(_db_a, _db_b)

    # --- Regulator selector and scatter tab status ----------------------------

    @render.ui
    def scatter_status() -> ui.Tag:
        """
        Status message on the Scatter tab while plots are being built.

        :trigger _scatter_rendered: re-renders as each scatter plot finishes. :trigger
        _scatter_expected: re-renders when expected count is set.

        """
        if _run_analysis.status() != "success":
            return ui.span()
        if _scatter_rendered() < _scatter_expected():
            return ui.div(
                {"class": "empty-state"},
                ui.p("Preparing visualizations, please wait..."),
            )
        return ui.span()

    @render.ui
    def regulator_selector() -> ui.Tag:
        """
        Dropdown of regulators present in at least one pair's correlation data.

        Initial selection is managed by ``_init_selected_reg``; this render only
        reflects the current value.

        :trigger _run_analysis.status: re-renders when the task completes.
        :trigger selected_reg: re-renders to reflect the current selection.

        """
        if _run_analysis.status() != "success":
            return ui.span()

        result = _run_analysis.result()
        corr_data: dict[tuple[str, str], pd.DataFrame] = result["corr_data"]

        all_regs: set[str] = set()
        for df in corr_data.values():
            if not df.empty:
                all_regs |= set(df["regulator_locus_tag"].dropna().unique())

        if not all_regs:
            return ui.span()

        choices = {r: sym_map.get(r, r) for r in all_regs}
        choices = dict(sorted(choices.items(), key=lambda kv: kv[1].lower()))

        with reactive.isolate():
            cur = selected_reg()
        default = cur if cur in choices else next(iter(choices), "")
        if not default:
            return ui.span()

        return ui.input_selectize(
            "selected_regulator_dropdown",
            "Regulator",
            choices=choices,
            selected=default,
        )

    @reactive.effect
    @reactive.event(input.selected_regulator_dropdown)
    def _sync_dropdown_to_reg() -> None:
        """
        Propagate dropdown selection to ``selected_reg``.

        :trigger input.selected_regulator_dropdown: fires when the user picks a
        regulator.

        """
        try:
            val = str(input.selected_regulator_dropdown())
        except Exception:
            return
        with reactive.isolate():
            if val != selected_reg():
                selected_reg.set(val)

    # --- Scatter plots ---------------------------------------------------------

    @render.ui
    def scatter_container() -> ui.Tag:
        """
        Flex container with one output slot per currently active pair.

        :trigger _run_analysis.status: re-renders when the task completes.

        """
        if _run_analysis.status() != "success":
            return ui.span()

        result = _run_analysis.result()
        pairs: list[tuple[str, str]] = result["pairs"]
        if not pairs:
            return ui.span()

        slots = [
            ui.output_ui(f"scatter_{db_a}__{db_b}")
            for db_a, db_b in _all_possible_pairs
            if (db_a, db_b) in pairs
        ]
        return ui.div(
            ui.output_ui("scatter_missing_note"),
            ui.div(
                *slots,
                style=(
                    "display: flex; flex-wrap: wrap;"
                    " gap: 1rem; align-items: flex-start;"
                ),
            ),
        )

    @render.ui
    def scatter_missing_note() -> ui.Tag:
        """
        Warning listing datasets where the selected regulator was not found.

        :trigger selected_reg: re-renders when the regulator changes. :trigger
        _run_analysis.status: re-renders when the task completes.

        """
        if _run_analysis.status() != "success":
            return ui.span()
        reg = selected_reg()
        if not reg:
            return ui.span()

        result = _run_analysis.result()
        corr_data = result["corr_data"]
        pairs: list[tuple[str, str]] = result["pairs"]

        failed: set[str] = set()
        succeeded: set[str] = set()
        for db_a, db_b in pairs:
            df = corr_data.get((db_a, db_b))
            has_reg = (
                df is not None
                and not df.empty
                and reg in df["regulator_locus_tag"].values
            )
            if has_reg:
                succeeded.add(display_names.get(db_a, db_a))
                succeeded.add(display_names.get(db_b, db_b))
            else:
                failed.add(display_names.get(db_a, db_a))
                failed.add(display_names.get(db_b, db_b))

        truly_missing = failed - succeeded
        if not truly_missing:
            return ui.span()
        names = ", ".join(sorted(truly_missing))
        return ui.p(
            f"{reg} was not found in: {names}. "
            "Pairs involving these datasets are omitted.",
            style="color: gray; margin: 0.5rem 0;",
        )

    def _make_scatter_render(db_a: str, db_b: str, pair_idx: int) -> None:
        """
        Register a ``@render.ui`` for the scatter plot of one dataset pair.

        Reads params from the task result rather than current sidebar inputs so the plot
        reflects the state at the time Execute was clicked.

        :param db_a: First dataset name.
        :param db_b: Second dataset name.
        :param pair_idx: Stable integer index used to namespace SQL parameters.

        """

        @output(id=f"scatter_{db_a}__{db_b}")
        @render.ui
        async def _scatter_plot() -> ui.Tag:
            """
            Scatter plot for one ``(db_a, db_b)`` pair.

            Captures ``_scatter_epoch`` at render-start so that completions from
            a stale epoch do not advance the current counter.

            :trigger selected_reg: re-renders when the regulator changes.
            :trigger _run_analysis.status: re-renders when the task completes.

            """
            # Capture epoch without creating a reactive dep on _scatter_epoch itself.
            with reactive.isolate():
                my_epoch = _scatter_epoch()

            def _count_scatter() -> None:
                """Increment the scatter counter if this render's epoch is current."""
                with reactive.isolate():
                    if _scatter_epoch() == my_epoch:
                        _scatter_rendered.set(_scatter_rendered() + 1)

            if _run_analysis.status() != "success":
                return ui.span()

            result = _run_analysis.result()
            pairs: list[tuple[str, str]] = result["pairs"]
            if (db_a, db_b) not in pairs:
                return ui.span()

            reg = selected_reg()
            if not reg:
                _count_scatter()
                return ui.span()

            col_map = result["col_map"]
            method = result["method"]
            filters = result["filters"]

            def _strip_reg(f: dict | None) -> dict | None:
                if not f:
                    return f
                stripped = {k: v for k, v in f.items() if k != "regulator_locus_tag"}
                return stripped or None

            try:
                col_a = col_map.get(db_a) or get_measurement_column(db_a, "effect")
                col_b = col_map.get(db_b) or get_measurement_column(db_b, "effect")
                fa = _strip_reg(filters.get(db_a))
                fb = _strip_reg(filters.get(db_b))
                scatter_sql, scatter_params = regulator_scatter_sql(
                    db_a, col_a, fa, db_b, col_b, fb, method, reg, pair_idx
                )
                merged = await asyncio.to_thread(
                    vdb.query, scatter_sql, **scatter_params
                )
                logger.debug(
                    "scatter %s/%s reg=%r rows=%d", db_a, db_b, reg, len(merged)
                )
            except Exception:
                logger.exception("Scatter fetch failed for %s/%s", db_a, db_b)
                _count_scatter()
                return ui.span()

            if merged.empty:
                _count_scatter()
                return ui.span()

            la = display_names.get(db_a, db_a)
            lb = display_names.get(db_b, db_b)
            r = merged["_val_a"].corr(merged["_val_b"])

            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=merged["_val_a"],
                    y=merged["_val_b"],
                    mode="markers",
                    marker=dict(size=4, opacity=0.6, color="#4A90D9"),
                    text=merged["target_symbol"],
                    hovertemplate="%{text}<extra></extra>",
                    showlegend=False,
                )
            )
            fig.add_annotation(
                text=f"r={r:.3f}",
                xref="paper",
                yref="paper",
                x=0.98,
                y=0.98,
                xanchor="right",
                yanchor="top",
                showarrow=False,
                font=dict(size=12),
            )
            fig.update_layout(
                title=dict(text=f"{la}<br>vs<br>{lb}", x=0.5, xanchor="center"),
                xaxis_title=f"{la}: {col_a}",
                yaxis_title=f"{lb}: {col_b}",
                margin=dict(l=50, r=20, t=100, b=50),
                width=400,
                height=400,
            )
            _count_scatter()
            return ui.div(
                ui.HTML(to_html(fig, include_plotlyjs=False, full_html=False)),
                style="flex: 0 0 auto;",
            )

    for _pair_idx, (_db_a, _db_b) in enumerate(_all_possible_pairs, start=1):
        _make_scatter_render(_db_a, _db_b, _pair_idx)


__all__ = ["perturbation_workspace_server"]
