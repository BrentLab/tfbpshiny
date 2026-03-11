"""Sidebar server for the Select Datasets page."""

from __future__ import annotations

import hashlib
from logging import Logger
from typing import Any

import faicons as fa
import pandas as pd
from shiny import module, reactive, render, ui
from tfbpapi import VirtualDB

from tfbpshiny.modules.select_datasets.queries import metadata_query
from tfbpshiny.modules.select_datasets.ui import dataset_filter_modal_ui


def _toggle_id(db_name: str) -> str:
    digest = hashlib.sha1(db_name.encode()).hexdigest()[:10]
    return f"ds_toggle_{digest}"


def _filter_btn_id(db_name: str) -> str:
    digest = hashlib.sha1(db_name.encode()).hexdigest()[:10]
    return f"ds_filter_{digest}"


@module.server
def selection_sidebar_server(
    input: Any,
    output: Any,
    session: Any,
    vdb: VirtualDB,
    logger: Logger,
) -> tuple[
    reactive.calc[list[str]],
    reactive.calc[list[str]],
    reactive.Value[dict[str, Any]],
]:
    """
    Render dataset selection sidebar; return (active_binding_datasets,
    active_perturbation_datasets, filter_dict).

    The sidebar has two sections: "Binding" and "Perturbation".
    Datasets are sourced from VirtualDB tags (data_type, display_name).

    """

    # dataset dict is structure
    # {<db_name>: {"data_type": "binding" or "perturbation",
    #              "display_name": str,
    #              "assay": str}, ...}
    dataset_dict: dict[str, dict[str, str]] = {}
    for db_name in vdb.get_datasets():
        tags = vdb.get_tags(db_name)
        if tags.get("data_type") in ["binding", "perturbation"]:
            dataset_dict[db_name] = tags

    # list of (db_name, display_name) tuples for the binding and perturbation sections
    binding_datasets: list[tuple[str, str]] = [
        (db_name, tags.get("display_name", db_name))
        for db_name, tags in dataset_dict.items()
        if tags.get("data_type") == "binding"
    ]
    perturbation_datasets: list[tuple[str, str]] = [
        (db_name, tags.get("display_name", db_name))
        for db_name, tags in dataset_dict.items()
        if tags.get("data_type") == "perturbation"
    ]
    # there are some common fields across datasets. In the dataset filters,
    # these common fields are displayed in their own section of the modal, and when
    # they are set on any dataset, they are applied to all datasets.
    common_fields = set(vdb.get_common_fields()) - {"sample_id"}

    # reactives
    collapsed: reactive.Value[bool] = reactive.value(False)
    # {<db_name>: {<field_name>: {"type": "categorical" or "numeric" or "bool",
    #                              "value": list[str] | [lo, hi] | bool}}}
    filter_dict: reactive.Value[dict[str, Any]] = reactive.value({})
    # tracks which db_name's filter modal is currently open
    modal_open_for: reactive.Value[str | None] = reactive.value(None)
    # stores the DataFrame fetched when a filter modal is opened
    modal_df: reactive.Value[pd.DataFrame | None] = reactive.value(None)

    # expand/collapse sidebar
    @reactive.effect
    @reactive.event(input.toggle_sidebar)
    def _toggle_sidebar() -> None:
        collapsed.set(not collapsed())

    @reactive.calc
    def active_binding_datasets() -> list[str]:
        """Return the list of currently active binding datasets based on the
        select_dataset sidebar toggles for the binding section."""
        selected = []
        for db_name, _ in binding_datasets:
            try:
                if bool(input[_toggle_id(db_name)]()):
                    selected.append(db_name)
            except Exception:
                pass
        return selected

    @reactive.calc
    def active_perturbation_datasets() -> list[str]:
        """Return the list of currently active perturbation datasets based on the
        select_dataset sidebar toggles for the perturbation section."""
        selected = []
        for db_name, _ in perturbation_datasets:
            try:
                if bool(input[_toggle_id(db_name)]()):
                    selected.append(db_name)
            except Exception:
                pass
        return selected

    # TODO: remove this and log it where active_perturbation_datasets
    # and active_binding_datasets are used
    @reactive.effect
    def _log_active_datasets() -> None:
        logger.info(
            f"Active datasets - Binding: {active_binding_datasets()}, "
            f"Perturbation: {active_perturbation_datasets()}"
        )

    for _db_name, _ in binding_datasets + perturbation_datasets:

        def _make_filter_effect(db_name: str) -> None:
            @reactive.effect
            @reactive.event(input[_filter_btn_id(db_name)])
            def _open_filter_modal() -> None:
                existing_filters = filter_dict().get(db_name)
                sql, params = metadata_query(db_name, existing_filters)
                df = vdb.query(sql, **params)
                modal_open_for.set(db_name)
                modal_df.set(df)
                ui.modal_show(
                    dataset_filter_modal_ui(
                        db_name, df, existing_filters, common_fields
                    )
                )

        _make_filter_effect(_db_name)

    @reactive.effect
    @reactive.event(input.modal_reset_filters)
    def _reset_filter_modal() -> None:
        db_name = modal_open_for()
        if db_name is not None:
            current = dict(filter_dict())
            all_db_names = [d for d, _ in binding_datasets + perturbation_datasets]
            # clear common-field filters from every dataset
            for ds in all_db_names:
                if ds in current:
                    ds_filters = {
                        f: v for f, v in current[ds].items() if f not in common_fields
                    }
                    if ds_filters:
                        current[ds] = ds_filters
                    else:
                        current.pop(ds)
            # clear dataset-specific filters for the open dataset
            current.pop(db_name, None)
            filter_dict.set(current)
        ui.modal_remove()
        modal_open_for.set(None)
        modal_df.set(None)

    @reactive.effect
    @reactive.event(input.modal_apply_filters)
    def _apply_filter_modal() -> None:
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
                value = input[f"filter_{field}"]()
            except Exception:
                continue

            if col.dtype == "bool":
                if bool(value):
                    field_filters[field] = {"type": "bool", "value": True}

            elif col.dtype.name in ("object", "category"):
                selected = list(value) if value else []
                if selected:
                    field_filters[field] = {"type": "categorical", "value": selected}

            elif col.dtype.name in ("float64", "int64", "float32", "int32"):
                if isinstance(value, (list, tuple)) and len(value) == 2:
                    non_null = col.dropna()
                    if non_null.empty:
                        continue
                    data_min = float(non_null.min())
                    data_max = float(non_null.max())
                    s_min, s_max = float(value[0]), float(value[1])
                    if s_min != data_min or s_max != data_max:
                        field_filters[field] = {
                            "type": "numeric",
                            "value": [s_min, s_max],
                        }

        # split into common-field filters (apply to all datasets) and dataset-specific
        common_filters = {f: v for f, v in field_filters.items() if f in common_fields}
        specific_filters = {
            f: v for f, v in field_filters.items() if f not in common_fields
        }

        current = dict(filter_dict())
        all_db_names = [d for d, _ in binding_datasets + perturbation_datasets]

        # apply common filters to every dataset
        for ds in all_db_names:
            ds_filters = dict(current.get(ds, {}))
            # clear stale common-field entries then write new ones
            for f in common_fields:
                ds_filters.pop(f, None)
            ds_filters.update(common_filters)
            if ds_filters:
                current[ds] = ds_filters
            else:
                current.pop(ds, None)

        # apply dataset-specific filters to just this dataset
        ds_filters = dict(current.get(db_name, {}))
        ds_filters.update(specific_filters)
        # remove any specific fields that are no longer set
        for f in list(ds_filters):
            if f not in common_fields and f not in specific_filters:
                ds_filters.pop(f)
        if ds_filters:
            current[db_name] = ds_filters
        else:
            current.pop(db_name, None)

        filter_dict.set(current)

        ui.modal_remove()
        modal_open_for.set(None)
        modal_df.set(None)

    # add dynamic dataset selection/filter UI to sidebar
    @render.ui
    def sidebar_panel() -> ui.Tag:
        is_collapsed = collapsed()

        search_term = ""
        if not is_collapsed:
            try:
                search_term = (input.search() or "").strip().lower()
            except Exception:
                pass

        def _dataset_row(db_name: str, label: str) -> ui.Tag:
            if is_collapsed:
                return ui.div(
                    {"class": "dataset-row"},
                    ui.input_switch(_toggle_id(db_name), label=None, value=False),
                )
            return ui.div(
                {"class": "dataset-row"},
                ui.input_switch(
                    _toggle_id(db_name),
                    label=ui.span({"class": "dataset-row-label sidebar-text"}, label),
                    value=False,
                ),
                ui.input_action_button(
                    _filter_btn_id(db_name),
                    "Filter",
                    class_="btn-filter-dataset",
                ),
            )

        section_tags: list[ui.Tag] = []

        visible_binding = [
            (db_name, label)
            for db_name, label in binding_datasets
            if not search_term or search_term in label.lower()
        ]
        if visible_binding:
            if not is_collapsed:
                section_tags.append(
                    ui.div({"class": "group-header sidebar-text"}, "Binding")
                )
            for db_name, label in visible_binding:
                section_tags.append(_dataset_row(db_name, label))

        visible_perturbation = [
            (db_name, label)
            for db_name, label in perturbation_datasets
            if not search_term or search_term in label.lower()
        ]
        if visible_perturbation:
            if not is_collapsed:
                section_tags.append(
                    ui.div({"class": "group-header sidebar-text"}, "Perturbation")
                )
            for db_name, label in visible_perturbation:
                section_tags.append(_dataset_row(db_name, label))

        if not section_tags:
            section_tags.append(
                ui.div(
                    {"class": "empty-state compact"},
                    ui.p("No datasets match your search."),
                )
            )

        return ui.div(
            {
                "class": "context-sidebar selection-sidebar"
                + (" collapsed" if is_collapsed else ""),
                "id": "selection-sidebar",
            },
            ui.div(
                {"class": "sidebar-header"},
                ui.div(
                    {"class": "sidebar-header-row"},
                    (
                        ui.div(
                            ui.h2("Select datasets\nfor analysis"),
                        )
                        if not is_collapsed
                        else ui.div(ui.h2("SD"))
                    ),
                    ui.input_action_button(
                        "toggle_sidebar",
                        (
                            fa.icon_svg("angles-left", width="14px", height="14px")
                            if not is_collapsed
                            else fa.icon_svg(
                                "angles-right", width="14px", height="14px"
                            )
                        ),
                        class_="btn-collapse-sidebar",
                    ),
                ),
            ),
            ui.div(
                {"class": "sidebar-body"},
                ui.div({"class": "dataset-list"}, *section_tags),
            ),
        )

    return active_binding_datasets, active_perturbation_datasets, filter_dict


__all__ = ["selection_sidebar_server"]
