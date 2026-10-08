"""Workspace server for the Select Datasets page."""

from __future__ import annotations

import json
from logging import Logger
from typing import Any

import duckdb
import pandas as pd
from shiny import reactive, render, ui
from shiny.types import SilentException

from tfbpshiny.components import (
    matrix_cell,
    matrix_cell_button,
    matrix_header_cell,
    matrix_row_label,
    matrix_table,
)
from tfbpshiny.modules.select_datasets.queries import (
    regulator_breakdown_query,
    regulator_conditions_query,
    regulator_locus_tags_query,
    sample_count_query,
)
from tfbpshiny.modules.select_datasets.ui import (
    diagonal_cell_modal_ui,
    off_diagonal_cell_modal_ui,
    regulator_cell_modal_ui,
)
from tfbpshiny.utils.vdb_init import HIDDEN_FILTER_FIELDS


def select_datasets_workspace_server(
    input: Any,
    output: Any,
    session: Any,
    active_binding_datasets: reactive.Calc_[list[str]],
    active_perturbation_datasets: reactive.Calc_[list[str]],
    dataset_filters: reactive.Value[dict[str, Any]],
    conn: duckdb.DuckDBPyConnection,
    logger: Logger,
) -> None:
    """
    Render the sample-count matrix for all active datasets.

    :param active_binding_datasets: Reactive calc returning active binding db names.
    :param active_perturbation_datasets: Reactive calc returning active perturbation db
        names.
    :param dataset_filters: Reactive value with per-dataset filter specs.
    :param conn: Read-only DuckDB connection to the materialized database.
    :param logger: Application logger.

    """
    # Build display-name lookup from dataset_registry.
    _display_df = conn.execute(
        "SELECT db_name, display_name FROM dataset_registry"
    ).df()
    display_names: dict[str, str] = dict(
        zip(_display_df["db_name"], _display_df["display_name"])
    )

    # Preload all registered db_names for broadcasting regulator filters.
    _all_db_names: list[str] = (
        conn.execute("SELECT db_name FROM dataset_registry").df()["db_name"].tolist()
    )

    @reactive.calc
    def _settled_datasets() -> list[str]:
        """
        Combined list of all active datasets.

        Dataset selection only changes when the user clicks Apply Changes (see
        ``sidebar.py::_apply_pending``), so no additional debouncing is needed here.

        :trigger: ``active_binding_datasets``, ``active_perturbation_datasets`` —
            re-runs whenever either list changes.
        :returns: Concatenated list of active db_name strings, binding first.

        """
        return active_binding_datasets() + active_perturbation_datasets()

    def _candidate_condition_columns(db_name: str) -> list[str]:
        """
        Non-identity, non-regulator, non-hidden columns from a dataset's meta table.

        :param db_name: Dataset to inspect.
        :returns: Column names eligible to display as sample "conditions".

        """
        try:
            all_cols_df = conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = ? ORDER BY ordinal_position",
                [f"{db_name}_meta"],
            ).df()
            all_cols = all_cols_df["column_name"].tolist()
        except Exception:
            return []

        remove_cols = (
            {"sample_id"}
            | {c for c in all_cols if c.lower().startswith("regulator")}
            | HIDDEN_FILTER_FIELDS.get("*", set())
            | HIDDEN_FILTER_FIELDS.get(db_name, set())
        )
        return [c for c in all_cols if c not in remove_cols]

    @reactive.calc
    def _matrix_data() -> dict[str, Any]:
        """
        Compute per-dataset regulator/sample counts and pairwise common-regulator
        counts.

        :trigger: ``_settled_datasets`` — re-runs when the active dataset set changes.
        :trigger: ``dataset_filters`` — re-runs when any filter changes.
        :returns: Dict with keys ``"diagonal"`` — ``{db_name: {"regulators": int,
            "samples": int}}``; ``"cross_dataset"`` — ``{(db_i, db_j):
            {"common_regulators": int, "samples_a": int, "samples_b": int}}``;
            ``"regulator_sets"`` — ``{db_name: set[locus_tag]}``;
            ``"regulator_symbols"`` — ``{locus_tag: symbol}`` union across all
            active datasets.

        """
        active = _settled_datasets()
        filters = dataset_filters()

        regulator_sets: dict[str, set[str]] = {}
        regulator_symbols: dict[str, str] = {}
        diagonal: dict[str, dict[str, int]] = {}

        for db_name in active:
            db_filters = filters.get(db_name)

            sql, params = regulator_locus_tags_query(db_name, db_filters)
            reg_df = conn.execute(sql, params).df()
            reg_df = reg_df.dropna(subset=["regulator_locus_tag"])
            regulators = set(reg_df["regulator_locus_tag"].astype(str))
            regulator_sets[db_name] = regulators
            for locus_tag, symbol in zip(
                reg_df["regulator_locus_tag"].astype(str), reg_df["regulator_symbol"]
            ):
                if locus_tag not in regulator_symbols:
                    regulator_symbols[locus_tag] = (
                        str(symbol) if pd.notna(symbol) else locus_tag
                    )

            sql, params = sample_count_query(db_name, db_filters)
            n_samples = int(conn.execute(sql, params).df().iloc[0, 0])

            diagonal[db_name] = {"regulators": len(regulators), "samples": n_samples}

        cross_dataset: dict[tuple[str, str], dict[str, int]] = {}

        for i, db_a in enumerate(active):
            for db_b in active[i + 1 :]:
                common = regulator_sets[db_a] & regulator_sets[db_b]
                common_list = list(common)

                sql_a, params_a = sample_count_query(
                    db_a, filters.get(db_a), restrict_to_regulators=common_list
                )
                sql_b, params_b = sample_count_query(
                    db_b, filters.get(db_b), restrict_to_regulators=common_list
                )
                n_a = int(conn.execute(sql_a, params_a).df().iloc[0, 0])
                n_b = int(conn.execute(sql_b, params_b).df().iloc[0, 0])

                cross_dataset[(db_a, db_b)] = {
                    "common_regulators": len(common),
                    "samples_a": n_a,
                    "samples_b": n_b,
                }

        return {
            "diagonal": diagonal,
            "cross_dataset": cross_dataset,
            "regulator_sets": regulator_sets,
            "regulator_symbols": regulator_symbols,
        }

    @reactive.calc
    def _regulator_union() -> list[str]:
        """
        Locus tags for the union of regulators across all active datasets, sorted by
        display symbol.

        :trigger: ``_matrix_data`` — re-runs whenever the active regulator union
            changes.
        :returns: Sorted list of locus tags. Empty if no datasets are active or
            computing ``_matrix_data`` fails.

        """
        try:
            data = _matrix_data()
        except Exception:
            return []
        regulator_sets = data["regulator_sets"]
        symbol_map = data["regulator_symbols"]
        return sorted(
            set().union(*regulator_sets.values()) if regulator_sets else set(),
            key=lambda lt: symbol_map.get(lt, lt),
        )

    @reactive.effect
    def _sync_regulator_search_choices() -> None:
        """
        Refresh the regulator search selectize's choices to match the active regulator
        union, preserving any selections still in range.

        :trigger: ``_regulator_union`` — re-runs whenever the active regulator
            union changes.

        """
        union = _regulator_union()
        symbol_map = _matrix_data()["regulator_symbols"] if union else {}
        choices = {lt: f"{symbol_map.get(lt, lt)} ({lt})" for lt in union}
        try:
            current_selected = list(input.regulator_search())
        except SilentException:
            current_selected = []
        ui.update_selectize(
            "regulator_search",
            choices=choices,
            selected=[lt for lt in current_selected if lt in choices],
        )

    def _make_diagonal_effect(db_name: str) -> None:
        """
        Create the modal and contents on click of a diagonal cell.

        :param db_name: The dataset this cell represents.

        """
        btn_id = f"diag_{db_name}"

        @reactive.effect
        @reactive.event(input[btn_id])
        def _on_click() -> None:
            """
            Compute regulator/sample multiplicity for this dataset and show the diagonal
            cell modal.

            :trigger: ``input[diag_{db_name}]`` — fires when the user clicks the
                diagonal matrix cell button.

            """
            filters = dataset_filters().get(db_name)
            candidate_cols = _candidate_condition_columns(db_name)

            sql, params = regulator_breakdown_query(db_name, candidate_cols, filters)
            row = conn.execute(sql, params).df().iloc[0]
            n_multi = int(row["n_multi"])

            if n_multi == 0:
                multi_regulator_sample_breakdown: dict = {"uniform": True}
            else:
                diff_cols = [c for c in candidate_cols if row.get(c, 0) > 0]
                multi_regulator_sample_breakdown = {
                    "uniform": False,
                    "n_multi": n_multi,
                    "differentiating_columns": diff_cols,
                }

            display_name = display_names.get(db_name, db_name)
            ui.modal_show(
                diagonal_cell_modal_ui(display_name, multi_regulator_sample_breakdown)
            )

    def _make_off_diagonal_effect(db_a: str, db_b: str) -> None:
        """Register per-pair click and modal-action effects for an off-diagonal cell."""
        btn_id = f"offdiag_{db_a}__{db_b}"
        apply_btn_id = "modal_queue_common_regulators"

        @reactive.effect
        @reactive.event(input[btn_id])
        def _on_click() -> None:
            """
            If this pair is the active regulator filter, clear the filter. Otherwise,
            show the off-diagonal cell modal.

            :trigger: ``input[offdiag_{db_a}__{db_b}]`` — fires when the user
                clicks the off-diagonal matrix cell button.

            """
            if _active_regulator_pair() == (db_a, db_b):
                current = dict(dataset_filters())
                for db_name in list(current):
                    ds_filters = dict(current[db_name])
                    ds_filters.pop("regulator_locus_tag", None)
                    if ds_filters:
                        current[db_name] = ds_filters
                    else:
                        current.pop(db_name)
                dataset_filters.set(current)
                _active_regulator_pair.set(None)
                return
            data = _matrix_data()
            info = data["cross_dataset"].get((db_a, db_b), {})
            n_common = info.get("common_regulators", 0)
            _open_modal_pair.set((db_a, db_b))
            ui.modal_show(
                off_diagonal_cell_modal_ui(
                    display_names.get(db_a, db_a),
                    display_names.get(db_b, db_b),
                    n_common,
                )
            )

        @reactive.effect
        @reactive.event(input[apply_btn_id])
        def _on_apply_common_regulators() -> None:
            """
            Compute the regulator intersection for this pair, write it as a
            ``regulator_locus_tag`` filter to all datasets, and highlight the cell.

            :trigger: ``input[modal_queue_common_regulators]`` — fires when the
                user clicks "Select common regulators" in the off-diagonal modal.

            """
            if _open_modal_pair() != (db_a, db_b):
                return
            reg_sets = {}
            filters = dataset_filters()
            for db_name in (db_a, db_b):
                db_filters = {
                    k: v
                    for k, v in (filters.get(db_name) or {}).items()
                    if k != "regulator_locus_tag"
                } or None
                sql, params = regulator_locus_tags_query(db_name, db_filters)
                reg_df = conn.execute(sql, params).df()
                reg_sets[db_name] = set(
                    reg_df["regulator_locus_tag"].dropna().astype(str)
                )
            common = sorted(reg_sets[db_a] & reg_sets[db_b])
            if not common:
                ui.modal_remove()
                return
            current = dict(dataset_filters())
            pair_display = (
                display_names.get(db_a, db_a),
                display_names.get(db_b, db_b),
            )
            for db_name in _all_db_names:
                ds_filters = dict(current.get(db_name, {}))
                ds_filters.pop("regulator_locus_tag", None)
                ds_filters["regulator_locus_tag"] = {
                    "type": "categorical",
                    "value": common,
                    "from_pair": pair_display,
                }
                current[db_name] = ds_filters
            dataset_filters.set(current)
            _active_regulator_pair.set((db_a, db_b))
            _open_modal_pair.set(None)
            ui.modal_remove()

    # Tracks the (db_a, db_b) pair whose intersection is the current regulator filter.
    _active_regulator_pair: reactive.Value[tuple[str, str] | None] = reactive.value(
        None
    )

    # Tracks which pair's off-diagonal modal is currently open.
    _open_modal_pair: reactive.Value[tuple[str, str] | None] = reactive.value(None)

    # Track which cell effects have already been registered to avoid duplicates.
    _registered_effects: set[str] = set()

    @reactive.effect
    def _register_cell_effects() -> None:
        """
        Register click effects for any newly active dataset cells.

        :trigger: ``_settled_datasets`` — re-runs whenever the active dataset list
            settles so that new cell effects are created for any newly added datasets.

        """
        active = _settled_datasets()
        for db_name in active:
            if db_name not in _registered_effects:
                _make_diagonal_effect(db_name)
                _registered_effects.add(db_name)
        for i, db_a in enumerate(active):
            for db_b in active[i + 1 :]:
                pair_id = f"{db_a}__{db_b}"
                if pair_id not in _registered_effects:
                    _make_off_diagonal_effect(db_a, db_b)
                    _registered_effects.add(pair_id)

    @reactive.effect
    @reactive.event(input.regulator_cell_click)
    def _on_regulator_cell_click() -> None:
        """
        Show the conditions modal for the clicked cell of the regulator/dataset table.

        A single shared input (``regulator_cell_click``) is used for every cell in
        the regulator/dataset presence table, with the clicked ``(locus_tag,
        db_name)`` pair JSON-encoded as the input value. This avoids registering
        one reactive effect per cell, since that table can have hundreds of
        regulator rows.

        :trigger: ``input.regulator_cell_click`` — fires when the user clicks any
            "x" cell in the regulator/dataset presence table.

        """
        try:
            locus_tag, db_name = json.loads(input.regulator_cell_click())
        except (TypeError, ValueError, json.JSONDecodeError):
            return
        if db_name not in _settled_datasets():
            return

        data = _matrix_data()
        symbol = data["regulator_symbols"].get(locus_tag, locus_tag)
        candidate_cols = _candidate_condition_columns(db_name)
        sql, params = regulator_conditions_query(
            db_name, locus_tag, candidate_cols, dataset_filters().get(db_name)
        )
        rows_df = conn.execute(sql, params).df()
        columns = ["sample_id", *candidate_cols]
        active_sample_ids = set(
            rows_df.loc[rows_df["__matches_filters"], "sample_id"].astype(str)
        )
        rows = rows_df[columns].to_dict("records")

        ui.modal_show(
            regulator_cell_modal_ui(
                display_names.get(db_name, db_name),
                symbol,
                locus_tag,
                columns,
                rows,
                active_sample_ids,
            )
        )

    @reactive.effect
    def _clear_pair_when_filter_removed() -> None:
        """
        Clear the highlighted cell pair when no ``regulator_locus_tag`` filter remains.

        :trigger: ``dataset_filters`` — re-runs on every filter change.

        """
        filters = dataset_filters()
        has_reg_filter = any(
            "regulator_locus_tag" in (v or {}) for v in filters.values()
        )
        if not has_reg_filter:
            _active_regulator_pair.set(None)

    @render.ui
    def matrix_content() -> ui.Tag:
        active = _settled_datasets()

        if not active:
            return ui.card(
                ui.card_body(
                    ui.p(
                        "Select datasets from the sidebar to view sample counts.",
                        class_="text-muted",
                    )
                )
            )

        try:
            data = _matrix_data()
        except Exception:
            logger.exception("Failed to compute matrix data")
            return ui.card(
                ui.card_body(
                    ui.p(
                        "Failed to load dataset matrix. Check that filters are valid.",
                        class_="text-danger",
                    )
                )
            )
        diagonal = data["diagonal"]
        cross_dataset = data["cross_dataset"]

        # header row
        header_cells = [matrix_header_cell("Dataset", row=True)]
        for db_name in active:
            header_cells.append(matrix_header_cell(display_names.get(db_name, db_name)))

        # body rows
        body_rows: list[ui.Tag] = []
        for row_i, db_row in enumerate(active):
            cells: list[ui.Tag] = [matrix_row_label(display_names.get(db_row, db_row))]

            for col_i, db_col in enumerate(active):
                if col_i < row_i:
                    cells.append(matrix_cell("empty"))
                    continue

                if col_i == row_i:
                    info = diagonal.get(db_row, {})
                    cells.append(
                        matrix_cell(
                            "diagonal",
                            matrix_cell_button(
                                session.ns(f"diag_{db_row}"),
                                f"{info.get('regulators', 0):,} regulators / "
                                f"{info.get('samples', 0):,} samples",
                            ),
                        )
                    )
                else:
                    key = (db_row, db_col)
                    info = cross_dataset.get(key, {})
                    is_active = _active_regulator_pair() == (db_row, db_col)
                    cells.append(
                        matrix_cell(
                            "interactive",
                            matrix_cell_button(
                                session.ns(f"offdiag_{db_row}__{db_col}"),
                                f"{info.get('common_regulators', 0):,} "
                                "common regulators",
                                tooltip=(
                                    "Click to remove the regulator filter"
                                    if is_active
                                    else None
                                ),
                            ),
                            active=is_active,
                        )
                    )

            body_rows.append(ui.tags.tr(*cells))

        return matrix_table(ui.tags.tr(*header_cells), *body_rows)

    @render.ui
    def regulator_dataset_table_content() -> ui.Tag:
        active = _settled_datasets()

        if not active:
            return ui.card(
                ui.card_body(
                    ui.p(
                        "Select datasets from the sidebar to view regulators.",
                        class_="text-muted",
                    )
                )
            )

        try:
            data = _matrix_data()
        except Exception:
            logger.exception("Failed to compute regulator table data")
            return ui.card(
                ui.card_body(
                    ui.p(
                        "Failed to load regulator table. Check that filters are"
                        " valid.",
                        class_="text-danger",
                    )
                )
            )

        regulator_sets = data["regulator_sets"]
        symbol_map = data["regulator_symbols"]
        all_locus_tags = _regulator_union()

        try:
            search_selected = set(input.regulator_search())
        except SilentException:
            search_selected = set()
        display_locus_tags = (
            [lt for lt in all_locus_tags if lt in search_selected]
            if search_selected
            else all_locus_tags
        )

        if not display_locus_tags:
            message = (
                "No regulators match your search."
                if search_selected
                else "No regulators found for the current filters."
            )
            return ui.card(ui.card_body(ui.p(message, class_="text-muted")))

        header_cells = [matrix_header_cell("Regulator", row=True)]
        for db_name in active:
            header_cells.append(matrix_header_cell(display_names.get(db_name, db_name)))

        body_rows: list[ui.Tag] = []
        for locus_tag in display_locus_tags:
            cells: list[ui.Tag] = [
                matrix_row_label(symbol_map.get(locus_tag, locus_tag))
            ]
            for db_name in active:
                if locus_tag in regulator_sets.get(db_name, set()):
                    cells.append(
                        matrix_cell(
                            "interactive",
                            matrix_cell_button(
                                session.ns("regulator_cell_click"),
                                "x",
                                value=json.dumps([locus_tag, db_name]),
                            ),
                        )
                    )
                else:
                    cells.append(matrix_cell("empty"))
            body_rows.append(ui.tags.tr(*cells))

        return matrix_table(ui.tags.tr(*header_cells), *body_rows, scroll_y=True)


__all__ = ["select_datasets_workspace_server"]
