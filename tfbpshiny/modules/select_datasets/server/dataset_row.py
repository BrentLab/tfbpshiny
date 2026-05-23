"""Dataset-row sub-module for the Select Datasets sidebar."""

from __future__ import annotations

from collections.abc import Callable
from logging import Logger
from typing import Any

import pandas as pd
from labretriever import ColumnMeta, VirtualDB
from shiny import module, reactive, ui
from shiny.types import SilentException

from tfbpshiny import components
from tfbpshiny.modules.select_datasets.queries import (
    metadata_query,
)
from tfbpshiny.modules.select_datasets.ui import (
    dataset_filter_modal_ui,
)
from tfbpshiny.utils.perf import perf, reset_render_counts
from tfbpshiny.utils.vdb_init import HIDDEN_FILTER_FIELDS, get_regulator_display_name


@module.ui
def dataset_row_ui(
    label: str,
    description: str,
    current_val: bool,
    is_collapsed: bool,
    has_active_filter: bool,
) -> ui.Tag:
    """
    Render one dataset row (toggle switch + optional filter button).

    :param label: Human-readable dataset name.
    :param description: Dataset description shown as a tooltip.
    :param current_val: Current toggle state.
    :param is_collapsed: When ``True``, renders only the toggle switch.
    :param has_active_filter: When ``True``, adds the active-filter CSS class to the
        filter button.

    """
    if is_collapsed:
        return ui.div(
            {"class": "dataset-row"},
            ui.input_switch("toggle", label=None, value=current_val),
        )
    label_span = ui.span({"class": "dataset-row-label sidebar-text"}, label)
    if description:
        label_span = components.tooltip(label_span, description, placement="right")
    return ui.div(
        {"class": "dataset-row"},
        ui.input_switch("toggle", label=label_span, value=current_val),
        ui.input_action_button(
            "filter_btn",
            "Filter",
            class_="btn-filter-dataset"
            + (" btn-filter-active" if has_active_filter else ""),
        ),
    )


@module.server
def dataset_row_server(
    input: Any,
    output: Any,
    session: Any,
    *,
    db_name: str,
    vdb: VirtualDB,
    dataset_dict: dict[str, dict[str, str]],
    all_col_meta: dict[str, dict[str, ColumnMeta]],
    common_fields: set[str],
    pending_toggle_state: reactive.Value[dict[str, bool]],
    pending_filters: reactive.Value[dict[str, Any]],
    modal_open_for: reactive.Value[str | None],
    modal_df: reactive.Value[pd.DataFrame | None],
    common_field_levels_fn: Callable[[], dict[str, list[str]]],
    meta_dfs_fn: Callable[[], dict[str, pd.DataFrame]],
    upstream_cols: list[str],
    modal_ns: Callable[[str], str],
    logger: Logger,
) -> None:
    """
    Register reactive effects for one dataset row.

    Writes to the shared ``pending_toggle_state``, ``pending_filters``,
    ``modal_open_for``, and ``modal_df`` reactive values provided by the parent
    module. Does not return anything; all communication with the parent is through
    those shared values.

    :param db_name: Dataset identifier — used as guard and dict key.
    :param vdb: VirtualDB instance for runtime queries.
    :param dataset_dict: Mapping of ``db_name`` to tag dict from the parent.
    :param all_col_meta: Per-column metadata keyed by ``db_name``.
    :param common_fields: Field names shared across all datasets.
    :param pending_toggle_state: Pending reactive dict of ``{db_name: bool}``.
    :param pending_filters: Pending reactive dict of active filters.
    :param modal_open_for: Shared reactive tracking which dataset's modal is open.
    :param modal_df: Shared reactive holding the open modal's metadata DataFrame.
    :param common_field_levels_fn: Callable returning the pre-computed union of
        categorical levels for each common field across all active datasets.
    :param meta_dfs_fn: Callable returning the cached unfiltered metadata
        DataFrames for all active datasets. Used to avoid a parquet scan on every
        modal open.
    :param upstream_cols: Column names that drive the cascade filter for this
        dataset. Pre-populated as initial ``selected=`` values in the modal so the
        cascade fires on first render without a post-render update.
    :param modal_ns: Namespace function from the parent module server
        (``session.ns``). Applied to all input IDs rendered inside the filter
        modal so they are registered under the parent's scope, not the row
        sub-module's scope.
    :param logger: Application logger.

    """

    session.on_flush(lambda: reset_render_counts(session.id))

    @reactive.effect
    def _sync_toggle_to_dom() -> None:
        """
        Keep the DOM switch in sync with ``pending_toggle_state`` so that programmatic
        activations (e.g. when the user applies filters to an off dataset) are reflected
        in the UI without requiring a full sidebar re-render.

        Uses a guard to avoid echoing back the value the user just set, which
        would trigger ``_on_toggle`` again unnecessarily.

        :trigger pending_toggle_state: fires whenever any dataset's toggle changes.

        """
        with perf(session.id, "select_datasets.dataset_row", "_sync_toggle_to_dom"):
            val = pending_toggle_state().get(db_name, False)
            with reactive.isolate():
                try:
                    current = bool(input.toggle())
                except SilentException:
                    return
            if current != val:
                ui.update_switch("toggle", value=val)

    @reactive.effect
    @reactive.event(input.toggle)
    def _on_toggle() -> None:
        """
        Update shared toggle state when the switch is flipped.

        Clears this dataset's filters when toggled off so the filter button
        returns to its inactive style and stale filters do not persist.

        The isolate guard prevents a reactive dependency on ``pending_toggle_state``
        itself and avoids a redundant write when ``ui.update_switch`` echoes
        the same value back.

        :trigger input.toggle: fires when the user flips this dataset's switch.

        """
        with perf(session.id, "select_datasets.dataset_row", "_on_toggle"):
            try:
                val = bool(input.toggle())
            except SilentException:
                return
            with reactive.isolate():
                if pending_toggle_state().get(db_name) == val:
                    return
            pending_toggle_state.set({**pending_toggle_state(), db_name: val})
            if not val:
                current = dict(pending_filters())
                current.pop(db_name, None)
                pending_filters.set(current)

    @reactive.effect
    @reactive.event(input.filter_btn)
    def _open_filter_modal() -> None:
        """
        Show the filter modal for this dataset.

        Uses the cached unfiltered metadata DataFrame from ``meta_dfs_fn`` to avoid
        a redundant parquet scan. Falls back to a live query for datasets not yet in
        the cache (e.g. toggled on but not yet committed). When existing filters are
        active, upstream categorical fields are pre-populated with the values that
        co-occur with those filters (inverse cascade), so the cascade renders
        correctly without a post-render update.

        :trigger input.filter_btn: fires when the user clicks the Filter button for
        this dataset.

        """
        with perf(session.id, "select_datasets.dataset_row", "_open_filter_modal"):
            existing_filters = pending_filters().get(db_name)

            df = meta_dfs_fn().get(db_name)
            if df is None:
                sql, params = metadata_query(db_name)
                df = vdb.query(sql, **params)

            modal_open_for.set(db_name)
            modal_df.set(df)

            # Infer upstream initial selections from the subset of the df that
            # matches existing filters, not the full unfiltered df. This ensures
            # that, e.g., opening the harbison modal with a YPD filter active shows
            # only "glucose" in Carbon source rather than all carbon sources.
            # Only runs when there are existing filters to infer from; if none
            # exist the upstream selectizes are left empty.
            augmented = dict(existing_filters or {})
            if existing_filters:
                mask = pd.Series(True, index=df.index)
                for fld, spec in existing_filters.items():
                    if fld not in df.columns:
                        continue
                    ftype = spec.get("type")
                    fval = spec.get("value")
                    if ftype == "categorical" and fval:
                        mask &= df[fld].astype(str).isin(fval)
                    elif (
                        ftype == "numeric"
                        and isinstance(fval, (list, tuple))
                        and len(fval) == 2
                    ):
                        lo, hi = float(fval[0]), float(fval[1])
                        mask &= (df[fld] >= lo) & (df[fld] <= hi)
                filtered_df = df[mask]
                for col in upstream_cols:
                    if col not in augmented and col in filtered_df.columns:
                        vals = filtered_df[col].dropna().astype(str).unique().tolist()
                        if vals:
                            augmented[col] = {
                                "type": "categorical",
                                "value": sorted(vals),
                            }

            # Build display_df: df filtered by the augmented upstream selections
            # so that condition checkboxes initially show only those conditions
            # that co-occur with the pre-selected upstream values. modal_df stays
            # as the full unfiltered df so the cascade can use it when the user
            # later changes an upstream selectize.
            upstream_mask = pd.Series(True, index=df.index)
            for col in upstream_cols:
                if col in augmented and col in df.columns:
                    vals = augmented[col].get("value", [])
                    if vals:
                        upstream_mask &= df[col].astype(str).isin(vals)
            display_df = df[upstream_mask]

            # If the upstream context didn't narrow the condition choices at
            # all (all rows still present — e.g. a dataset with a single
            # carbon source so every condition is "glucose"), fall back to
            # also applying the active condition-column filters from
            # ``augmented``. This prevents datasets whose upstream metadata
            # doesn't vary across conditions from showing every possible
            # condition at once.  Only applied when the result is non-empty,
            # so stale filter values can't produce a blank checkbox group.
            if len(display_df) == len(df) and augmented:
                _db_col_meta = all_col_meta.get(db_name, {})
                _cond_mask = pd.Series(True, index=display_df.index)
                _cond_applied = False
                for _col, _spec in augmented.items():
                    if _col not in display_df.columns:
                        continue
                    _cmeta = _db_col_meta.get(_col)
                    if (
                        _cmeta is None
                        or _cmeta.role != "experimental_condition"
                        or _cmeta.level_definitions is None
                    ):
                        continue
                    _fval = _spec.get("value", [])
                    if _spec.get("type") == "categorical" and _fval:
                        _cond_mask &= display_df[_col].astype(str).isin(_fval)
                        _cond_applied = True
                if _cond_applied:
                    _cond_filtered = display_df[_cond_mask]
                    if not _cond_filtered.empty:
                        display_df = _cond_filtered

            display_name = dataset_dict[db_name].get("display_name", db_name)
            common_field_levels = common_field_levels_fn()

            # build {locus_tag: display_name} map for regulator selectize;
            # use the pre-built in-memory table to avoid a second meta view scan.
            reg_display_labels: dict[str, str] = {}
            if "regulator_locus_tag" in df.columns:
                try:
                    tags = df["regulator_locus_tag"].dropna().unique().tolist()
                    if tags:
                        reg_df = get_regulator_display_name(vdb, tags)
                        reg_display_labels = dict(
                            zip(reg_df["regulator_locus_tag"], reg_df["display_name"])
                        )
                except Exception:
                    logger.exception(
                        "Failed to fetch regulator display labels for %s", db_name
                    )

            ui.modal_show(
                dataset_filter_modal_ui(
                    db_name,
                    display_df,
                    augmented if augmented else None,
                    common_fields,
                    display_name=display_name,
                    common_field_levels=common_field_levels,
                    hidden_fields=HIDDEN_FILTER_FIELDS.get("*", set())
                    | HIDDEN_FILTER_FIELDS.get(db_name, set()),
                    regulator_display_labels=reg_display_labels or None,
                    col_meta=all_col_meta.get(db_name) or None,
                    ns=modal_ns,
                )
            )


__all__ = ["dataset_row_ui", "dataset_row_server"]
