"""Sidebar server for the Select Datasets page — Phase 2 DuckDB version."""

from __future__ import annotations

import copy
from logging import Logger
from typing import Any

import duckdb
import pandas as pd
from shiny import reactive, render, ui
from shiny.types import SilentException

from tfbpshiny.components import export_download_button, export_instructions
from tfbpshiny.modules.select_datasets.export import (
    EXPORT_RUN_NAME_PLACEHOLDER,
    ExportDataset,
    build_export_archive,
    new_export_run_name,
)
from tfbpshiny.modules.select_datasets.queries import (
    FIELD_TYPE_OVERRIDES,
    full_data_query,
    metadata_query,
)
from tfbpshiny.modules.select_datasets.server.dataset_row import (
    dataset_row_server,
    dataset_row_ui,
)
from tfbpshiny.modules.select_datasets.ui import _slugify
from tfbpshiny.utils.vdb_init import DEFAULT_DATASET_FILTERS, AppDatasets


def _build_experimental_condition_field_choices(
    df: pd.DataFrame,
    mask: pd.Series,
    condition_cols: list[str],
) -> dict[str, dict[str, str]]:
    """
    Return condition column choices filtered by mask, sorted by descending count.

    :param df: Full metadata DataFrame for the dataset.
    :param mask: Boolean mask to apply before counting levels.
    :param condition_cols: Column names with role ``condition``.
    :returns: Dict mapping condition column name to ``{value: label}`` choices.

    """
    result: dict[str, dict[str, str]] = {}
    for cond_col in condition_cols:
        if cond_col not in df.columns:
            continue
        valid = (
            df.loc[mask, cond_col].dropna().astype(str).value_counts().index.tolist()
        )
        # Phase 2: no level_definitions — use raw values as both key and label
        result[cond_col] = {v: v for v in valid}
    return result


def select_datasets_sidebar_server(
    input: Any,
    output: Any,
    session: Any,
    conn: duckdb.DuckDBPyConnection,
    app_datasets: AppDatasets,
    logger: Logger,
) -> tuple[
    reactive.Calc_[list[str]],
    reactive.Calc_[list[str]],
    reactive.Value[dict[str, Any]],
]:
    """
    Render dataset selection sidebar; return (active_binding_datasets,
    active_perturbation_datasets, dataset_filters).

    The sidebar has two sections: "Binding" and "Perturbation".
    Datasets are sourced from the ``dataset_registry`` table.

    :param conn: Read-only DuckDB connection to the materialized database.
    :param app_datasets: Pre-loaded per-dataset column classification.
    :param logger: Application logger.

    """
    # Build dataset lookup from the materialized dataset_registry table.
    # Only show primary datasets (is_primary = TRUE) in the selector.
    _reg_df = conn.execute(
        "SELECT db_name, data_type, display_name, is_active_default "
        "FROM dataset_registry WHERE is_primary = TRUE"
    ).df()

    dataset_dict: dict[str, dict[str, Any]] = {}
    for _, row in _reg_df.iterrows():
        dataset_dict[str(row["db_name"])] = {
            "data_type": str(row["data_type"]),
            "display_name": str(row["display_name"]),
            "is_active_default": bool(row["is_active_default"]),
        }

    # Sorted lists of (db_name, display_name, description) for each data type.
    # description is not stored in dataset_registry; use empty string.
    binding_datasets: list[tuple[str, str, str]] = sorted(
        [
            (db_name, tags["display_name"], "")
            for db_name, tags in dataset_dict.items()
            if tags["data_type"] == "binding"
        ],
        key=lambda t: t[1],
    )
    perturbation_datasets: list[tuple[str, str, str]] = sorted(
        [
            (db_name, tags["display_name"], "")
            for db_name, tags in dataset_dict.items()
            if tags["data_type"] == "perturbation"
        ],
        key=lambda t: t[1],
    )

    # Common fields: upstream-role columns present in 2+ datasets.
    # These are eligible for "apply to all datasets" propagation.
    _col_df = conn.execute(
        "SELECT column_name, COUNT(DISTINCT db_name) AS n "
        "FROM dataset_column_metadata WHERE role = 'upstream' "
        "GROUP BY column_name HAVING COUNT(DISTINCT db_name) >= 2"
    ).df()
    common_fields: set[str] = set(_col_df["column_name"].tolist()) - {"sample_id"}

    _initial_toggle: dict[str, bool] = {
        db_name: bool(dataset_dict[db_name].get("is_active_default", False))
        for db_name, _, _ in binding_datasets + perturbation_datasets
    }

    # Two-state model: pending receives all user edits immediately; committed is
    # updated only when the user clicks Apply Changes. The Apply button is shown
    # whenever pending != committed.
    # {<db_name>: {<field_name>: {"type": "categorical" or "numeric" or "bool",
    #                              "value": list[str] | [lo, hi] | bool}}}
    # ``dataset_filters`` is the committed state — the only thing passed to
    # workspace/binding/perturbation/comparison, so it must never change except at
    # Apply Changes commit time (matching how ``_committed_toggle`` works).
    dataset_filters: reactive.Value[dict[str, Any]] = reactive.value(
        copy.deepcopy(DEFAULT_DATASET_FILTERS)
    )
    _committed_toggle: reactive.Value[dict[str, bool]] = reactive.value(_initial_toggle)
    _pending_toggle: reactive.Value[dict[str, bool]] = reactive.value(_initial_toggle)

    # Staged, not-yet-applied filter edits from the filter modal (Queue Filters /
    # Reset / Clear). Only holds entries that differ from ``dataset_filters()``,
    # keyed by db_name — an entry (even ``{}``) means "queued"; an absent key means
    # "no staged change, defer to the committed value". Committed into
    # ``dataset_filters`` (and cleared) when the user clicks Apply Changes, so
    # editing filters — even for an already-active dataset — never touches the
    # workspace/analysis modules until then.
    _pending_filters: reactive.Value[dict[str, dict[str, Any]]] = reactive.value({})

    # tracks which db_name's filter modal is currently open
    modal_open_for: reactive.Value[str | None] = reactive.value(None)
    # stores the DataFrame fetched when a filter modal is opened
    modal_df: reactive.Value[pd.DataFrame | None] = reactive.value(None)

    @reactive.calc
    def _has_pending_changes() -> bool:
        """
        True when the pending toggle state differs from the committed state, or there
        are staged (unapplied) filter edits.

        :trigger: ``_pending_toggle``, ``_committed_toggle``, ``_pending_filters``.

        """
        return _pending_toggle() != _committed_toggle() or bool(_pending_filters())

    @reactive.calc
    def _active_binding_datasets() -> list[str]:
        """
        Binding datasets currently committed (drives analysis).

        :trigger: ``_committed_toggle`` — re-runs when committed state changes.

        """
        state = _committed_toggle()
        return [db for db, _, _ in binding_datasets if state.get(db, False)]

    @reactive.calc
    def _active_perturbation_datasets() -> list[str]:
        """
        Perturbation datasets currently committed (drives analysis).

        :trigger: ``_committed_toggle`` — re-runs when committed state changes.

        """
        state = _committed_toggle()
        return [db for db, _, _ in perturbation_datasets if state.get(db, False)]

    def _all_active() -> list[str]:
        return _active_binding_datasets() + _active_perturbation_datasets()

    def _stage_filters(
        working: dict[str, dict[str, Any]], all_db_names: list[str]
    ) -> None:
        """
        Diff ``working`` against the committed ``dataset_filters`` and write the result
        to ``_pending_filters``.

        :param working: Full working copy of per-dataset filters (committed merged
            with the prior overlay, then mutated by the caller).
        :param all_db_names: Every registered dataset name, so entries that were
            cleared entirely (popped from ``working``) are still diffed against
            their committed value.

        """
        committed = dataset_filters()
        new_overlay: dict[str, dict[str, Any]] = {}
        for ds in set(all_db_names) | set(working) | set(committed):
            committed_val = committed.get(ds, {})
            new_val = working.get(ds, {})
            if new_val != committed_val:
                new_overlay[ds] = new_val
        _pending_filters.set(new_overlay)

    for db_name, _, _ in binding_datasets + perturbation_datasets:
        dataset_row_server(
            db_name,
            db_name=db_name,
            conn=conn,
            dataset_dict=dataset_dict,
            app_datasets=app_datasets,
            common_fields=common_fields,
            toggle_state=_pending_toggle,
            dataset_filters=dataset_filters,
            pending_filters=_pending_filters,
            modal_open_for=modal_open_for,
            modal_df=modal_df,
            active_datasets_fn=_all_active,
            modal_ns=session.ns,
            logger=logger,
        )

    # One-directional cascade: upstream categoricals narrow condition choices.
    for _db_name, _u_cols in app_datasets.upstream_cols.items():
        _cond_cols = app_datasets.condition_cols.get(_db_name, [])

        for _upstream_col in _u_cols:
            _u_id = f"filter_{_slugify(_upstream_col)}"

            def _register_upstream_cascade(
                db_name: str,
                u_id: str,
                u_col: str,
                cond_cols: list[str],
            ) -> None:
                """
                Register a cascade effect for one upstream column.

                :param db_name: Dataset identifier.
                :param u_id: Shiny input ID of the upstream selectize widget.
                :param u_col: Column name the upstream selectize controls.
                :param cond_cols: Condition column names to update.

                """

                @reactive.effect
                @reactive.event(input[u_id], ignore_init=True)
                def _cascade() -> None:
                    """
                    Narrow condition selectize choices to levels that co-occur with the
                    current upstream selection.

                    ``ignore_init=True`` because dynamically-inserted modal inputs send
                    their initial (empty) value to the server as soon as they're bound,
                    which would otherwise fire this cascade immediately on modal open —
                    before the user has touched anything.

                    :trigger: ``input[u_id]`` — fires when the upstream selectize
                        changes.

                    """
                    if modal_open_for() != db_name:
                        return
                    df = modal_df()
                    if df is None or u_col not in df.columns:
                        return
                    type_override = FIELD_TYPE_OVERRIDES.get(
                        (db_name, u_col)
                    ) or FIELD_TYPE_OVERRIDES.get(("", u_col))
                    override_kind = type_override[0] if type_override else None
                    col_dtype = df[u_col].dtype
                    is_categorical = (
                        override_kind == "categorical"
                        or col_dtype.name in ("object", "category")
                    )
                    if not is_categorical:
                        return
                    try:
                        sel = list(input[u_id]())
                    except SilentException:
                        sel = []
                    mask = (
                        df[u_col].isin(sel) if sel else pd.Series(True, index=df.index)
                    )
                    for (
                        cond_col,
                        choices,
                    ) in _build_experimental_condition_field_choices(
                        df, mask, cond_cols
                    ).items():
                        cond_id = f"filter_{_slugify(cond_col)}"
                        try:
                            cur = list(input[cond_id]())
                        except SilentException:
                            cur = list(choices)
                        ui.update_selectize(
                            cond_id,
                            choices=choices,
                            selected=[v for v in cur if v in choices],
                        )

            _register_upstream_cascade(_db_name, _u_id, _upstream_col, _cond_cols)

    @reactive.effect
    @reactive.event(input.modal_reset_filters)
    def _reset_filter_modal() -> None:
        """
        Stage clearing all filters for the open dataset and close the modal.

        Only ``_pending_filters`` is touched — the reset is not applied to
        ``dataset_filters`` until the user clicks Apply Changes.

        :trigger: ``input.modal_reset_filters`` — fires when the user clicks Reset
            inside the filter modal.

        """
        db_name = modal_open_for()
        if db_name is not None:
            all_db_names = [d for d, _, _ in binding_datasets + perturbation_datasets]
            current = dict(dataset_filters())
            current.update(_pending_filters())
            for ds in all_db_names:
                if ds in current:
                    ds_filters = {
                        f: v for f, v in current[ds].items() if f not in common_fields
                    }
                    if ds_filters:
                        current[ds] = ds_filters
                    else:
                        current.pop(ds, None)
            current.pop(db_name, None)
            _stage_filters(current, all_db_names)
            logger.debug(
                "filters reset (staged) for %s: %d datasets with active filters",
                db_name,
                len(current),
            )
        ui.modal_remove()
        modal_open_for.set(None)
        modal_df.set(None)

    @reactive.effect
    @reactive.event(input.modal_clear_regulator_filter)
    def _clear_regulator_filter() -> None:
        """
        Stage removal of regulator_locus_tag from all datasets and clear the selectize.

        Only ``_pending_filters`` is touched — the clear is not applied to
        ``dataset_filters`` until the user clicks Apply Changes.

        :trigger: ``input.modal_clear_regulator_filter`` — fires when the user
            clicks Clear inside the Regulator card.

        """
        db_name = modal_open_for()
        if db_name is None:
            return
        all_db_names = [d for d, _, _ in binding_datasets + perturbation_datasets]
        current = dict(dataset_filters())
        current.update(_pending_filters())
        for ds in all_db_names:
            ds_filters = dict(current.get(ds, {}))
            ds_filters.pop("regulator_locus_tag", None)
            if ds_filters:
                current[ds] = ds_filters
            else:
                current.pop(ds, None)
        _stage_filters(current, all_db_names)
        ui.update_selectize("filter_regulator_locus_tag", selected=[])

    @reactive.effect
    @reactive.event(input.modal_apply_filters)
    def _apply_filter_modal() -> None:
        """
        Read filter inputs from the modal and stage them to ``_pending_filters``, mark
        the dataset pending-active if it was off, then close the modal.

        Only ``_pending_filters`` is touched here — staged edits are not applied to
        ``dataset_filters`` (and so cannot affect the workspace/analysis modules)
        until the user clicks Apply Changes.

        :trigger: ``input.modal_apply_filters`` — fires when the user clicks
            Queue Filters inside the filter modal.

        """
        db_name = modal_open_for()
        df = modal_df()
        if db_name is None or df is None:
            ui.modal_remove()
            return

        field_filters: dict[str, Any] = {}
        for field in df.columns:
            if field == "sample_id":
                continue

            col = df[field]
            try:
                value = input[f"filter_{_slugify(field)}"]()
            except SilentException:
                continue

            type_override = FIELD_TYPE_OVERRIDES.get(
                (db_name, field)
            ) or FIELD_TYPE_OVERRIDES.get(("", field))
            override_kind = type_override[0] if type_override else None

            if override_kind == "categorical" or col.dtype.name in (
                "object",
                "category",
            ):
                selected = list(value) if value else []
                if selected:
                    field_filters[field] = {"type": "categorical", "value": selected}

            elif col.dtype == "bool":
                if bool(value):
                    field_filters[field] = {"type": "bool", "value": True}

            elif col.dtype.name in ("float64", "int64", "float32", "int32"):
                if isinstance(value, (list, tuple)) and len(value) == 2:
                    non_null = col.dropna()
                    if non_null.empty:
                        continue
                    data_min = float(non_null.min())
                    data_max = float(non_null.max())
                    if data_min == data_max:
                        continue
                    s_min, s_max = float(value[0]), float(value[1])
                    if s_min != data_min or s_max != data_max:
                        field_filters[field] = {
                            "type": "numeric",
                            "value": [s_min, s_max],
                        }

            if field in common_fields and field in field_filters:
                try:
                    apply_to_all = bool(input[f"apply_to_all_{_slugify(field)}"]())
                except SilentException:
                    apply_to_all = False
                field_filters[field]["apply_to_all"] = apply_to_all

        # handle regulator_locus_tag explicitly
        try:
            reg_selected = list(input["filter_regulator_locus_tag"]())
        except SilentException:
            reg_selected = []
        try:
            reg_apply_to_all = bool(input["apply_to_all_regulator_locus_tag"]())
        except SilentException:
            reg_apply_to_all = True
        merged = dict(dataset_filters())
        merged.update(_pending_filters())

        if reg_selected:
            saved_reg = merged.get(db_name, {}).get("regulator_locus_tag", {})
            from_pair = saved_reg.get("from_pair") if saved_reg else None
            reg_spec: dict[str, Any] = {
                "type": "categorical",
                "value": reg_selected,
                "apply_to_all": reg_apply_to_all,
            }
            if from_pair:
                reg_spec["from_pair"] = from_pair
            field_filters["regulator_locus_tag"] = reg_spec

        reg_filter = field_filters.pop("regulator_locus_tag", None)
        common_filters = {f: v for f, v in field_filters.items() if f in common_fields}
        specific_filters = {
            f: v for f, v in field_filters.items() if f not in common_fields
        }

        current = dict(merged)
        all_db_names = [d for d, _, _ in binding_datasets + perturbation_datasets]

        if reg_filter:
            if reg_filter.get("apply_to_all", True):
                for ds in all_db_names:
                    ds_filters = dict(current.get(ds, {}))
                    ds_filters["regulator_locus_tag"] = reg_filter
                    current[ds] = ds_filters
            else:
                for ds in all_db_names:
                    ds_filters = dict(current.get(ds, {}))
                    if ds == db_name:
                        ds_filters["regulator_locus_tag"] = reg_filter
                    else:
                        ds_filters.pop("regulator_locus_tag", None)
                    if ds_filters:
                        current[ds] = ds_filters
                    else:
                        current.pop(ds, None)
        else:
            for ds in all_db_names:
                ds_filters = dict(current.get(ds, {}))
                ds_filters.pop("regulator_locus_tag", None)
                if ds_filters:
                    current[ds] = ds_filters
                else:
                    current.pop(ds, None)

        for f, spec in common_filters.items():
            apply_to_all = spec.get("apply_to_all", True)
            if apply_to_all:
                for ds in all_db_names:
                    ds_filters = dict(current.get(ds, {}))
                    ds_filters[f] = spec
                    current[ds] = ds_filters
            else:
                for ds in all_db_names:
                    ds_filters = dict(current.get(ds, {}))
                    if ds == db_name:
                        ds_filters[f] = spec
                    else:
                        ds_filters.pop(f, None)
                    if ds_filters:
                        current[ds] = ds_filters
                    else:
                        current.pop(ds, None)

        for f in common_fields:
            if f not in common_filters:
                prev_spec = current.get(db_name, {}).get(f)
                prev_apply_to_all = (
                    prev_spec.get("apply_to_all", False) if prev_spec else False
                )
                targets = all_db_names if prev_apply_to_all else [db_name]
                for ds in targets:
                    ds_filters = dict(current.get(ds, {}))
                    ds_filters.pop(f, None)
                    if ds_filters:
                        current[ds] = ds_filters
                    else:
                        current.pop(ds, None)

        ds_filters = dict(current.get(db_name, {}))
        ds_filters.update(specific_filters)
        for f in list(ds_filters):
            if f not in common_fields and f not in specific_filters:
                ds_filters.pop(f)
        if ds_filters:
            current[db_name] = ds_filters
        else:
            current.pop(db_name, None)

        _stage_filters(current, all_db_names)
        logger.debug(
            "filters queued for %s: %d fields set",
            db_name,
            len(ds_filters),
        )

        if not _pending_toggle().get(db_name, False):
            _pending_toggle.set({**_pending_toggle(), db_name: True})

        ui.modal_remove()
        modal_open_for.set(None)
        modal_df.set(None)

    # Holds the run name generated by `_export_filename` so the handler below
    # can reuse it as the in-archive directory prefix. Shiny's download
    # endpoint calls `filename` immediately before `handler` for the same
    # request (see shiny.session._session's download GET handling), so this
    # is safe despite not being a reactive value.
    _export_run_name: list[str] = []

    def _export_filename() -> str:
        run_name = new_export_run_name()
        _export_run_name[:] = [run_name]
        return f"{run_name}.tar.gz"

    @render.download(
        filename=_export_filename,
        media_type="application/gzip",
    )
    def export_datasets():
        """
        Build and stream a .tar.gz export kit for all active datasets.

        The kit contains the VirtualDB config, a generated fetch_data.py
        script (embedding each active dataset's SQL + params), requirements.txt,
        and a top-level README -- no data is queried server-side.

        :trigger: ``input.export_datasets`` — fires when the user clicks the
            Export Selected Datasets download button.

        """
        all_active = _active_binding_datasets() + _active_perturbation_datasets()
        if not all_active:
            return

        filters = dataset_filters()

        export_list: list[ExportDataset] = []
        for db_name in all_active:
            display_name = dataset_dict[db_name].get("display_name", db_name)
            meta_sql, meta_params = metadata_query(db_name, filters.get(db_name))
            data_sql, data_params = full_data_query(db_name, filters.get(db_name))

            export_list.append(
                ExportDataset(
                    db_name=db_name,
                    display_name=display_name,
                    metadata_sql=meta_sql,
                    metadata_params=meta_params,
                    data_sql=data_sql,
                    data_params=data_params,
                )
            )

        run_name = _export_run_name[0] if _export_run_name else new_export_run_name()
        try:
            buf = build_export_archive(export_list, run_name=run_name)
        except Exception:
            logger.exception("Export archive build failed")
            return

        while chunk := buf.read(65536):
            yield chunk

    @reactive.effect
    @reactive.event(input.apply_pending)
    def _apply_pending() -> None:
        """
        Commit pending toggle state and staged filter edits, triggering analysis updates
        exactly once.

        Filters for any dataset newly deactivated by this commit are cleared here
        rather than immediately on toggle, so that flipping a switch off and back
        on before clicking Apply Changes leaves its filters untouched.

        :trigger: ``input.apply_pending`` — fires when the user clicks Apply Changes.

        """
        pending = _pending_toggle()
        committed = _committed_toggle()
        deactivated = [
            db
            for db, was_on in committed.items()
            if was_on and not pending.get(db, False)
        ]

        committed_filters = dataset_filters()
        merged = dict(committed_filters)
        merged.update(_pending_filters())
        for db_name in deactivated:
            merged.pop(db_name, None)
        if merged != committed_filters:
            dataset_filters.set(merged)
        _pending_filters.set({})

        _committed_toggle.set(pending)
        logger.debug(
            "_apply_pending committed: %d datasets active",
            sum(pending.values()),
        )

    @render.ui
    def sidebar_content() -> ui.Tag:
        """
        Dataset rows for the selection sidebar with Apply Changes button.

        :trigger: ``input.search`` — re-renders when the search input changes.
        :trigger: ``_pending_toggle`` — re-renders when any toggle changes.
        :trigger: ``dataset_filters`` — re-renders when filters are committed
            (Apply Changes).
        :trigger: ``_pending_filters`` — re-renders when filters are staged
            (Queue Filters / Reset / Clear in the filter modal).

        Toggle state is read with ``reactive.isolate()`` so that toggling a
        dataset does NOT trigger a full sidebar re-render.

        """
        pending_toggle = _pending_toggle()
        merged_filters = dict(dataset_filters())
        merged_filters.update(_pending_filters())
        active_filter_names: set[str] = {
            db
            for db in merged_filters
            if pending_toggle.get(db, False) and merged_filters.get(db)
        }
        has_pending = _has_pending_changes()
        has_active = bool(_active_binding_datasets() or _active_perturbation_datasets())

        search_term = ""
        try:
            search_term = (input.search() or "").strip().lower()
        except SilentException:
            pass

        def _dataset_row(db_name: str, label: str, description: str) -> ui.Tag:
            with reactive.isolate():
                current_val = _pending_toggle().get(db_name, False)
                committed_val = _committed_toggle().get(db_name, False)
            return dataset_row_ui(
                db_name,
                label=label,
                description=description,
                current_val=current_val,
                is_collapsed=False,
                has_active_filter=db_name in active_filter_names,
                is_committed=committed_val,
            )

        section_tags: list[ui.Tag] = []

        visible_binding = [
            (db_name, label, desc)
            for db_name, label, desc in binding_datasets
            if not search_term or search_term in label.lower()
        ]
        if visible_binding:
            section_tags.append(
                ui.div({"class": "group-header sidebar-text"}, "Binding")
            )
            for db_name, label, desc in visible_binding:
                section_tags.append(_dataset_row(db_name, label, desc))

        visible_perturbation = [
            (db_name, label, desc)
            for db_name, label, desc in perturbation_datasets
            if not search_term or search_term in label.lower()
        ]
        if visible_perturbation:
            section_tags.append(
                ui.div({"class": "group-header sidebar-text"}, "Perturbation")
            )
            for db_name, label, desc in visible_perturbation:
                section_tags.append(_dataset_row(db_name, label, desc))

        if not section_tags:
            section_tags.append(
                ui.div(
                    {"class": "empty-state compact"},
                    ui.p("No datasets match your search."),
                )
            )

        banner = (
            ui.div(
                {"class": "pending-banner"},
                "Dataset selection has changed. Click Apply Changes to update.",
            )
            if has_pending
            else ui.span()
        )

        footer_tags: list[ui.Tag] = []
        if has_active:
            footer_tags.append(
                ui.div(
                    {"class": "sidebar-footer"},
                    export_instructions(EXPORT_RUN_NAME_PLACEHOLDER),
                    export_download_button("export_datasets"),
                )
            )

        return ui.div(
            ui.h2("Select datasets for analysis"),
            banner,
            ui.input_action_button(
                "apply_pending",
                "Apply Changes",
                class_="btn-apply-pending"
                + ("" if has_pending else " btn-apply-pending--idle"),
            ),
            ui.div({"class": "dataset-list"}, *section_tags),
            *footer_tags,
        )

    return _active_binding_datasets, _active_perturbation_datasets, dataset_filters


__all__ = ["select_datasets_sidebar_server"]
