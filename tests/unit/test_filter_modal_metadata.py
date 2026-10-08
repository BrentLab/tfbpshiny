"""The filter modal's column metadata: written at build time, read at startup, and used
to label condition checkboxes and narrow them by the upstream selections."""

from __future__ import annotations

import duckdb
import pandas as pd
from labretriever import ColumnMeta

from tfbpshiny.materialize.coordinating.sql import column_metadata_sql
from tfbpshiny.modules.select_datasets.modal_state import (
    condition_choices,
    initial_modal_view,
    upstream_mask,
)
from tfbpshiny.modules.select_datasets.ui import dataset_filter_modal_ui
from tfbpshiny.utils.vdb_init import load_app_datasets

CONDITION = ColumnMeta(
    description="Growth condition",
    role="experimental_condition",
    level_definitions={"YPD": "Rich medium", "HEAT": "Heat shock"},
)
CARBON = ColumnMeta(description="Carbon source", role="experimental_condition")
META = {"Experimental condition": CONDITION, "Carbon source": CARBON}


class _MetaVDB:
    """Just the VirtualDB accessors ``column_metadata_sql`` uses."""

    def get_datasets(self) -> list[str]:
        return ["harbison"]

    def get_column_metadata(self, db_name: str) -> dict[str, ColumnMeta]:
        return {
            **META,
            "sample_id": ColumnMeta(),
            "regulator_locus_tag": ColumnMeta(role="regulator_identifier"),
            "Temperature": ColumnMeta(description="Degrees C, it's warm"),
        }


def _df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sample_id": [1, 2, 3, 4],
            "Carbon source": ["glucose", "glucose", "galactose", "galactose"],
            "Experimental condition": ["YPD", "HEAT", "YPD", "GAL"],
        }
    )


def test_metadata_survives_the_database_round_trip() -> None:
    conn = duckdb.connect()
    conn.execute(column_metadata_sql(_MetaVDB()))
    app = load_app_datasets(conn)
    meta = app.column_meta["harbison"]
    assert set(meta) == {"Experimental condition", "Carbon source", "Temperature"}
    assert meta["Experimental condition"].role == "experimental_condition"
    assert meta["Experimental condition"].level_definitions == {
        "YPD": "Rich medium",
        "HEAT": "Heat shock",
    }
    assert meta["Temperature"].description == "Degrees C, it's warm"
    assert meta["Carbon source"].level_definitions is None
    assert app.condition_cols["harbison"] == ["Experimental condition"]
    assert sorted(app.upstream_cols["harbison"]) == ["Carbon source", "Temperature"]


def test_condition_levels_are_labelled_with_their_definitions() -> None:
    df = _df()
    choices = condition_choices(
        df, upstream_mask(df, "harbison", {}), ["Experimental condition"], META
    )
    assert choices["Experimental condition"] == {
        "YPD": "Rich medium (YPD)",
        "HEAT": "Heat shock (HEAT)",
        "GAL": "GAL",
    }


def test_upstream_selection_narrows_the_condition_levels() -> None:
    df = _df()
    mask = upstream_mask(df, "harbison", {"Carbon source": ["galactose"]})
    choices = condition_choices(df, mask, ["Experimental condition"], META)
    assert set(choices["Experimental condition"]) == {"YPD", "GAL"}


def test_modal_opens_on_the_upstream_levels_the_filters_imply() -> None:
    filters = {"Experimental condition": {"type": "categorical", "value": ["HEAT"]}}
    augmented, view = initial_modal_view(
        _df(), "harbison", filters, ["Carbon source"], META
    )
    assert augmented["Carbon source"] == {"type": "categorical", "value": ["glucose"]}
    assert set(view["Experimental condition"]) == {"YPD", "HEAT"}


def test_condition_filters_narrow_when_upstream_cannot() -> None:
    df = _df().assign(**{"Carbon source": "glucose"})
    filters = {"Experimental condition": {"type": "categorical", "value": ["YPD"]}}
    _, view = initial_modal_view(df, "harbison", filters, ["Carbon source"], META)
    assert set(view["Experimental condition"]) == {"YPD"}


def test_no_filters_open_on_every_row() -> None:
    augmented, view = initial_modal_view(
        _df(), "harbison", None, ["Carbon source"], META
    )
    assert augmented == {}
    assert len(view) == 4


def test_modal_renders_condition_checkboxes_with_labels() -> None:
    html = str(dataset_filter_modal_ui("harbison", _df(), None, set(), col_meta=META))
    assert 'type="checkbox"' in html
    assert "Rich medium (YPD)" in html
