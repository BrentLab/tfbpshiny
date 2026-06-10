"""Pure UI builder for the rectangular binding × perturbation top-N matrix."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
from shiny import ui

from tfbpshiny.components import (
    matrix_cell,
    matrix_cell_button,
    matrix_header_cell,
    matrix_table,
)


def build_topn_matrix_ui(
    binding_datasets: list[str],
    perturbation_datasets: list[str],
    topn_medians: dict[tuple[str, str], float | None],
    display_names: dict[str, str],
    selected_binding: str | None,
    selected_perturbation: str | None,
    ns: Callable[[str], str] = lambda s: s,
    cell_slot: Callable[[str, str], ui.Tag] | None = None,
    col_tooltip: Callable[[str], str] | None = None,
) -> ui.Tag:
    """
    Build a rectangular binding × perturbation matrix table tag.

    Layout::

                  Pert A    Pert B    Pert C
        Bind X    12.3 %    —         8.7 %
        Bind Y    15.1 %    9.4 %     11.0 %

    Row headers are clickable buttons that select the entire row (all
    perturbation datasets for that binding dataset).  Column headers are
    clickable buttons that select the entire column (all binding datasets for
    that perturbation dataset).  Interior cells are also clickable and select
    the binding row.

    Button IDs:

    - Row header: ``topnrow_{b_db}``
    - Column header: ``topncol_{p_db}``
    - Interior cell: ``topncell_{b_db}__{p_db}``

    :param binding_datasets: Ordered list of binding dataset db_names (rows).
    :param perturbation_datasets: Ordered list of perturbation dataset db_names
        (columns).
    :param topn_medians: Mapping from ``(b_db, p_db)`` to median percent-
        responsive, or ``None`` when no data is available for that pair.
    :param display_names: Mapping from db_name to human-readable label.
    :param selected_binding: Currently selected binding db_name, or ``None``.
    :param selected_perturbation: Currently selected perturbation db_name, or
        ``None``.
    :param ns: Namespace function (the module ``session.ns``) applied to every
        button id. The button ``onclick`` writes ``Shiny.setInputValue`` with a
        literal id that is not auto-namespaced, so it must be the module-scoped
        id for the click effects (``input[bare_id]``) to receive it. Defaults to
        identity for standalone (non-module) use.
    :param cell_slot: Optional callback ``(b_db, p_db) -> ui.Tag`` that, when
        provided, replaces the computed value label in each interactive cell with
        the returned tag. Use to embed ``ui.output_ui(...)`` slots for progressive
        loading. When ``None`` (default), cells show the value from
        ``topn_medians`` directly.
    :param col_tooltip: Optional callback ``(p_db) -> str`` returning the tooltip
        text for each column header. When ``None``, a generic click-hint is shown.
    :returns: ``ui.Tag`` ready to embed directly in a ``render.ui`` output.

    """
    # --- Header row -----------------------------------------------------------
    # Corner spacer + one column header button per perturbation dataset.
    header_cells: list[ui.Tag] = [matrix_header_cell("", row=True)]
    for p_db in perturbation_datasets:
        label = display_names.get(p_db, p_db)
        is_active = selected_perturbation == p_db
        tip = (
            col_tooltip(p_db)
            if col_tooltip is not None
            else "Click to view distributions for this perturbation dataset"
        )
        # Column headers are interactive (clickable to select column).
        header_cells.append(
            ui.tags.th(
                {"class": "matrix-col-header"},
                matrix_cell_button(
                    ns(f"topncol_{p_db}"),
                    label,
                    tooltip=tip,
                ),
                **(
                    {"style": "background-color: #2B4C7E; color: white;"}
                    if is_active
                    else {}
                ),
            )
        )

    # --- Body rows ------------------------------------------------------------
    body_rows: list[ui.Tag] = []
    for b_db in binding_datasets:
        row_active = selected_binding == b_db
        # Row label is a clickable button.
        row_label_cell = ui.tags.td(
            {
                "class": "matrix-row-label"
                + (" matrix-cell-active" if row_active else "")
            },
            matrix_cell_button(
                ns(f"topnrow_{b_db}"),
                display_names.get(b_db, b_db),
                tooltip="Click to view distributions for this binding dataset",
            ),
        )
        cells: list[ui.Tag] = [row_label_cell]
        for p_db in perturbation_datasets:
            # Cell is active when its row OR column is selected.
            cell_active = (selected_binding == b_db) or (selected_perturbation == p_db)
            if cell_slot is not None:
                # Progressive loading: embed an output_ui slot; the pre-registered
                # per-cell render fills it independently when its slice lands.
                cells.append(
                    matrix_cell(
                        "interactive",
                        cell_slot(b_db, p_db),
                        active=cell_active,
                    )
                )
            else:
                val = topn_medians.get((b_db, p_db))
                if val is not None and not pd.isna(val):
                    label = f"{val:.1f}%"
                else:
                    label = "—"
                cells.append(
                    matrix_cell(
                        "interactive",
                        matrix_cell_button(ns(f"topncell_{b_db}__{p_db}"), label),
                        active=cell_active,
                    )
                )
        body_rows.append(ui.tags.tr(*cells))

    return matrix_table(ui.tags.tr(*header_cells), *body_rows)


__all__ = ["build_topn_matrix_ui"]
