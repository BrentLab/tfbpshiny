"""Workspace server for the Comparison module."""

from __future__ import annotations

import asyncio
import functools
from logging import Logger
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from labretriever import VirtualDB
from plotly.io import to_html
from shiny import reactive, render, ui
from shiny.reactive import extended_task
from shiny.ui import bind_task_button, input_task_button  # noqa: F401

from tfbpshiny.components import sidebar_label
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
from tfbpshiny.utils.perf import perf, reset_render_counts
from tfbpshiny.utils.topn_matrix import build_topn_matrix_ui
from tfbpshiny.utils.vdb_init import (
    DEFAULT_RESPONSIVENESS_PRESET,
    DEFAULT_RESPONSIVENESS_PRESETS,
    get_regulator_display_name,
)

# ---------------------------------------------------------------------------
# Display-order constants
# ---------------------------------------------------------------------------

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

# Binding datasets that can appear in the Compare Methods tab.
_METHODS_ELIGIBLE: frozenset[str] = frozenset(PEAKS_VARIANT_MAP)

# Promoter tooltip text.
_PROMOTER_TOOLTIPS: dict[str, str] = {
    "Kang": "Promoter defined as 800 bp upstream of TSS (Kang et al. 2014)",
    "Mindel": (
        "Promoter defined as the intergenic region between adjacent genes "
        "upstream of TSS (Mindel et al. 2025)"
    ),
}


def _checkbox_group_with_disabled(
    input_id: str,
    choices: dict[str, str],
    selected: list[str],
    disabled: set[str],
) -> ui.Tag:
    """
    Build a checkbox group identical to ``ui.input_checkbox_group`` but with per-choice
    disabled support.

    Replicates Shiny's internal HTML structure (``name=input_id``,
    ``value=choice_value``, ``class="shiny-options-group"``), adding the
    HTML ``disabled`` attribute to any choice whose value is in ``disabled``.
    Disabled choices are also visually dimmed via inline opacity.

    :param input_id: The Shiny input ID (already namespaced by the caller).
    :param choices: Ordered ``{value: label}`` mapping.
    :param selected: Values that should be checked.
    :param disabled: Values that should be disabled (unchecked and non-interactive).
    :returns: A ``div.shiny-input-container`` tag matching Shiny's checkbox group.

    """
    option_tags: list[ui.Tag] = []
    for value, label in choices.items():
        is_disabled = value in disabled
        inp = ui.tags.input(
            type="checkbox",
            name=input_id,
            value=value,
            checked="checked" if (value in selected and not is_disabled) else None,
            disabled="disabled" if is_disabled else None,
        )
        option_tags.append(
            ui.div(
                ui.tags.label(
                    inp,
                    " ",
                    ui.span(label),
                    style="opacity: 0.45;" if is_disabled else None,
                ),
                class_="checkbox",
            )
        )
    return ui.div(
        ui.div(*option_tags, class_="shiny-options-group"),
        id=input_id,
        class_="shiny-input-checkboxgroup shiny-input-container",
    )


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
    """Render the Comparison workspace: Compare Datasets, Promoters, Methods."""

    session.on_flush(lambda: reset_render_counts(session.id))

    def _timed_render(label: str) -> Any:
        """
        Decorator that wraps a ``render`` function in a :func:`perf` timing block.

        Applied beneath ``@render.ui`` so the rendered output id (derived from the
        function name) is preserved via ``functools.wraps``.

        :param label: perf label for the render, e.g. ``"cd_matrix_container"``.

        """

        def deco(fn: Any) -> Any:
            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                with perf(session.id, "comparison.workspace", label):
                    return fn(*args, **kwargs)

            return wrapper

        return deco

    _available_datasets: frozenset[str] = frozenset(vdb.get_datasets())
    _mindel_dbs: frozenset[str] = (
        frozenset(PROMOTER_VARIANT_PAIRS.values()) & _available_datasets
    )

    _reg_df = get_regulator_display_name(vdb)
    _reg_labels: dict[str, str] = dict(
        zip(_reg_df["regulator_locus_tag"], _reg_df["display_name"])
    )

    display_names: dict[str, str] = {
        db: vdb.get_tags(db).get("display_name", db) for db in vdb.get_datasets()
    }

    # All primary binding datasets known to this VDB (excludes Mindel/peaks).
    _all_primary_binding: list[str] = sorted(
        db
        for db in vdb.get_datasets()
        if db in BINDING_CONFIGS
        and db not in _mindel_dbs
        and db not in frozenset().union(*PEAKS_VARIANT_MAP.values())
    )
    _all_perturbation: list[str] = sorted(
        db for db in vdb.get_datasets() if db in PERTURBATION_CONFIGS
    )

    # Selected row/column in the Compare Datasets matrix.
    cd_selected_binding: reactive.Value[str | None] = reactive.value(None)
    cd_selected_perturbation: reactive.Value[str | None] = reactive.value(None)

    # Snapshot of the sidebar inputs at the last successful Execute, keyed by
    # inner tab. Per-tab so that switching to an already-run tab (with no input
    # changes) does not falsely re-activate the Execute button — the single
    # shared snapshot used to mismatch because it embeds the active tab.
    _last_run_snapshot: reactive.Value[dict[str, tuple]] = reactive.value({})

    # True whenever results are out of date and Execute Analysis must be re-run.
    # Starts True (no run yet), set True when dataset_filters changes, False
    # only when a successful analysis result is cached.
    _results_stale: reactive.Value[bool] = reactive.value(True)

    # Per-tab result cache: stores the last successful _run_analysis result for
    # each inner tab so that switching back to a tab shows the previous results
    # without requiring a re-run.
    _tab_results: reactive.Value[dict[str, dict]] = reactive.value({})

    # Config-keyed result cache: maps a full sidebar-config key to the computed
    # _run_analysis result, so re-running an identical configuration (e.g.
    # toggling a dataset off then on, or revisiting a prior selection) returns
    # instantly without recomputing. The materialized data never changes at
    # runtime, so cached results stay valid; capped to bound memory.
    _config_cache: dict[tuple, dict] = {}
    _CONFIG_CACHE_MAX = 16

    # ---------------------------------------------------------------------------
    # Helper: derive active tab
    # ---------------------------------------------------------------------------

    def _inner_tab() -> str:
        try:
            return str(input.comparison_inner_tabs())
        except Exception:
            return "Compare Datasets"

    # ---------------------------------------------------------------------------
    # Snapshot
    # ---------------------------------------------------------------------------

    def _snapshot_current() -> tuple:
        """
        Return a hashable representation of the *active* subtab's inputs.

        Scoped to the current inner tab (plus the shared ``top_n`` and dataset
        filters) rather than every subtab's inputs. Shiny retains an input's
        value after its control is unmounted, so including the other subtabs'
        inputs made the snapshot change merely by visiting those subtabs — which
        falsely re-activated the Execute button on returning to an already-run
        subtab. Comparing only the active subtab's inputs keeps the pending
        state stable across subtab navigation.

        """
        try:
            filters_repr = repr(
                sorted((k, repr(v)) for k, v in dataset_filters().items())
            )
        except Exception:
            filters_repr = ""

        def _safe(fn: Any) -> Any:
            try:
                v = fn()
                if hasattr(v, "__iter__") and not isinstance(v, str):
                    return tuple(sorted(v))
                return v
            except Exception:
                return None

        tab = _inner_tab()
        base: tuple = (tab, input.top_n(), filters_repr)
        if tab == "Compare Datasets":
            return base + (
                _safe(input.cd_binding_method),
                _safe(input.cd_promoter_set),
                _safe(input.cd_included_binding),
                _safe(input.cd_included_perturbation),
            )
        if tab == "Compare Promoter Definitions":
            return base + (
                _safe(input.cp_included_binding),
                _safe(input.cp_included_perturbation),
                _safe(input.cp_included_promoter_sets),
            )
        if tab == "Compare Analysis Methods":
            return base + (
                _safe(input.cm_binding_dataset),
                _safe(input.cm_included_perturbation),
            )
        return base

    # ---------------------------------------------------------------------------
    # Gate tab
    # ---------------------------------------------------------------------------

    # ---------------------------------------------------------------------------
    # Staleness: mark results stale when committed dataset filters change
    # ---------------------------------------------------------------------------

    @reactive.effect
    def _mark_stale_on_filter_change() -> None:
        """
        Mark results stale whenever committed dataset filters change.

        Reads ``dataset_filters`` so this re-fires each time ``_apply_pending``
        commits a new filter state.  Uses ``reactive.isolate`` to set the flag
        without creating a circular dependency on ``_results_stale`` itself.

        :trigger dataset_filters: fires whenever Apply Changes is pressed in
            Select Datasets.

        """
        dataset_filters()
        with reactive.isolate():
            if not _results_stale():
                logger.debug("_mark_stale_on_filter_change: marking results stale")
                _results_stale.set(True)
                _last_run_snapshot.set({})
                _tab_results.set({})

    # ---------------------------------------------------------------------------
    # Pending button style
    # ---------------------------------------------------------------------------

    @output(suspend_when_hidden=False)
    @render.ui
    def execute_pending_style() -> ui.Tag:
        """
        Dims the Execute button when no changes are pending.

        :trigger _snapshot inputs: re-fires on any sidebar change. :trigger
        _last_run_snapshot: re-fires after Execute. :trigger _results_stale:
        re-fires when dataset filters change.

        """
        if _results_stale():
            return ui.span()
        current = _snapshot_current()
        last = _last_run_snapshot().get(_inner_tab())
        has_pending = (last is None) or (current != last)
        if has_pending:
            return ui.span()
        btn_id = session.ns("execute_analysis")
        return ui.tags.style(
            f"#{btn_id} {{ opacity: 0.35; pointer-events: none; cursor: not-allowed; }}"
        )

    # ---------------------------------------------------------------------------
    # Tab-specific sidebar controls
    # ---------------------------------------------------------------------------

    @render.ui
    def tab_specific_controls() -> ui.Tag:
        """
        Render sidebar controls appropriate for the active inner tab.

        :trigger input.comparison_inner_tabs: re-renders when the tab changes. :trigger
        active_binding_datasets: re-renders when dataset selection changes. :trigger
        active_perturbation_datasets: re-renders when dataset selection changes.

        """
        tab = _inner_tab()
        binding_primary = [
            db
            for db in active_binding_datasets()
            if db in BINDING_CONFIGS
            and db not in _mindel_dbs
            and db not in frozenset().union(*PEAKS_VARIANT_MAP.values())
        ]
        pert_dbs = [
            db for db in active_perturbation_datasets() if db in PERTURBATION_CONFIGS
        ]

        if tab == "Compare Datasets":
            try:
                cd_method = input.cd_binding_method()
            except Exception:
                cd_method = "Promoter Enrichment"
            peaks_only = cd_method == "Peaks"
            # Datasets that have no peaks variant are disabled when Peaks is selected.
            cd_disabled = (
                {db for db in binding_primary if db not in PEAKS_VARIANT_MAP}
                if peaks_only
                else set()
            )
            cd_selected = [db for db in binding_primary if db not in cd_disabled]
            return ui.div(
                sidebar_label("Binding Method"),
                ui.input_select(
                    "cd_binding_method",
                    label=None,
                    choices={
                        "Promoter Enrichment": "Promoter Enrichment",
                        "Peaks": "Peaks",
                    },
                    selected="Promoter Enrichment",
                ),
                sidebar_label("Promoter Set"),
                ui.input_select(
                    "cd_promoter_set",
                    label=None,
                    choices={"Kang": "Kang", "Mindel": "Mindel"},
                    selected="Kang",
                ),
                sidebar_label("Binding Datasets"),
                _checkbox_group_with_disabled(
                    input_id=session.ns("cd_included_binding"),
                    choices={
                        db: BINDING_LABEL_MAP.get(db, db) for db in binding_primary
                    },
                    selected=cd_selected,
                    disabled=cd_disabled,
                ),
                sidebar_label("Perturbation Datasets"),
                ui.input_checkbox_group(
                    "cd_included_perturbation",
                    label=None,
                    choices={db: PERTURBATION_LABEL_MAP.get(db, db) for db in pert_dbs},
                    selected=pert_dbs,
                ),
            )

        if tab == "Compare Promoter Definitions":
            # All primary binding (including harbison which has no Mindel variant).
            return ui.div(
                sidebar_label("Binding Datasets"),
                ui.input_checkbox_group(
                    "cp_included_binding",
                    label=None,
                    choices={
                        db: BINDING_LABEL_MAP.get(db, db) for db in binding_primary
                    },
                    selected=binding_primary,
                ),
                sidebar_label("Perturbation Datasets"),
                ui.input_checkbox_group(
                    "cp_included_perturbation",
                    label=None,
                    choices={db: PERTURBATION_LABEL_MAP.get(db, db) for db in pert_dbs},
                    selected=pert_dbs,
                ),
                sidebar_label("Promoter Sets"),
                ui.input_checkbox_group(
                    "cp_included_promoter_sets",
                    label=None,
                    choices={
                        ps: ui.tooltip(
                            ui.span(ps),
                            _PROMOTER_TOOLTIPS.get(ps, ps),
                            placement="right",
                        )
                        for ps in ("Kang", "Mindel")
                    },
                    selected=["Kang", "Mindel"],
                ),
            )

        if tab == "Compare Analysis Methods":
            eligible = [db for db in binding_primary if db in _METHODS_ELIGIBLE]
            method_choices = {db: BINDING_LABEL_MAP.get(db, db) for db in eligible}
            return ui.div(
                sidebar_label("Binding Dataset"),
                ui.input_select(
                    "cm_binding_dataset",
                    label=None,
                    choices=method_choices,
                    selected=next(iter(method_choices), None),
                ),
                sidebar_label("Perturbation Datasets"),
                ui.input_checkbox_group(
                    "cm_included_perturbation",
                    label=None,
                    choices={db: PERTURBATION_LABEL_MAP.get(db, db) for db in pert_dbs},
                    selected=pert_dbs,
                ),
            )

        return ui.span()

    # ---------------------------------------------------------------------------
    # Execute Analysis task
    # ---------------------------------------------------------------------------

    @bind_task_button(button_id="execute_analysis")
    @extended_task
    async def _run_analysis(
        tab: str,
        top_n: int,
        preset: dict,
        filters: dict,
        # Compare Datasets inputs
        cd_method: str,
        cd_promoter_set: str,
        cd_included_binding: list[str],
        cd_included_perturbation: list[str],
        # Compare Promoters inputs
        cp_included_binding: list[str],
        cp_included_perturbation: list[str],
        cp_included_promoter_sets: list[str],
        # Compare Methods inputs
        cm_binding_db: str | None,
        cm_included_perturbation: list[str],
    ) -> dict:
        """
        Compute top-N responsive ratios for the active inner tab, off the main thread.

        Each tab computes only what it needs; unused keys default to empty.

        :returns: Dict with keys ``tab``, ``cd_data``, ``cd_binding_datasets``,
            ``cd_perturbation_datasets``, ``cp_topn_data``,
            ``cp_included_promoter_sets``, ``cm_topn_data``, ``cm_binding_db``.

        """
        # Return a cached result when this exact configuration was already
        # computed (data is immutable at runtime, so the cache never goes stale).
        cache_key = (
            tab,
            top_n,
            repr(sorted((k, repr(v)) for k, v in filters.items())),
            repr(sorted((k, repr(v)) for k, v in preset.items())),
            cd_method,
            cd_promoter_set,
            tuple(cd_included_binding),
            tuple(cd_included_perturbation),
            tuple(cp_included_binding),
            tuple(cp_included_perturbation),
            tuple(cp_included_promoter_sets),
            cm_binding_db,
            tuple(cm_included_perturbation),
        )
        cached = _config_cache.get(cache_key)
        if cached is not None:
            return cached

        result: dict[str, Any] = {
            "tab": tab,
            "cd_data": pd.DataFrame(),
            "cd_binding_datasets": [],
            "cd_perturbation_datasets": [],
            "cp_topn_data": pd.DataFrame(),
            "cp_included_promoter_sets": cp_included_promoter_sets,
            "cm_topn_data": pd.DataFrame(),
            "cm_binding_db": cm_binding_db,
        }

        def _get_preset(db: str) -> tuple[float, float]:
            return preset.get(db, preset.get("*", (0.0, 0.05)))

        # ---- Compare Datasets ------------------------------------------------
        if (
            tab == "Compare Datasets"
            and cd_included_binding
            and cd_included_perturbation
        ):
            # Resolve each primary binding db to the correct variant db_name based
            # on method (Promoter Enrichment vs Peaks) and promoter set
            # (Kang vs Mindel).
            def _resolve_cd_db(b_db: str) -> str | None:
                if cd_method == "Peaks":
                    variants = PEAKS_VARIANT_MAP.get(b_db, [])
                    if not variants:
                        return None
                    # Prefer the Mindel peaks variant when Mindel is selected and
                    # a second entry exists; otherwise use the first (Kang) variant.
                    if cd_promoter_set == "Mindel" and len(variants) >= 2:
                        return variants[1]
                    return variants[0]
                else:
                    # Promoter Enrichment
                    if cd_promoter_set == "Mindel":
                        mindel = PROMOTER_VARIANT_PAIRS.get(b_db)
                        return (
                            mindel if mindel and mindel in _available_datasets else b_db
                        )
                    return b_db

            # Build (resolved_db, primary_db) pairs; skip any that can't be resolved.
            cd_resolved: list[tuple[str, str]] = [
                (resolved, b_db)
                for b_db in cd_included_binding
                for resolved in [_resolve_cd_db(b_db)]
                if resolved and resolved in BINDING_CONFIGS
            ]

            cd_pairs = [
                (resolved, p_db)
                for resolved, _ in cd_resolved
                for p_db in cd_included_perturbation
                if p_db in PERTURBATION_CONFIGS
            ]

            if cd_pairs:
                try:
                    with perf(
                        session.id,
                        "comparison.workspace",
                        "cd_topn_all_pairs_sql",
                        kind="data",
                    ):
                        raw = await asyncio.to_thread(
                            topn_all_pairs_sql, vdb, cd_pairs, filters, top_n, preset
                        )
                except Exception as exc:
                    logger.error("cd topn_all_pairs_sql failed: %s", exc, exc_info=True)
                    raw = pd.DataFrame()

                if not raw.empty and "pair_key" in raw.columns:
                    rows_: list[pd.DataFrame] = []
                    for resolved, b_db in cd_resolved:
                        for p_db in cd_included_perturbation:
                            pair_key = f"{resolved}__{p_db}"
                            sub = (
                                raw[raw["pair_key"] == pair_key]
                                .drop(columns=["pair_key"])
                                .reset_index(drop=True)
                                .copy()
                            )
                            if sub.empty:
                                continue
                            sub["binding_db"] = b_db
                            sub["binding_label"] = BINDING_LABEL_MAP.get(b_db, b_db)
                            sub["perturbation_db"] = p_db
                            sub["perturbation_source"] = PERTURBATION_LABEL_MAP.get(
                                p_db, p_db
                            )
                            sub["regulator_label"] = (
                                sub["regulator_locus_tag"]
                                .map(_reg_labels)
                                .fillna(sub["regulator_locus_tag"])
                            )
                            sub["percent_responsive"] = sub["responsive_ratio"] * 100
                            rows_.append(sub)
                    if rows_:
                        result["cd_data"] = pd.concat(rows_, ignore_index=True)

            result["cd_binding_datasets"] = [b_db for _, b_db in cd_resolved]
            result["cd_perturbation_datasets"] = list(cd_included_perturbation)

        # ---- Compare Promoters -----------------------------------------------
        if (
            tab == "Compare Promoter Definitions"
            and cp_included_binding
            and cp_included_perturbation
        ):
            expanded: list[str] = []
            for b_db in cp_included_binding:
                if "Kang" in cp_included_promoter_sets:
                    expanded.append(b_db)
                if "Mindel" in cp_included_promoter_sets:
                    mindel = PROMOTER_VARIANT_PAIRS.get(b_db)
                    if mindel and mindel in _available_datasets:
                        expanded.append(mindel)

            cp_pairs = [
                (b_db, p_db)
                for b_db in expanded
                if b_db in BINDING_CONFIGS
                for p_db in cp_included_perturbation
                if p_db in PERTURBATION_CONFIGS
            ]
            if cp_pairs:
                try:
                    with perf(
                        session.id,
                        "comparison.workspace",
                        "cp_topn_all_pairs_sql",
                        kind="data",
                    ):
                        raw = await asyncio.to_thread(
                            topn_all_pairs_sql, vdb, cp_pairs, filters, top_n, preset
                        )
                except Exception as exc:
                    logger.error("cp topn_all_pairs_sql failed: %s", exc, exc_info=True)
                    raw = pd.DataFrame()

                if not raw.empty and "pair_key" in raw.columns:
                    cp_rows_: list[pd.DataFrame] = []
                    for b_db in expanded:
                        for p_db in cp_included_perturbation:
                            pair_key = f"{b_db}__{p_db}"
                            sub = (
                                raw[raw["pair_key"] == pair_key]
                                .drop(columns=["pair_key"])
                                .reset_index(drop=True)
                                .copy()
                            )
                            if sub.empty:
                                continue
                            sub["binding_base_label"] = BINDING_BASE_LABEL_MAP.get(
                                b_db, b_db
                            )
                            sub["promoter_set"] = PROMOTER_SET_MAP.get(b_db, "Kang")
                            sub["perturbation_source"] = PERTURBATION_LABEL_MAP.get(
                                p_db, p_db
                            )
                            sub["regulator_label"] = (
                                sub["regulator_locus_tag"]
                                .map(_reg_labels)
                                .fillna(sub["regulator_locus_tag"])
                            )
                            sub["percent_responsive"] = sub["responsive_ratio"] * 100
                            cp_rows_.append(sub)
                    if cp_rows_:
                        result["cp_topn_data"] = pd.concat(cp_rows_, ignore_index=True)

        # ---- Compare Methods -------------------------------------------------
        if (
            tab == "Compare Analysis Methods"
            and cm_binding_db
            and cm_included_perturbation
        ):
            # All scoring variants for the selected binding dataset.
            peaks = [
                pk
                for pk in PEAKS_VARIANT_MAP.get(cm_binding_db, [])
                if pk in _available_datasets
            ]
            mindel = PROMOTER_VARIANT_PAIRS.get(cm_binding_db)
            mindel_peaks = (
                [
                    pk
                    for pk in PEAKS_VARIANT_MAP.get(mindel or "", [])
                    if mindel and pk in _available_datasets
                ]
                if mindel
                else []
            )
            all_method_dbs = (
                [cm_binding_db]
                + ([mindel] if mindel and mindel in _available_datasets else [])
                + peaks
                + mindel_peaks
            )
            all_method_dbs = [
                b
                for b in all_method_dbs
                if b in METHOD_BASE_LABEL_MAP and b in BINDING_CONFIGS
            ]

            cm_pairs = [
                (b_db, p_db)
                for b_db in all_method_dbs
                for p_db in cm_included_perturbation
                if p_db in PERTURBATION_CONFIGS
            ]
            if cm_pairs:
                try:
                    with perf(
                        session.id,
                        "comparison.workspace",
                        "cm_topn_all_pairs_sql",
                        kind="data",
                    ):
                        raw = await asyncio.to_thread(
                            topn_all_pairs_sql, vdb, cm_pairs, filters, top_n, preset
                        )
                except Exception as exc:
                    logger.error("cm topn_all_pairs_sql failed: %s", exc, exc_info=True)
                    raw = pd.DataFrame()

                if not raw.empty and "pair_key" in raw.columns:
                    cm_rows_: list[pd.DataFrame] = []
                    for b_db in all_method_dbs:
                        for p_db in cm_included_perturbation:
                            pair_key = f"{b_db}__{p_db}"
                            sub = (
                                raw[raw["pair_key"] == pair_key]
                                .drop(columns=["pair_key"])
                                .reset_index(drop=True)
                                .copy()
                            )
                            if sub.empty:
                                continue
                            sub["scoring_variant"] = SCORING_VARIANT_MAP.get(b_db, b_db)
                            sub["perturbation_source"] = PERTURBATION_LABEL_MAP.get(
                                p_db, p_db
                            )
                            sub["regulator_label"] = (
                                sub["regulator_locus_tag"]
                                .map(_reg_labels)
                                .fillna(sub["regulator_locus_tag"])
                            )
                            sub["percent_responsive"] = sub["responsive_ratio"] * 100
                            cm_rows_.append(sub)
                    if cm_rows_:
                        result["cm_topn_data"] = pd.concat(cm_rows_, ignore_index=True)

        _config_cache[cache_key] = result
        if len(_config_cache) > _CONFIG_CACHE_MAX:
            # Evict the oldest entry (dicts preserve insertion order).
            _config_cache.pop(next(iter(_config_cache)))
        return result

    # ---------------------------------------------------------------------------
    # Execute handler
    # ---------------------------------------------------------------------------

    @reactive.effect
    @reactive.event(input.execute_analysis)
    def _on_execute() -> None:
        """
        Collect sidebar state and invoke the analysis task.

        :trigger input.execute_analysis: fires when Execute Analysis is clicked.

        """
        tab = _inner_tab()
        top_n = input.top_n()
        preset = DEFAULT_RESPONSIVENESS_PRESETS.get(
            DEFAULT_RESPONSIVENESS_PRESET, {"*": (0.0, 0.05)}
        )
        filters = dataset_filters()

        def _safe_list(fn: Any, fallback: list) -> list:
            try:
                return list(fn() or [])
            except Exception:
                return fallback

        def _safe_str(fn: Any, fallback: str = "") -> str:
            try:
                return str(fn()) if fn() else fallback
            except Exception:
                return fallback

        binding_primary = [
            db
            for db in active_binding_datasets()
            if db in BINDING_CONFIGS
            and db not in _mindel_dbs
            and db not in frozenset().union(*PEAKS_VARIANT_MAP.values())
        ]
        pert_all = [
            db for db in active_perturbation_datasets() if db in PERTURBATION_CONFIGS
        ]

        cd_method = _safe_str(input.cd_binding_method, "Promoter Enrichment")
        cd_promoter_set = _safe_str(input.cd_promoter_set, "Kang")
        cd_included_binding = _safe_list(input.cd_included_binding, binding_primary)
        cd_included_perturbation = _safe_list(input.cd_included_perturbation, pert_all)

        cp_included_binding = _safe_list(input.cp_included_binding, binding_primary)
        cp_included_perturbation = _safe_list(input.cp_included_perturbation, pert_all)
        cp_included_promoter_sets = _safe_list(
            input.cp_included_promoter_sets, ["Kang", "Mindel"]
        )

        eligible = [db for db in binding_primary if db in _METHODS_ELIGIBLE]
        cm_binding_db = _safe_str(input.cm_binding_dataset)
        if not cm_binding_db and eligible:
            cm_binding_db = eligible[0]
        cm_included_perturbation = _safe_list(input.cm_included_perturbation, pert_all)

        _run_analysis.invoke(
            tab,
            top_n,
            preset,
            filters,
            cd_method,
            cd_promoter_set,
            cd_included_binding,
            cd_included_perturbation,
            cp_included_binding,
            cp_included_perturbation,
            cp_included_promoter_sets,
            cm_binding_db,
            cm_included_perturbation,
        )
        _last_run_snapshot.set({**_last_run_snapshot(), tab: _snapshot_current()})

    # ---------------------------------------------------------------------------
    # Status render
    # ---------------------------------------------------------------------------

    @output(suspend_when_hidden=False)
    @render.ui
    def analysis_status() -> ui.Tag:
        """:trigger _run_analysis.status: re-renders when the task state changes."""
        status = _run_analysis.status()
        if status == "running":
            return ui.div(
                {"class": "empty-state"},
                ui.p(
                    "Computing. This typically takes less than 5 seconds. "
                    "Thank you for your patience."
                ),
            )
        if status == "error":
            return ui.div(
                {"class": "empty-state"},
                ui.p(f"Error: {_run_analysis.error()}"),
            )
        return ui.span()

    # ---------------------------------------------------------------------------
    # Per-tab result cache
    # ---------------------------------------------------------------------------

    @reactive.effect
    def _cache_tab_result() -> None:
        """
        Store each successful task result in ``_tab_results`` keyed by tab name.

        :trigger _run_analysis.status: fires on every task status change.

        """
        if _run_analysis.status() != "success":
            return
        result = _run_analysis.result()
        tab = result.get("tab", "")
        if not tab:
            return
        with reactive.isolate():
            cache = dict(_tab_results())
        cache[tab] = result
        _tab_results.set(cache)
        _results_stale.set(False)

    # ---------------------------------------------------------------------------
    # Helper: table cell style
    # ---------------------------------------------------------------------------

    def _cell_style(val: float) -> str:
        """HSL green scale: 0% → white, 100% → full green."""
        clamped = max(0.0, min(100.0, val))
        lightness = 100 - clamped * 0.5
        return (
            f"background-color: hsl(120, 60%, {lightness:.0f}%);"
            " padding: 6px 10px; text-align: right;"
        )

    # ===========================================================================
    # Tab 1: Compare Datasets
    # ===========================================================================

    # All possible (b_db, p_db) combinations at init time for pre-registering effects.
    _all_cd_pairs: list[tuple[str, str]] = [
        (b_db, p_db) for b_db in _all_primary_binding for p_db in _all_perturbation
    ]

    def _make_cd_cell_effect(b_db: str, p_db: str) -> None:
        btn_id = f"topncell_{b_db}__{p_db}"

        @reactive.effect
        @reactive.event(input[btn_id])
        def _on_cell() -> None:
            cd_selected_binding.set(b_db)
            cd_selected_perturbation.set(None)

    def _make_cd_row_effect(b_db: str) -> None:
        btn_id = f"topnrow_{b_db}"

        @reactive.effect
        @reactive.event(input[btn_id])
        def _on_row() -> None:
            cd_selected_binding.set(b_db)
            cd_selected_perturbation.set(None)

    def _make_cd_col_effect(p_db: str) -> None:
        btn_id = f"topncol_{p_db}"

        @reactive.effect
        @reactive.event(input[btn_id])
        def _on_col() -> None:
            cd_selected_perturbation.set(p_db)
            cd_selected_binding.set(None)

    for _b, _p in _all_cd_pairs:
        _make_cd_cell_effect(_b, _p)
    for _b in _all_primary_binding:
        _make_cd_row_effect(_b)
    for _p in _all_perturbation:
        _make_cd_col_effect(_p)

    @output(suspend_when_hidden=False)
    @render.ui
    @_timed_render("cd_matrix_container")
    def cd_matrix_container() -> ui.Tag:
        """
        Binding × perturbation matrix with median % responsive in each cell.

        :trigger _tab_results: re-renders when cached Compare Datasets result updates.
        :trigger cd_selected_binding: re-renders to move row highlight. :trigger
        cd_selected_perturbation: re-renders to move column highlight.

        """
        if _results_stale():
            return ui.div(
                {"class": "empty-state"},
                ui.p("Click Execute Analysis to compute."),
            )
        result = _tab_results().get("Compare Datasets")
        if result is None:
            return ui.div(
                {"class": "empty-state"},
                ui.p("Click Execute Analysis to compute."),
            )

        cd_data: pd.DataFrame = result["cd_data"]
        b_datasets: list[str] = result["cd_binding_datasets"]
        p_datasets: list[str] = result["cd_perturbation_datasets"]

        if cd_data.empty or not b_datasets or not p_datasets:
            return ui.div(
                {"class": "empty-state"},
                ui.p("No data available for the selected datasets."),
            )

        # Build median lookup.
        topn_medians: dict[tuple[str, str], float | None] = {}
        for b_db in b_datasets:
            for p_db in p_datasets:
                sub = cd_data[
                    (cd_data["binding_db"] == b_db)
                    & (cd_data["perturbation_db"] == p_db)
                ]
                if sub.empty:
                    topn_medians[(b_db, p_db)] = None
                else:
                    per_reg = sub.groupby("regulator_locus_tag")[
                        "percent_responsive"
                    ].median()
                    topn_medians[(b_db, p_db)] = (
                        float(per_reg.median()) if not per_reg.empty else None
                    )

        return build_topn_matrix_ui(
            binding_datasets=b_datasets,
            perturbation_datasets=p_datasets,
            topn_medians=topn_medians,
            display_names=display_names,
            selected_binding=cd_selected_binding(),
            selected_perturbation=cd_selected_perturbation(),
            ns=session.ns,
        )

    @output(suspend_when_hidden=False)
    @render.ui
    @_timed_render("cd_distribution_container")
    def cd_distribution_container() -> ui.Tag:
        """
        One box plot per pair in the selected row or column.

        :trigger _tab_results: re-renders when cached Compare Datasets result updates.
        :trigger cd_selected_binding: re-renders when a row is selected. :trigger
        cd_selected_perturbation: re-renders when a column is selected.

        """
        # Unmount the box-plot figures when the Comparisons tab is not active so
        # they do not stay resident in the DOM (see binding pair_box_container).
        if (
            active_tab is not None
            and active_tab() != "Binding/Perturbation Comparisons"
        ):
            return ui.span()
        if _results_stale():
            return ui.span()
        result = _tab_results().get("Compare Datasets")
        if result is None or result["cd_data"].empty:
            return ui.span()

        b_sel = cd_selected_binding()
        p_sel = cd_selected_perturbation()

        if b_sel is None and p_sel is None:
            return ui.div(
                {"class": "empty-state"},
                ui.p(
                    "Click a row header to view distributions for a binding dataset,"
                    " or a column header to view distributions for a perturbation"
                    " dataset."
                ),
            )

        cd_data: pd.DataFrame = result["cd_data"]
        b_datasets: list[str] = result["cd_binding_datasets"]
        p_datasets: list[str] = result["cd_perturbation_datasets"]

        # Determine which pairs to display.
        if b_sel is not None:
            pairs = [(b_sel, p_db) for p_db in p_datasets]
            x_col = "perturbation_source"
        else:
            pairs = [(b_db, p_sel) for b_db in b_datasets]
            x_col = "binding_label"

        fig = go.Figure()
        for b_db, p_db in pairs:
            sub = cd_data[
                (cd_data["binding_db"] == b_db) & (cd_data["perturbation_db"] == p_db)
            ]
            if sub.empty:
                continue
            mask = sub["percent_responsive"].notna()
            fig.add_trace(
                go.Box(
                    x=sub.loc[mask, x_col].values,
                    y=sub.loc[mask, "percent_responsive"].values,
                    name=sub.loc[mask, x_col].iloc[0] if mask.any() else "",
                    text=sub.loc[mask, "regulator_label"].values,
                    hovertemplate="%{text}<br>%{y:.1f}%<extra></extra>",
                    hoveron="points",
                    boxpoints="all",
                    jitter=0.4,
                    pointpos=0,
                    marker=dict(size=4, opacity=0.5),
                    line=dict(width=1.5),
                    showlegend=False,
                )
            )

        if not fig.data:
            return ui.div(
                {"class": "empty-state"},
                ui.p("No data for the selected datasets."),
            )

        fig.update_yaxes(title_text="% responsive in top N", range=[0, 100])
        fig.update_layout(margin=dict(l=50, r=20, t=40, b=80))
        return ui.div(
            {"style": "margin-top: 1.5rem;"},
            ui.HTML(to_html(fig, include_plotlyjs=False, full_html=False)),
        )

    # ===========================================================================
    # Tab 2: Compare Promoter Definitions
    # ===========================================================================

    @output(suspend_when_hidden=False)
    @render.ui
    @_timed_render("cp_promoter_table")
    def cp_promoter_table() -> ui.Tag:
        """
        Promoter comparison tables, one per perturbation source.

        Rows = binding datasets (with Kang and/or Mindel variants). Columns = promoter
        sets selected. Values = median % responsive.

        :trigger _tab_results: re-renders when cached Compare Promoter Definitions
        result updates.

        """
        if _results_stale():
            return ui.div(
                {"class": "empty-state"},
                ui.p("Click Execute Analysis to compute."),
            )
        result = _tab_results().get("Compare Promoter Definitions")
        if result is None:
            return ui.div(
                {"class": "empty-state"},
                ui.p("Click Execute Analysis to compute."),
            )

        df: pd.DataFrame = result["cp_topn_data"]
        included_ps: list[str] = result["cp_included_promoter_sets"]

        if df.empty:
            return ui.div(
                {"class": "empty-state"},
                ui.p("No data available for the selected datasets."),
            )

        # Facet by perturbation source (one table per perturbation dataset).
        pert_sources = [
            p for p in _PERT_ORDER if p in df["perturbation_source"].unique()
        ]
        binding_base_labels = [
            b for b in _BINDING_ORDER if b in df["binding_base_label"].unique()
        ]

        _th_style = "padding: 6px 10px; text-align: right;"

        table_tags: list[ui.Tag] = []
        for pert_label in pert_sources:
            sub_p = df[df["perturbation_source"] == pert_label]
            if sub_p.empty:
                continue

            header_cells = [
                ui.tags.th(
                    "Binding Dataset", style="padding: 6px 10px; text-align: left;"
                ),
            ]
            for ps in included_ps:
                header_cells.append(ui.tags.th(ps, style=_th_style))

            data_rows: list[ui.Tag] = []
            for base_label in binding_base_labels:
                sub_b = sub_p[sub_p["binding_base_label"] == base_label]
                if sub_b.empty:
                    continue
                row_cells = [
                    ui.tags.td(
                        base_label,
                        style=(
                            "padding: 6px 10px; text-align: left; white-space: nowrap;"
                        ),
                    )
                ]
                for ps in included_ps:
                    sub_ps = sub_b[sub_b["promoter_set"] == ps]
                    if sub_ps.empty:
                        row_cells.append(
                            ui.tags.td(
                                "-", style="padding: 6px 10px; text-align: right;"
                            )
                        )
                    else:
                        per_reg = sub_ps.groupby("regulator_locus_tag")[
                            "percent_responsive"
                        ].median()
                        val = float(per_reg.median()) if not per_reg.empty else None
                        if val is not None and not pd.isna(val):
                            row_cells.append(
                                ui.tags.td(f"{val:.1f}%", style=_cell_style(val))
                            )
                        else:
                            row_cells.append(
                                ui.tags.td(
                                    "-", style="padding: 6px 10px; text-align: right;"
                                )
                            )
                data_rows.append(ui.tags.tr(*row_cells))

            if not data_rows:
                continue

            table_tags.append(
                ui.div(
                    {
                        "style": (
                            "flex: 1 1 0; border: 1px solid #ddd;"
                            " border-radius: 4px; overflow: hidden;"
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
                        pert_label,
                    ),
                    ui.tags.table(
                        {
                            "style": (
                                "border-collapse: collapse;"
                                " font-size: 0.9rem; width: 100%;"
                            )
                        },
                        ui.tags.thead(
                            {"style": "background-color: #f5f5f5;"},
                            ui.tags.tr(*header_cells),
                        ),
                        ui.tags.tbody(*data_rows),
                    ),
                )
            )

        if not table_tags:
            return ui.div(
                {"class": "empty-state"},
                ui.p(
                    "No promoter comparison data available for the selected datasets."
                ),
            )

        return ui.div(
            {
                "style": (
                    "display: flex; flex-wrap: wrap;"
                    " gap: 1.5rem; margin-top: 0.5rem;"
                )
            },
            *table_tags,
        )

    # ===========================================================================
    # Tab 3: Compare Analysis Methods
    # ===========================================================================

    @output(suspend_when_hidden=False)
    @render.ui
    @_timed_render("cm_method_table")
    def cm_method_table() -> ui.Tag:
        """
        Method comparison tables, one per perturbation source.

        Rows = scoring variants.  Values = median % responsive.

        :trigger _tab_results: re-renders when cached Compare Analysis Methods result
        updates.

        """
        if _results_stale():
            return ui.div(
                {"class": "empty-state"},
                ui.p("Click Execute Analysis to compute."),
            )
        result = _tab_results().get("Compare Analysis Methods")
        if result is None:
            return ui.div(
                {"class": "empty-state"},
                ui.p("Click Execute Analysis to compute."),
            )

        df: pd.DataFrame = result["cm_topn_data"]

        if df.empty:
            return ui.div(
                {"class": "empty-state"},
                ui.p(
                    "No method comparison data available. "
                    "Select a binding dataset with scoring variants"
                    " (ChIP-exo or ChEC-seq)."
                ),
            )

        pert_sources = [
            p for p in _PERT_ORDER if p in df["perturbation_source"].unique()
        ]
        variants_present = [
            v for v in SCORING_VARIANT_ORDER if v in df["scoring_variant"].unique()
        ]

        _th_style = "padding: 6px 10px; text-align: right;"

        table_tags: list[ui.Tag] = []
        for pert_label in pert_sources:
            sub_p = df[df["perturbation_source"] == pert_label]
            if sub_p.empty:
                continue

            header = ui.tags.tr(
                ui.tags.th(
                    "Scoring Variant", style="padding: 6px 10px; text-align: left;"
                ),
                ui.tags.th("Median % Responsive", style=_th_style),
            )

            data_rows: list[ui.Tag] = []
            for variant in variants_present:
                sub_v = sub_p[sub_p["scoring_variant"] == variant]
                if sub_v.empty:
                    continue
                per_reg = sub_v.groupby("regulator_locus_tag")[
                    "percent_responsive"
                ].median()
                val = float(per_reg.median()) if not per_reg.empty else None
                color = SCORING_VARIANT_COLORS.get(variant, "#888888")
                data_rows.append(
                    ui.tags.tr(
                        ui.tags.td(
                            ui.span(
                                {
                                    "style": (
                                        "display: inline-block; width: 10px;"
                                        " height: 10px; border-radius: 50%;"
                                        f" background: {color}; margin-right: 6px;"
                                    )
                                },
                            ),
                            variant,
                            style=(
                                "padding: 6px 10px; text-align: left;"
                                " white-space: nowrap;"
                            ),
                        ),
                        ui.tags.td(
                            (
                                f"{val:.1f}%"
                                if val is not None and not pd.isna(val)
                                else "-"
                            ),
                            style=(
                                _cell_style(val)
                                if val is not None and not pd.isna(val)
                                else "padding: 6px 10px; text-align: right;"
                            ),
                        ),
                    )
                )

            if not data_rows:
                continue

            table_tags.append(
                ui.div(
                    {
                        "style": (
                            "flex: 1 1 0; border: 1px solid #ddd;"
                            " border-radius: 4px; overflow: hidden; min-width: 280px;"
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
                        pert_label,
                    ),
                    ui.tags.table(
                        {
                            "style": (
                                "border-collapse: collapse;"
                                " font-size: 0.9rem; width: 100%;"
                            )
                        },
                        ui.tags.thead({"style": "background-color: #f5f5f5;"}, header),
                        ui.tags.tbody(*data_rows),
                    ),
                )
            )

        if not table_tags:
            return ui.div(
                {"class": "empty-state"},
                ui.p("No data for the selected datasets."),
            )

        return ui.div(
            {
                "style": (
                    "display: flex; flex-wrap: wrap;"
                    " gap: 1.5rem; margin-top: 0.5rem;"
                )
            },
            *table_tags,
        )


__all__ = ["comparison_workspace_server"]
