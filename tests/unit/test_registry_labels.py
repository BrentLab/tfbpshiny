"""The display labels the figures use come from the registry tables, not from code."""

from __future__ import annotations

import duckdb

from tfbpshiny.materialize.coordinating.sql import (
    binding_methods_sql,
    promoter_sets_sql,
)
from tfbpshiny.utils.vdb_init import binding_method_labels, promoter_set_labels


def _registry_conn() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(":memory:")
    conn.execute(promoter_sets_sql())
    conn.execute(binding_methods_sql())
    return conn


def test_promoter_set_labels_read_the_registry_display_names() -> None:
    labels = promoter_set_labels(_registry_conn())
    assert labels["500bp"] == "500bp"
    assert labels["kang"] == "Kang"
    assert labels["mindel"] == "Mindel"
    assert labels["intergenic"] == "Intergenic"
    # The registry also names the two non-window promoter sets; readers that only
    # want the comparable levels index with PROMOTER_SET_LEVELS.
    assert {"peaks", "array"} <= set(labels)


def test_binding_method_labels_read_the_registry_display_names() -> None:
    assert binding_method_labels(_registry_conn()) == {
        "promoter_enrichment": "Promoter Enrichment",
        "peak_calling": "Peak Calling",
    }
