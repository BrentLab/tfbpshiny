"""Unit tests for select_datasets pure helper functions."""

from tfbpshiny.modules.select_datasets.queries import (
    _build_where,
    metadata_query,
    regulator_locus_tags_query,
    sample_count_query,
)
from tfbpshiny.modules.select_datasets.server.sidebar import _filter_btn_id, _toggle_id

# --- ID generators ---


def test_toggle_id_is_stable():
    assert _toggle_id("harbison") == _toggle_id("harbison")


def test_toggle_id_differs_by_dataset():
    assert _toggle_id("harbison") != _toggle_id("hackett")


def test_filter_btn_id_is_stable():
    assert _filter_btn_id("harbison") == _filter_btn_id("harbison")


# --- _build_where ---


def test_build_where_no_filters():
    params: dict = {}
    assert _build_where(None, params) == ""
    assert params == {}


def test_build_where_categorical():
    params: dict = {}
    where = _build_where(
        {"strain": {"type": "categorical", "value": ["BY4741"]}}, params
    )
    assert "strain IN" in where
    assert "BY4741" in params.values()


def test_build_where_numeric():
    params: dict = {}
    where = _build_where({"time": {"type": "numeric", "value": [0.0, 30.0]}}, params)
    assert "BETWEEN" in where
    assert params["num_time_lo"] == 0.0
    assert params["num_time_hi"] == 30.0


def test_build_where_bool():
    params: dict = {}
    where = _build_where({"is_wt": {"type": "bool", "value": True}}, params)
    assert "is_wt" in where
    assert params["bool_is_wt"] is True


# --- query builders ---


def test_metadata_query_no_filters():
    sql, params = metadata_query("harbison")
    assert sql == "SELECT * FROM harbison_meta"
    assert params == {}


def test_metadata_query_with_filter():
    sql, params = metadata_query(
        "harbison", {"strain": {"type": "categorical", "value": ["BY4741"]}}
    )
    assert "WHERE" in sql
    assert "BY4741" in params.values()


def test_sample_count_query():
    sql, params = sample_count_query("harbison")
    assert "COUNT(sample_id)" in sql
    assert params == {}


def test_sample_count_query_with_regulators():
    sql, params = sample_count_query("harbison", restrict_to_regulators=["YAL001C"])
    assert "regulator_locus_tag IN" in sql
    assert "YAL001C" in params.values()


def test_regulator_locus_tags_query():
    sql, params = regulator_locus_tags_query("harbison")
    assert "DISTINCT regulator_locus_tag" in sql
    assert params == {}
