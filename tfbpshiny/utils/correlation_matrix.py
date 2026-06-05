"""Pure UI builder for the pairwise correlation matrix."""

from __future__ import annotations

import pandas as pd
from shiny import ui

from tfbpshiny.components import (
    matrix_cell,
    matrix_cell_button,
    matrix_header_cell,
    matrix_row_label,
    matrix_table,
)


def build_correlation_matrix_ui(
    all_possible_pairs: list[tuple[str, str]],
    active_pairs: list[tuple[str, str]],
    active_datasets: list[str],
    corr_data: dict[tuple[str, str], pd.DataFrame],
    display_names: dict[str, str],
    selected_pairs: set[tuple[str, str]],
) -> ui.Tag:
    """
    Build the upper-triangle-only correlation matrix table tag.

    Layout (N=4 example, datasets A B C D):

    ::

              B      C      D
        A   A-B    A-C    A-D
        B          B-C    B-D
        C                 C-D

    Row labels (sticky left) identify the row dataset.  Column headers identify
    the column dataset.  The last dataset has no row (all its cells would be
    lower-triangle or diagonal) so it appears only as a column header.
    Diagonal and lower-triangle positions are grey empty placeholders.

    Clicking an interactive cell toggles its membership in ``selected_pairs``;
    all selected cells receive the ``.matrix-cell-active`` style.

    Canonical pair ordering is derived from a rank dict built from
    ``all_possible_pairs`` — the same approach used in the select_datasets
    workspace to ensure button IDs are stable across re-renders.

    :param all_possible_pairs: Full universe of ``(db_a, db_b)`` tuples
        registered at server start.  Used to derive stable canonical ordering
        for button IDs.
    :param active_pairs: Pairs present in the completed ``_run_analysis``
        result (already filtered by included-datasets checkbox).
    :param active_datasets: Ordered list of active dataset names.
    :param corr_data: Mapping from canonical pair tuple to a DataFrame with a
        ``"correlation"`` column containing per-regulator values.
    :param display_names: Mapping from ``db_name`` to human-readable label.
    :param selected_pairs: Set of canonical pairs currently selected.
    :returns: ``ui.Tag`` ready to embed directly in a ``render.ui`` output.

    """
    # Rank dict for canonical pair ordering (lower rank = first in pair).
    # Built from the unique sorted dataset list so every dataset gets a rank,
    # including the last one which never appears as the first element of a pair.
    _seen: list[str] = []
    for _a, _b in all_possible_pairs:
        if _a not in _seen:
            _seen.append(_a)
        if _b not in _seen:
            _seen.append(_b)
    _rank: dict[str, int] = {db: i for i, db in enumerate(_seen)}

    def _canonical(a: str, b: str) -> tuple[str, str]:
        return (a, b) if _rank.get(a, -1) < _rank.get(b, -1) else (b, a)

    active_set: set[tuple[str, str]] = set(active_pairs)

    # Header: corner spacer + column labels for datasets[1..N-1].
    # datasets[0] appears only as a row label; it has no column of its own
    # (its column position is entirely lower-triangle / diagonal).
    header_cells: list[ui.Tag] = [matrix_header_cell("", row=True)]
    for db in active_datasets[1:]:
        header_cells.append(matrix_header_cell(display_names.get(db, db)))

    # Body: one row per dataset except the last (which has no interactive cells).
    body_rows: list[ui.Tag] = []
    for row_i, db_row in enumerate(active_datasets[:-1]):
        cells: list[ui.Tag] = [matrix_row_label(display_names.get(db_row, db_row))]
        for col_i, db_col in enumerate(active_datasets[1:], start=1):
            if col_i <= row_i:
                # Lower-triangle position (col is to the left of the diagonal).
                cells.append(matrix_cell("empty"))
            else:
                pair = _canonical(db_row, db_col)
                btn_id = f"corrpair_{pair[0]}__{pair[1]}"
                if pair in active_set:
                    df = corr_data.get(pair, pd.DataFrame())
                    if df.empty or "correlation" not in df.columns:
                        label = "—"
                    else:
                        med = df["correlation"].median()
                        label = f"{med:.3f}" if pd.notna(med) else "—"
                else:
                    label = "—"
                cells.append(
                    matrix_cell(
                        "interactive",
                        matrix_cell_button(btn_id, label),
                        active=(pair in selected_pairs),
                    )
                )
        body_rows.append(ui.tags.tr(*cells))

    return matrix_table(ui.tags.tr(*header_cells), *body_rows)


__all__ = ["build_correlation_matrix_ui"]
