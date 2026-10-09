"""
Pure helpers behind the dataset filter modal's condition choices.

A dataset's metadata columns are either *condition* columns (labretriever role
``experimental_condition`` with per-level definitions, shown as labelled checkboxes) or
*upstream* columns (everything else that is filterable, e.g. carbon source). Upstream
selections narrow which condition levels are offered; condition selections never feed
back into the upstream choices.

"""

from __future__ import annotations

from typing import Any

import pandas as pd
from labretriever import ColumnMeta

from tfbpshiny.utils.vdb_init import FIELD_TYPE_OVERRIDES


def is_categorical(df: pd.DataFrame, db_name: str, col: str) -> bool:
    """
    Whether a metadata column is filtered by picking levels.

    :param df: The dataset's metadata.
    :param db_name: Dataset name, for :data:`FIELD_TYPE_OVERRIDES`.
    :param col: Column name.
    :returns: ``True`` when the column is overridden to categorical or has a string
        or categorical dtype.

    """
    override = FIELD_TYPE_OVERRIDES.get((db_name, col)) or FIELD_TYPE_OVERRIDES.get(
        ("", col)
    )
    if override is not None and override[0] == "categorical":
        return True
    return df[col].dtype.name in ("object", "category")


def condition_choices(
    df: pd.DataFrame,
    mask: pd.Series,
    condition_cols: list[str],
    db_meta: dict[str, ColumnMeta],
) -> dict[str, dict[str, str]]:
    """
    Labelled choices for each condition column, among the rows ``mask`` keeps.

    :param df: The dataset's metadata.
    :param mask: Rows whose condition levels are offered.
    :param condition_cols: Condition column names.
    :param db_meta: The dataset's column metadata.
    :returns: ``column -> {level: label}``, most frequent level first. A level with a
        definition is labelled ``"definition (level)"``.

    """
    result: dict[str, dict[str, str]] = {}
    for col in condition_cols:
        if col not in df.columns:
            continue
        levels = df.loc[mask, col].dropna().astype(str).value_counts().index.tolist()
        meta = db_meta.get(col)
        defs = (meta.level_definitions if meta else None) or {}
        result[col] = {v: f"{defs[v]} ({v})" if defs.get(v) else v for v in levels}
    return result


def upstream_mask(
    df: pd.DataFrame,
    db_name: str,
    selections: dict[str, list[str]],
) -> pd.Series:
    """
    Rows matching every non-empty categorical upstream selection.

    All upstream columns are intersected together, so a column whose value is the same
    in every row cannot undo the narrowing of one that discriminates.

    :param df: The dataset's metadata.
    :param db_name: Dataset name.
    :param selections: ``upstream column -> selected levels``; an empty list selects
        everything.
    :returns: Boolean mask over ``df``.

    """
    mask = pd.Series(True, index=df.index)
    for col, sel in selections.items():
        if sel and col in df.columns and is_categorical(df, db_name, col):
            mask &= df[col].astype(str).isin([str(v) for v in sel])
    return mask


def initial_modal_view(
    df: pd.DataFrame,
    db_name: str,
    existing_filters: dict[str, Any] | None,
    upstream_cols: list[str],
) -> tuple[dict[str, Any], pd.DataFrame]:
    """
    The filter values and rows the modal opens with.

    Upstream columns the filters do not set are pre-selected with the levels that
    co-occur with the filters, so that, e.g., Harbison filtered to YPD opens with only
    glucose under Carbon source. The rows are then narrowed to those upstream levels,
    so condition checkboxes offer only conditions that co-occur with them. A dataset
    whose upstream columns do not vary offers every condition.

    :param df: The dataset's unfiltered metadata.
    :param db_name: Dataset name.
    :param existing_filters: The dataset's staged or applied filter spec, or
        ``None``.
    :param upstream_cols: The dataset's upstream column names.
    :returns: ``(filters, rows)``: the filter spec to pre-populate the modal with,
        and the metadata rows its controls are built from.

    """
    augmented: dict[str, Any] = dict(existing_filters or {})
    if existing_filters:
        mask = pd.Series(True, index=df.index)
        for fld, spec in existing_filters.items():
            if fld not in df.columns:
                continue
            ftype, fval = spec.get("type"), spec.get("value")
            if ftype == "categorical" and fval:
                mask &= df[fld].astype(str).isin([str(v) for v in fval])
            elif (
                ftype == "numeric"
                and isinstance(fval, (list, tuple))
                and len(fval) == 2
            ):
                mask &= (df[fld] >= float(fval[0])) & (df[fld] <= float(fval[1]))
        matched = df[mask]
        for col in upstream_cols:
            if col in augmented or col not in matched.columns:
                continue
            vals = matched[col].dropna().astype(str).unique().tolist()
            if vals:
                augmented[col] = {"type": "categorical", "value": sorted(vals)}

    selections = {
        col: list(augmented[col].get("value") or [])
        for col in upstream_cols
        if col in augmented and augmented[col].get("type") == "categorical"
    }
    view = df[upstream_mask(df, db_name, selections)]

    return augmented, view
