"""Sidebar server for the Select Datasets page."""

from __future__ import annotations

import hashlib
from logging import Logger
from typing import Any

import faicons as fa
from shiny import module, reactive, render, ui
from tfbpapi import VirtualDB


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
    reactive.Value[str | None], reactive.calc[list[str]], reactive.calc[list[str]]
]:
    """
    Render dataset selection sidebar; return (filter_modal_open_for,
    active_binding_datasets, active_perturbation_datasets).

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

    # reactives
    collapsed: reactive.Value[bool] = reactive.value(False)
    filter_modal_open_for: reactive.Value[str | None] = reactive.value(None)
    filter_click_counts: reactive.Value[dict[str, int]] = reactive.value({})

    # expand/collapse sidebar
    @reactive.effect
    @reactive.event(input.toggle_sidebar)
    def _toggle_sidebar() -> None:
        collapsed.set(not collapsed())

    # these reactive functions return the set of selected binding and perturbation
    # datasets based on the state of the toggle switches in the sidebar
    @reactive.calc
    def active_binding_datasets() -> list[str]:
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

    # TODO: implement filter modal
    @reactive.effect
    def _watch_filter_buttons() -> None:
        current_counts = dict(filter_click_counts())
        for db_name, _ in binding_datasets + perturbation_datasets:
            btn_id = _filter_btn_id(db_name)
            try:
                clicks = int(input[btn_id]())
            except Exception:
                continue
            prev = int(current_counts.get(db_name, 0))
            if clicks > prev:
                current_counts[db_name] = clicks
                filter_click_counts.set(current_counts)
                filter_modal_open_for.set(db_name)
                return

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

    return filter_modal_open_for, active_binding_datasets, active_perturbation_datasets


__all__ = ["selection_sidebar_server"]
