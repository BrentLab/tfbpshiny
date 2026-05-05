from __future__ import annotations

import copy
import itertools
import time
from collections.abc import Callable
from html import escape
from logging import Logger
from typing import Any, Literal

import pandas as pd
import plotly.graph_objects as go
from labretriever import VirtualDB
from plotly.io import to_html
from shiny import module, reactive, render, ui

from tfbpshiny.modules.perturbation.queries import (
    corr_pair_sql,
    get_measurement_column,
    regulator_scatter_sql,
)
from tfbpshiny.utils.profiler import profile_span
from tfbpshiny.utils.query_cache import cached_query
from tfbpshiny.utils.sample_conditions import fetch_sample_condition_map
from tfbpshiny.utils.vdb_init import AppDatasets, get_regulator_display_name


@module.server
def perturbation_workspace_server(
    input: Any,
    output: Any,
    session: Any,
    active_perturbation_datasets: reactive.Calc_[list[str]],
    corr_type: Callable[[], str],
    col_preference: Callable[[], str],
    dataset_filters: reactive.Value[dict[str, Any]],
    vdb: VirtualDB,
    app_datasets: AppDatasets,
    logger: Logger,
    profile_logger: Logger,
    session_id: str = "",
    shared_regulator: reactive.Value[str] | None = None,
    active_module: reactive.Value[str] | None = None,
) -> None:
    """
    Render the perturbation correlation rows: pairwise distributions
    and per-regulator plots.
    """

    display_names: dict[str, str] = {
        db_name: vdb.get_tags(db_name).get("display_name", db_name)
        for db_name in vdb.get_datasets()
    }

    _reg_df = get_regulator_display_name(vdb)
    sym_map: dict[str, str] = dict(
        zip(_reg_df["regulator_locus_tag"], _reg_df["display_name"])
    )

    _render_counts: dict[str, int] = {"distributions_plot": 0, "regulator_plots": 0}

    @reactive.calc
    def _condition_maps() -> dict[str, dict[str, str]]:
        """
        ``{db_name: {sample_id: label}}`` for each active dataset that has
        experimental_condition columns.

        Used to annotate tooltips on the selected-regulator overlay in the
        distribution plot so the user can distinguish multiple samples of the
        same regulator. Datasets without ``condition_cols`` are omitted from
        the outer dict, causing the tooltip to skip their side.

        :trigger active_perturbation_datasets: re-runs when the user toggles
            a perturbation dataset on or off.
        :returns: Outer dict keyed by db_name; inner dict maps sample_id to
            the joined condition label.

        """
        out: dict[str, dict[str, str]] = {}
        for db in active_perturbation_datasets():
            cols = app_datasets.condition_cols.get(db, [])
            if not cols:
                continue
            try:
                out[db] = fetch_sample_condition_map(vdb, db, cols)
            except Exception:
                logger.exception("Failed to fetch condition map for %s", db)
                out[db] = {}
        return out

    @reactive.calc
    def _pairs() -> list[tuple[str, str]]:
        """
        All unique pairs of active perturbation datasets.

        :trigger active_perturbation_datasets: re-runs whenever the user toggles
            a perturbation dataset on or off in the Select Datasets sidebar.
        :returns: List of ``(db_a, db_b)`` tuples, length = n_active choose 2.

        """
        active = active_perturbation_datasets()
        return list(itertools.combinations(active, 2))

    # Persistent correlation cache. Stored as a reactive.Value so it survives
    # tab switches — unlike @reactive.calc, which is torn down when the module
    # DOM is destroyed. The tuple is (cache_key, result); the effect below
    # only re-runs queries when the key changes.
    _corr_cache: reactive.Value[tuple[tuple, dict[tuple[str, str], pd.DataFrame]]] = (
        reactive.Value(((), {}))
    )

    @reactive.effect
    def _fill_corr_cache() -> None:
        """
        Populate ``_corr_cache`` with per-pair correlation data.

        Reads all four inputs reactively so any change invalidates the effect
        and triggers a re-query.  Before running the queries the current inputs
        are hashed into a cache key; if the key matches what is already stored
        the effect returns immediately without touching the database.  This
        makes returning to the perturbation tab after a tab switch free — the
        DOM recreation invalidates the effect, but the key comparison
        short-circuits before any SQL is executed, and the existing
        ``_corr_cache`` value remains unchanged, so downstream renders read
        the cached result without waiting.

        :trigger _pairs: re-runs when the set of active pairs changes.
        :trigger col_preference: re-runs when column preference changes.
        :trigger corr_type: re-runs when correlation method changes.
        :trigger dataset_filters: re-runs when filters are applied or reset.

        """
        pairs = _pairs()
        preference: Literal["effect", "pvalue"] = col_preference()  # type: ignore[assignment] # noqa: E501
        method = corr_type()
        filters = dataset_filters()

        key: tuple = (
            tuple(pairs),
            preference,
            method,
            tuple(sorted((k, tuple(sorted(str(v)))) for k, v in filters.items())),
        )
        with reactive.isolate():
            cached_key, cached_result = _corr_cache.get()
        if key == cached_key:
            logger.debug("perturbation _fill_corr_cache: cache hit, skipping queries")
            return

        if not pairs:
            _corr_cache.set((key, {}))
            return

        result: dict[tuple[str, str], pd.DataFrame] = {}
        for i, (db_a, db_b) in enumerate(pairs):
            try:
                col_a = get_measurement_column(db_a, preference)
                col_b = get_measurement_column(db_b, preference)
                logger.debug(
                    f"Correlating {db_a}({col_a}) vs {db_b}({col_b}) ({method})"
                )
                with profile_span(
                    profile_logger,
                    "vdb.query",
                    module="perturbation",
                    dataset=f"{db_a}x{db_b}",
                    context="_all_corr_data",
                    session_id=session_id,
                ):
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
                    columns=[
                        "db_a",
                        "db_a_id",
                        "db_b",
                        "db_b_id",
                        "regulator_locus_tag",
                        "correlation",
                    ]
                )
        _corr_cache.set((key, result))

    def _all_corr_data() -> dict[tuple[str, str], pd.DataFrame]:
        """
        Return the current correlation data from the persistent cache.

        Reads ``_corr_cache`` reactively so callers invalidate when new data
        arrives.  The actual queries run in ``_fill_corr_cache``.

        :returns: Dict mapping ``(db_a, db_b)`` pairs to correlation DataFrames.

        """
        return _corr_cache()[1]

    # Persistent distributions-figure cache.  Stored as reactive.Value so it
    # survives tab switches — _distributions_base was a @reactive.calc that was
    # torn down on DOM destruction, forcing a full Plotly figure rebuild (2-3 s)
    # on every tab return even when the underlying data had not changed.
    _DistBase = tuple[
        go.Figure,
        dict[str, list[str]],
        dict[str, list[float]],
        dict[str, list[str]],
    ]
    _distributions_cache: reactive.Value[tuple[tuple, _DistBase]] = reactive.Value(
        ((), (go.Figure(), {}, {}, {}))
    )

    @reactive.effect
    def _fill_distributions_cache() -> None:
        """
        Rebuild the box+jitter figure only when the underlying data changes.

        Computes a cache key from the correlation cache key and a fingerprint of
        ``_condition_maps``.  On tab return the key matches and the effect exits
        immediately, so ``distributions_plot`` reads the cached figure without
        any CPU work.

        :trigger _corr_cache: re-runs when correlation data changes.
        :trigger _condition_maps: re-runs when condition label data changes.
        :trigger corr_type: re-runs when the correlation method changes.

        """
        pairs = _pairs()
        corr_data = _all_corr_data()
        cond_maps = _condition_maps()
        method = corr_type().capitalize()

        with reactive.isolate():
            cached_corr_key, _ = _corr_cache.get()
        cond_key = tuple(
            sorted((db, tuple(sorted(m.items()))) for db, m in cond_maps.items())
        )
        key: tuple = (cached_corr_key, cond_key, method)
        with reactive.isolate():
            cached_key, _ = _distributions_cache.get()
        if key == cached_key:
            logger.debug(
                "perturbation _fill_distributions_cache: cache hit, skipping build"
            )
            return

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
            _distributions_cache.set((key, (fig, {}, {}, {})))
            return

        all_x: list[str] = []
        all_y: list[float] = []
        all_tags: list[str] = []
        all_hover: list[str] = []

        tag_x: dict[str, list[str]] = {}
        tag_y: dict[str, list[float]] = {}
        tag_hover: dict[str, list[str]] = {}

        for db_a, db_b in pairs:
            df = corr_data.get((db_a, db_b), pd.DataFrame())
            label_a = display_names.get(db_a, db_a)
            label_b = display_names.get(db_b, db_b)
            pair_label = f"{label_a}<br>vs<br>{label_b}"
            cond_a = cond_maps.get(db_a, {})
            cond_b = cond_maps.get(db_b, {})
            if not df.empty:
                df_clean = df.dropna(subset=["correlation"])
                for tag, corr, sample_a, sample_b in zip(
                    df_clean["regulator_locus_tag"],
                    df_clean["correlation"],
                    df_clean["db_a_id"],
                    df_clean["db_b_id"],
                ):
                    display = sym_map.get(tag, tag)
                    all_x.append(pair_label)
                    all_y.append(corr)
                    all_tags.append(tag)
                    all_hover.append(display)

                    # Build per-tag hover for the highlight overlay.
                    # All DB-sourced strings are HTML-escaped before being
                    # joined with <br> separators because Plotly renders
                    # hovertext as HTML (stored-XSS sink if any researcher-
                    # uploaded metadata ever contained markup).
                    hover_lines = [escape(display), f"r = {corr:.3f}"]
                    label_sample_a = cond_a.get(str(sample_a), "")
                    if label_sample_a:
                        hover_lines.append(
                            f"{escape(label_a)}: {escape(label_sample_a)}"
                        )
                    label_sample_b = cond_b.get(str(sample_b), "")
                    if label_sample_b:
                        hover_lines.append(
                            f"{escape(label_b)}: {escape(label_sample_b)}"
                        )

                    tag_x.setdefault(tag, []).append(pair_label)
                    tag_y.setdefault(tag, []).append(corr)
                    tag_hover.setdefault(tag, []).append("<br>".join(hover_lines))

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

        fig.update_layout(
            title=f"{method} correlation across regulators",
            yaxis_title=f"{method} r",
            showlegend=False,
            margin=dict(l=40, r=20, t=50, b=80),
        )

        _distributions_cache.set((key, (fig, tag_x, tag_y, tag_hover)))

    @render.ui
    def distributions_plot() -> ui.Tag:
        """
        Compose the distributions figure: retrieve the cached base figure from
        ``_distributions_cache`` and add the highlight overlay for the currently
        selected regulator.

        Only the overlay composition and ``to_html`` call re-run when the user
        clicks a dot; the expensive box trace loop is cached in
        ``_fill_distributions_cache`` and only re-runs when the underlying data
        changes.

        :trigger _distributions_cache: re-renders when correlation data, condition
            maps, or correlation method changes.  ``shared_regulator`` is read
            inside ``isolate()`` so it does not register as a reactive dependency
            here — the overlay updates whenever the cache changes (which already
            keys on the regulator), avoiding phantom re-renders on the other tab.

        """
        _render_counts["distributions_plot"] += 1
        t0 = time.perf_counter()
        with reactive.isolate():
            selected_reg = (
                shared_regulator.get() if shared_regulator is not None else ""
            )
        logger.debug(
            f"RENDER perturbation/distributions_plot "
            f"#{_render_counts['distributions_plot']} "
            f"selected_regulator={selected_reg!r}"
        )

        _, (fig, tag_x, tag_y, tag_hover) = _distributions_cache()

        if selected_reg and selected_reg in tag_x:
            fig = copy.copy(fig)
            fig.add_trace(
                go.Scatter(
                    x=tag_x[selected_reg],
                    y=tag_y[selected_reg],
                    mode="markers",
                    hovertext=tag_hover[selected_reg],
                    customdata=[selected_reg] * len(tag_x[selected_reg]),
                    hovertemplate="%{hovertext}<extra></extra>",
                    marker=dict(size=10, color="black", symbol="circle"),
                    showlegend=False,
                )
            )

        input_id = session.ns("selected_regulator")
        # post_script runs immediately after Plotly.newPlot() initializes the
        # figure.  Plotly substitutes {plot_id} with the actual div ID before
        # inserting the script.  The IIFE registers a plotly_click handler on
        # the graph div using Plotly's event bus (div.on), which fires whenever
        # the user clicks a data point.  The clicked point's customdata field
        # holds the regulator locus tag (stored when building the highlight
        # trace above).  That tag is pushed to the Shiny input with
        # priority:'event' so the flush is immediate even if the value matches
        # the current selection.
        post_script = (
            "(function() {"
            "  var div = document.getElementById('{plot_id}');"
            "  div.on('plotly_click', function(data) {"
            "    var pt = data.points[0];"
            "    if (!pt || pt.customdata === undefined) return;"
            f"    Shiny.setInputValue('{input_id}', pt.customdata, {{priority: 'event'}});"  # type: ignore # noqa:E501
            "  });"
            "})();"
        )
        with profile_span(
            profile_logger,
            "plot.build",
            module="perturbation",
            context="distributions_plot",
            session_id=session_id,
        ):
            html = to_html(
                fig,
                include_plotlyjs=False,
                full_html=False,
                post_script=post_script,
            )
        logger.debug(
            f"RENDER_DONE perturbation/distributions_plot "
            f"#{_render_counts['distributions_plot']} "
            f"elapsed={time.perf_counter()-t0:.3f}s"
        )
        return ui.HTML(html)

    @reactive.calc
    def _regulator_choices() -> tuple[dict[str, str], str] | None:
        """
        Compute the sorted regulator choices dict and default selection key.

        Uses lazy evaluation — only runs when read by a downstream reactive
        context that is mounted. Dataset toggles on other pages never trigger
        this calc because nothing mounted on those pages reads it.

        The default key prefers the value already in ``shared_regulator`` so
        that switching from the binding tab preserves the last selection.
        The read of ``shared_regulator`` is isolated so this calc does not
        re-run every time the shared value is written.

        The result is consumed by ``_sync_regulator_choices``, which calls
        ``ui.update_selectize`` to push choices to the static
        ``selected_regulator`` widget.

        :trigger _all_corr_data: re-runs when correlation data changes
            (new datasets, filters applied, or column/method changed).
        :returns: ``(choices, default_key)`` when regulators are available,
            ``None`` when the correlation data is empty.

        """
        corr_data = _all_corr_data()
        if not corr_data:
            return None
        all_regs: set[str] = set()
        for df in corr_data.values():
            if not df.empty:
                all_regs |= set(df["regulator_locus_tag"].dropna().unique())
        if not all_regs:
            return None
        choices = {r: sym_map.get(r, r) for r in all_regs}
        choices = dict(sorted(choices.items(), key=lambda kv: kv[1].lower()))
        with reactive.isolate():
            current = shared_regulator.get() if shared_regulator is not None else ""
        default = current if current in choices else next(iter(choices))
        return choices, default

    @reactive.effect
    def _resolve_active_regulator() -> None:
        """
        Promote a non-empty, valid widget selection to ``shared_regulator``.

        Only writes when ``input.selected_regulator`` is a non-empty string
        that exists in the current choice set.  An empty string — which Shiny
        produces when the DOM is recreated on tab mount and the widget resets —
        is ignored so that a cross-tab selection made on the binding page is
        never overwritten by a spurious DOM-reset event here.

        The equality guard on ``.set()`` ensures ``shared_regulator`` only
        invalidates downstream renders when the resolved value actually changes,
        preventing double-renders caused by ``update_selectize`` echoing back
        through ``input.selected_regulator``.

        :trigger _regulator_choices: re-runs when the choice set changes.
        :trigger input.selected_regulator: re-runs on any non-empty widget change.

        """
        result = _regulator_choices()
        if result is None:
            return
        choices, _ = result
        try:
            current = str(input.selected_regulator())
        except Exception:
            current = ""
        # Ignore DOM-reset empty string and values not in the current choice set.
        if not current or current not in choices:
            logger.debug(
                f"perturbation _resolve_active_regulator: ignoring {current!r}"
            )
            return
        if shared_regulator is not None:
            with reactive.isolate():
                old_val = shared_regulator.get()
            if current != old_val:
                logger.debug(
                    f"perturbation _resolve_active_regulator: "
                    f"{old_val!r} -> {current!r}"
                )
                shared_regulator.set(current)

    @reactive.effect
    def _sync_regulator_choices() -> None:
        """
        Push choices and the active selection to the selectize widget.

        Depends on both ``_regulator_choices`` and ``input.selected_regulator``
        reactively.  The ``input.selected_regulator`` dependency is needed so
        that when the DOM is recreated on tab mount and the widget resets to
        ``""``, this effect fires and repopulates the fresh widget with the
        correct choices and the regulator currently stored in
        ``shared_regulator``.

        :trigger _regulator_choices: fires when correlation data changes.
        :trigger input.selected_regulator: fires when the widget is reset on tab mount.

        """
        result = _regulator_choices()
        try:
            input.selected_regulator()  # register dependency; value unused here
        except Exception:
            pass
        if result is None:
            ui.update_selectize("selected_regulator", choices={}, selected=None)
            return
        choices, default = result
        with reactive.isolate():
            effective = shared_regulator.get() if shared_regulator is not None else ""
        # Use the shared value only if it exists in this module's choices.
        # If not (e.g. a binding-only TF was selected on the other tab, or
        # shared_regulator is still empty on first mount), fall back to the
        # local alphabetical default and write it back to shared_regulator so
        # that the renders in this same flush read the correct value rather than
        # the empty string.
        if not effective or effective not in choices:
            effective = default
            if shared_regulator is not None:
                with reactive.isolate():
                    if shared_regulator.get() != effective:
                        shared_regulator.set(effective)
        logger.debug(
            f"perturbation _sync_regulator_choices: pushing selected={effective!r}"
        )
        ui.update_selectize("selected_regulator", choices=choices, selected=effective)

    # Persistent scatter-data cache keyed by (reg, pairs, preference, filters, method).
    # Stored as reactive.Value so the cache survives tab switches.  The effect below
    # runs the SQL queries as soon as any input changes; by the time the render
    # function executes, the data is already available and regulator_plots completes
    # in <10 ms instead of 400-550 ms.
    _ScatterResult = dict[tuple[str, str], Any]
    _scatter_cache: reactive.Value[tuple[tuple, _ScatterResult]] = reactive.Value(
        ((), {})
    )

    @reactive.effect
    def _fill_scatter_cache() -> None:
        """
        Populate ``_scatter_cache`` with per-pair scatter data for the active regulator.

        Reads all inputs reactively so any change (regulator click, filter change,
        dataset toggle, method change) invalidates the effect.  A cache-key comparison
        short-circuits before touching the database when nothing has changed — which is
        the common case after a tab return.

        :trigger active_module: exits early (without queries) when perturbation     is
        not the active tab; re-fires when the user switches to perturbation. :trigger
        shared_regulator: re-runs when the selected regulator changes. :trigger
        _all_corr_data: re-runs when the active pair set changes. :trigger
        col_preference: re-runs when the column preference changes. :trigger
        dataset_filters: re-runs when filters change. :trigger corr_type: re-runs when
        the correlation method changes.

        """
        # Read active_module reactively (not inside isolate) so the effect
        # re-fires when the user switches TO perturbation and can fill a stale cache.
        if active_module is not None and active_module() != "perturbation":
            return
        reg = (shared_regulator.get() if shared_regulator is not None else "") or None
        # Skip if the current regulator is not valid for this module's choice set.
        # This prevents running scatter queries for a cross-tab regulator that
        # _sync_regulator_choices is about to replace with the local default.
        choices_result = _regulator_choices()
        if choices_result is not None and reg is not None:
            choices, _ = choices_result
            if reg not in choices:
                return
        pairs = list(_all_corr_data().keys())
        preference: Literal["effect", "pvalue"] = col_preference()  # type: ignore[assignment] # noqa: E501
        filters = dataset_filters()
        method = corr_type()

        key: tuple = (
            reg,
            tuple(pairs),
            preference,
            method,
            tuple(sorted((k, str(v)) for k, v in filters.items())),
        )
        with reactive.isolate():
            cached_key, _ = _scatter_cache.get()
        if key == cached_key:
            logger.debug(
                "perturbation _fill_scatter_cache: cache hit, skipping queries"
            )
            return

        if not reg or not pairs:
            _scatter_cache.set((key, {}))
            return

        def _strip_reg(f: dict | None) -> dict | None:
            if not f:
                return f
            stripped = {k: v for k, v in f.items() if k != "regulator_locus_tag"}
            return stripped or None

        result: _ScatterResult = {}
        for idx, (db_a, db_b) in enumerate(pairs, start=1):
            try:
                col_a = get_measurement_column(db_a, preference)
                col_b = get_measurement_column(db_b, preference)
                fa = _strip_reg(filters.get(db_a))
                fb = _strip_reg(filters.get(db_b))
                scatter_sql, scatter_params = regulator_scatter_sql(
                    db_a, col_a, fa, db_b, col_b, fb, method, reg, idx
                )
                with profile_span(
                    profile_logger,
                    "vdb.query",
                    module="perturbation",
                    context="scatter_cache",
                    session_id=session_id,
                ):
                    merged = cached_query(vdb, scatter_sql, scatter_params)
                logger.debug(
                    f"scatter {db_a}/{db_b} reg={reg!r} "
                    f"rows={len(merged)} fa={fa!r} fb={fb!r}"
                )
                result[(db_a, db_b)] = (col_a, col_b, fa, fb, merged)
            except Exception:
                logger.exception(f"Regulator plot fetch failed for {db_a}/{db_b}")
        _scatter_cache.set((key, result))

    @render.ui
    def regulator_plots() -> ui.Tag:
        """
        Per-pair scatter plots for the selected regulator.

        Reads pre-fetched data from ``_scatter_cache`` so no SQL runs inside
        this render function.  The expensive queries run in
        ``_fill_scatter_cache`` before Shiny schedules the render.

        :trigger _scatter_cache: re-renders when scatter data changes (new
            regulator, filter change, dataset toggle, or method change).

        """
        _render_counts["regulator_plots"] += 1
        t0 = time.perf_counter()
        with reactive.isolate():
            _sel = shared_regulator.get() if shared_regulator is not None else ""
        logger.debug(
            f"RENDER perturbation/regulator_plots "
            f"#{_render_counts['regulator_plots']} "
            f"selected_regulator={_sel!r}"
        )
        try:
            result = _build_regulator_plots()
        except Exception as exc:
            logger.exception("regulator_plots render failed")
            fig = go.Figure()
            fig.add_annotation(
                text=f"Error rendering plots: {exc}",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
            )
            result = ui.HTML(to_html(fig, include_plotlyjs=False, full_html=False))
        logger.debug(
            f"RENDER_DONE perturbation/regulator_plots "
            f"#{_render_counts['regulator_plots']} "
            f"elapsed={time.perf_counter()-t0:.3f}s"
        )
        return result

    def _build_regulator_plots() -> ui.Tag:
        """
        Build the scatter plot UI from the pre-fetched ``_scatter_cache`` data.

        Pure function: reads the cache and constructs Plotly figures; performs
        no SQL queries.

        """
        with reactive.isolate():
            reg = (
                shared_regulator.get() if shared_regulator is not None else ""
            ) or None
        _, scatter_data = _scatter_cache()

        if not reg or not scatter_data:
            fig = go.Figure()
            fig.add_annotation(
                text="Select a regulator above to see per-pair scatter plots.",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
            )
            return ui.HTML(to_html(fig, include_plotlyjs=False, full_html=False))

        pair_data: list[tuple[str, str, str, str, Any]] = []
        failed_datasets: set[str] = set()
        succeeded_datasets: set[str] = set()

        for (db_a, db_b), (col_a, col_b, fa, fb, merged) in scatter_data.items():
            if merged.empty:
                failed_datasets.add(display_names.get(db_a, db_a))
                failed_datasets.add(display_names.get(db_b, db_b))
            else:
                succeeded_datasets.add(display_names.get(db_a, db_a))
                succeeded_datasets.add(display_names.get(db_b, db_b))
                pair_data.append((db_a, db_b, col_a, col_b, merged))

        plot_divs: list[ui.Tag] = []
        for db_a, db_b, col_a, col_b, merged in pair_data:
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
                    text=merged["target_locus_tag"],
                    hovertemplate=(
                        f"{la}: %{{x:.3f}}<br>" + f"{lb}: %{{y:.3f}}<extra></extra>"
                    ),
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
                title=dict(
                    text=f"{la}<br>vs<br>{lb}",
                    x=0.5,
                    xanchor="center",
                ),
                xaxis_title=f"{la}: {col_a}",
                yaxis_title=f"{lb}: {col_b}",
                margin=dict(l=50, r=20, t=100, b=50),
                width=400,
                height=400,
            )
            with profile_span(
                profile_logger,
                "plot.build",
                module="perturbation",
                context="regulator_plot",
                session_id=session_id,
            ):
                plot_html = to_html(fig, include_plotlyjs=False, full_html=False)
            plot_divs.append(
                ui.div(
                    ui.HTML(plot_html),
                    style="flex: 0 0 auto;",
                )
            )

        missing_note: list[ui.Tag] = []
        truly_missing = failed_datasets - succeeded_datasets
        if truly_missing:
            names = ", ".join(sorted(truly_missing))
            missing_note.append(
                ui.p(
                    f"{reg} was not found in: {names}. "
                    "Pairs involving these datasets are omitted.",
                    style="color: gray; font-style: italic; margin: 0.5rem 0;",
                )
            )

        logger.debug(
            f"regulator_plots built reg={reg!r} "
            f"pairs_total={len(scatter_data)} pairs_plotted={len(plot_divs)} "
            f"missing={sorted(truly_missing)}"
        )
        return ui.div(
            *missing_note,
            ui.div(
                *plot_divs,
                style="display: flex; flex-wrap: wrap; gap: 1rem; align-items: flex-start;",  # noqa: E501
            ),
        )


__all__ = ["perturbation_workspace_server"]
