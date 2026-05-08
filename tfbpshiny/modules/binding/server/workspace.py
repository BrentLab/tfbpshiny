from __future__ import annotations

import itertools
from collections.abc import Callable
from html import escape
from logging import Logger
from typing import Any, Literal

import pandas as pd
import plotly.graph_objects as go
from labretriever import VirtualDB
from plotly.io import to_html
from shiny import module, reactive, render, req, ui

from tfbpshiny.modules.binding.queries import (
    corr_all_pairs_sql,
    get_measurement_column,
    regulator_scatter_sql,
)
from tfbpshiny.utils.perf import perf, reset_render_counts
from tfbpshiny.utils.ratelimit import debounce
from tfbpshiny.utils.sample_conditions import fetch_sample_condition_map
from tfbpshiny.utils.vdb_init import AppDatasets, get_regulator_display_name


@module.server
def binding_workspace_server(
    input: Any,
    output: Any,
    session: Any,
    active_binding_datasets: reactive.Calc_[list[str]],
    corr_type: Callable[[], str],
    col_preference: Callable[[], str],
    dataset_filters: reactive.Value[dict[str, Any]],
    vdb: VirtualDB,
    app_datasets: AppDatasets,
    logger: Logger,
    active_module: reactive.Value[str] | None = None,
) -> None:
    """
    Render the binding correlation rows: pairwise distributions
    and per-regulator plots.
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

    @reactive.calc
    def _condition_maps() -> dict[str, dict[str, str]]:
        """
        ``{db_name: {sample_id: label}}`` for each active dataset that has
        experimental_condition columns.

        Used to annotate tooltips on the selected-regulator overlay in the
        distribution plot so the user can distinguish multiple samples of the
        same regulator. Datasets without ``condition_cols`` are omitted from
        the outer dict, causing the tooltip to skip their side.

        :trigger active_binding_datasets: re-runs when the user toggles a
            binding dataset on or off.
        :returns: Outer dict keyed by db_name; inner dict maps sample_id to
            the joined condition label.

        """
        if active_module is not None:
            req(active_module() == "binding")
        with perf(session.id, "binding.workspace", "_condition_maps"):
            out: dict[str, dict[str, str]] = {}
            for db in active_binding_datasets():
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
        All unique pairs of active binding datasets.

        Raises ``SilentException`` when the binding tab is not active, which
        propagates through ``_all_corr_data`` without creating a direct dependency
        on ``active_module`` inside the expensive calc.

        :trigger active_binding_datasets: re-runs whenever the user toggles a
            binding dataset on or off in the Select Datasets sidebar.
        :trigger active_module: silently blocks when another tab is active.
        :returns: List of ``(db_a, db_b)`` tuples, length = n_active choose 2.

        """
        if active_module is not None:
            req(active_module() == "binding")
        with perf(session.id, "binding.workspace", "_pairs"):
            active = active_binding_datasets()
            pairs = list(itertools.combinations(sorted(active), 2))
            logger.debug(f"binding _pairs: active={active}, pairs={pairs}")
            return pairs

    @debounce(0.3)
    @reactive.calc
    def _all_corr_data() -> dict[tuple[str, str], pd.DataFrame]:
        """
        Per-regulator correlation values for every active dataset pair.

        The heart of this function is a for loop over the dataset pairs. In each
        iteration, the user selected measurement column (effect or p-value),
        filters for that dataset, and the correlation method (pearson or spearman) are
        submitted along with the virtualDB instance to `corr_pair_sql()`
        (see queries.py), which uses the duckDB aggregate functions to compute
        correlations. The join is done on (regulator_locus_tag, target_locus_tag).
        NOTE: if there are multiple samples for a given regulator_locus_tag, then
        there will be multiple correlation values for that regulator in the output
        dataframe.

        :trigger _pairs: re-runs when the set of active pairs changes; silently
            blocked when the binding tab is not active via ``_pairs``.
        :trigger col_preference: re-runs when the user switches between Effect
            and P-value columns.
        :trigger corr_type: re-runs when the user switches between Pearson and
            Spearman.
        :trigger dataset_filters: re-runs when filters are applied or reset for
            any dataset.
        :returns: a dict with keys ``(db_a, db_b)`` and values a dataframe
            with columns ``db_a``, ``db_a_id``, ``db_b``, ``db_b_id``,
            ``regulator_locus_tag`` and ``correlation``. Failed pairs are stored as
            empty DataFrames so downstream renders can handle them gracefully. The
            failure and error are logged at the ERROR level.

        """
        with perf(session.id, "binding.workspace", "_all_corr_data"):
            pairs = _pairs()
            # TODO: get rid of the type ignore
            preference: Literal["effect", "pvalue"] = col_preference()  # type: ignore[assignment] # noqa: E501
            method = corr_type()
            filters = dataset_filters()

            if not pairs:
                return {}

            col_map = {
                db: get_measurement_column(db, preference)
                for pair in pairs
                for db in pair
            }
            logger.debug(f"binding _all_corr_data: {len(pairs)} pairs, method={method}")

            try:
                combined = corr_all_pairs_sql(vdb, pairs, col_map, filters, method)
            except Exception as exc:
                logger.error(f"corr_all_pairs_sql failed: {exc}", exc_info=True)
                combined = pd.DataFrame(
                    columns=[
                        "db_a",
                        "db_a_id",
                        "db_b",
                        "db_b_id",
                        "regulator_locus_tag",
                        "correlation",
                        "pair_key",
                    ]
                )

            empty_cols = [
                "db_a",
                "db_a_id",
                "db_b",
                "db_b_id",
                "regulator_locus_tag",
                "correlation",
            ]
            result: dict[tuple[str, str], pd.DataFrame] = {}
            for db_a, db_b in pairs:
                key = f"{db_a}__{db_b}"
                if combined.empty or "pair_key" not in combined.columns:
                    result[(db_a, db_b)] = pd.DataFrame(columns=empty_cols)
                else:
                    subset = (
                        combined[combined["pair_key"] == key]
                        .drop(columns=["pair_key"])
                        .reset_index(drop=True)
                    )
                    result[(db_a, db_b)] = subset

            return result

    @render.ui
    def distributions_plot() -> ui.Tag:
        """
        Box-plot of per-regulator correlation values for every active pair.

        :trigger _pairs: re-renders when the set of active pairs changes. :trigger
        _all_corr_data: re-renders when correlation data is recomputed. :trigger
        corr_type: re-renders when the correlation method changes     (updates the
        axis/title label).

        """
        pairs = _pairs()
        corr_data = _all_corr_data()
        method = corr_type().capitalize()

        fig = go.Figure()

        if not pairs:
            fig.add_annotation(
                text="Select at least two binding datasets to see correlations.",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
            )
            return fig

        # sym_map is built at server init from the pre-computed lookup table
        try:
            selected_reg = str(input.selected_regulator())
        except Exception:
            selected_reg = ""

        cond_maps = _condition_maps()

        # Build a single combined box trace using x as the category axis.
        # Each point's x value is the pair label; Plotly groups points under
        # each category and draws one box per unique x value.
        all_x: list[str] = []
        all_y: list[float] = []
        all_tags: list[str] = []
        all_hover: list[str] = []
        sel_x: list[str] = []
        sel_y: list[float] = []
        sel_hover: list[str] = []
        sel_tags: list[str] = []
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
                    if tag == selected_reg:
                        sel_x.append(pair_label)
                        sel_y.append(corr)
                        # Per-dot hover: regulator + r + one condition line per
                        # dataset that has a non-empty label for this sample.
                        # All DB-sourced strings are HTML-escaped before being
                        # joined with the <br> separators because Plotly renders
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
                        sel_hover.append("<br>".join(hover_lines))
                        sel_tags.append(tag)

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

        if sel_x:
            fig.add_trace(
                go.Scatter(
                    x=sel_x,
                    y=sel_y,
                    mode="markers",
                    hovertext=sel_hover,
                    customdata=sel_tags,
                    hovertemplate="%{hovertext}<extra></extra>",
                    marker=dict(size=10, color="black", symbol="circle"),
                    showlegend=False,
                )
            )

        fig.update_layout(
            title=f"{method} correlation across regulators",
            yaxis_title=f"{method} r",
            showlegend=False,
            margin=dict(l=40, r=20, t=50, b=80),
        )
        input_id = session.ns("selected_regulator")
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
        return ui.HTML(
            to_html(
                fig,
                include_plotlyjs="cdn",
                full_html=False,
                post_script=post_script,
            )
        )

    @render.ui
    def regulator_selector() -> ui.Tag:
        """
        Dropdown of regulators present in at least one pair's correlation data.

        Choices are keyed by locus tag and labelled by gene symbol where available. The
        previously selected regulator is preserved across re-renders if it is still
        present in the new choice set.

        :trigger _all_corr_data: re-renders when correlation data changes (new
        datasets selected, filters applied, or column/method changed). :trigger
        active_binding_datasets: re-renders to refresh the symbol map     when the
        active dataset set changes.

        """
        corr_data = _all_corr_data()
        if not corr_data:
            return ui.span()

        # sym_map is built at server init from the pre-computed lookup table
        all_regs: set[str] = set()
        for df in corr_data.values():
            if not df.empty:
                all_regs |= set(df["regulator_locus_tag"].dropna().unique())

        if not all_regs:
            return ui.span()
        choices = {r: sym_map.get(r, r) for r in all_regs}
        choices = dict(sorted(choices.items(), key=lambda kv: kv[1].lower()))

        try:
            current = str(input.selected_regulator())
        except Exception:
            current = ""
        default = current if current in choices else next(iter(choices))

        return ui.input_selectize(
            "selected_regulator",
            "Regulator",
            choices=choices,
            selected=default,
        )

    # All possible pairs across the full dataset catalogue — fixed at init time.
    # Used to pre-register one @render.ui per pair so each scatter plot resolves
    # independently without triggering a full-page re-render.
    _all_possible_pairs: list[tuple[str, str]] = list(
        itertools.combinations(
            sorted(
                db
                for db in vdb.get_datasets()
                if vdb.get_tags(db).get("data_type") == "binding"
            ),
            2,
        )
    )

    @render.ui
    def scatter_container() -> ui.Tag:
        """
        Flex container with one output slot per currently active pair.

        Only re-renders when the active pair set changes — not when plot data or the
        selected regulator changes. Each slot is filled independently by its own per-
        pair render.

        :trigger _pairs: re-renders when the active dataset set changes.

        """
        active_pairs = _pairs()
        if not active_pairs:
            return ui.span()
        slots = [
            ui.output_ui(f"scatter_{db_a}__{db_b}")
            for db_a, db_b in _all_possible_pairs
            if (db_a, db_b) in active_pairs
        ]
        return ui.div(
            ui.output_ui("scatter_missing_note"),
            ui.div(
                *slots,
                style="display: flex; flex-wrap: wrap; gap: 1rem; align-items: flex-start;",  # noqa: E501
            ),
        )

    @render.ui
    def scatter_missing_note() -> ui.Tag:
        """
        Warning paragraph listing datasets where the selected regulator was not found.

        :trigger input.selected_regulator: re-renders when the regulator changes.
        :trigger _all_corr_data: re-renders when dataset/filter/method changes.

        """
        try:
            reg = str(input.selected_regulator()) or None
        except Exception:
            reg = None
        if not reg:
            return ui.span()
        active_pairs = _pairs()
        corr_data = _all_corr_data()
        failed: set[str] = set()
        succeeded: set[str] = set()
        for db_a, db_b in active_pairs:
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

        All arguments are captured by value via the function signature so each closure
        refers to its own pair and index, not the loop variables at fire time.

        :param db_a: First dataset name.
        :param db_b: Second dataset name.
        :param pair_idx: Stable integer index used to namespace SQL parameters.

        """

        @output(id=f"scatter_{db_a}__{db_b}")
        @render.ui
        def _scatter_plot() -> ui.Tag:
            """
            Scatter plot for one (db_a, db_b) pair.

            Returns an empty span when this pair is not currently active so the slot
            takes no space in the DOM.

            :trigger input.selected_regulator: re-renders when the regulator changes.
            :trigger _all_corr_data: re-renders when dataset/filter/method changes.

            """
            active_pairs = _pairs()
            if (db_a, db_b) not in active_pairs:
                return ui.span()

            try:
                reg = str(input.selected_regulator()) or None
            except Exception:
                reg = None

            if not reg:
                return ui.span()

            # TODO: get rid of the type ignore
            preference: Literal["effect", "pvalue"] = col_preference()  # type: ignore[assignment] # noqa: E501
            filters = dataset_filters()
            method = corr_type()

            def _strip_reg(f: dict | None) -> dict | None:
                if not f:
                    return f
                stripped = {k: v for k, v in f.items() if k != "regulator_locus_tag"}
                return stripped or None

            try:
                col_a = get_measurement_column(db_a, preference)
                col_b = get_measurement_column(db_b, preference)
                fa = _strip_reg(filters.get(db_a))
                fb = _strip_reg(filters.get(db_b))
                scatter_sql, scatter_params = regulator_scatter_sql(
                    db_a,
                    col_a,
                    fa,
                    db_b,
                    col_b,
                    fb,
                    method,
                    reg,
                    pair_idx,
                )
                merged = vdb.query(scatter_sql, **scatter_params)
                logger.debug(f"scatter {db_a}/{db_b} reg={reg!r} rows={len(merged)}")
            except Exception:
                logger.exception(f"Scatter fetch failed for {db_a}/{db_b}")
                return ui.span()

            if merged.empty:
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
                title=dict(text=f"{la}<br>vs<br>{lb}", x=0.5, xanchor="center"),
                xaxis_title=f"{la}: {col_a}",
                yaxis_title=f"{lb}: {col_b}",
                margin=dict(l=50, r=20, t=100, b=50),
                width=400,
                height=400,
            )
            return ui.div(
                ui.HTML(to_html(fig, include_plotlyjs=False, full_html=False)),
                style="flex: 0 0 auto;",
            )

    for _pair_idx, (_db_a, _db_b) in enumerate(_all_possible_pairs, start=1):
        _make_scatter_render(_db_a, _db_b, _pair_idx)


__all__ = ["binding_workspace_server"]
