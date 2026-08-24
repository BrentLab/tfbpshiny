"""
Startup checks that a materialized database matches what the app expects to read.

The app pins analysis parameters by value when it reads ``topn_results``. A database
built by an older materializer can therefore hold *extra* rows the app has no filter
for, which silently change every median it computes -- an error with no traceback and
no empty table to notice.

"""

from __future__ import annotations

import logging

import duckdb


def warn_if_stale_topn_schema(
    conn: duckdb.DuckDBPyConnection, logger: logging.Logger
) -> bool:
    """
    Warn when ``topn_results`` still carries the retired ``criteria`` column.

    Databases built before responsiveness became threshold-only hold two rows per key:
    one scored by thresholds and one scored by each perturbation dataset's deprecated
    ``responsive`` column. The app no longer filters on ``criteria``, so both rows now
    match every query and the median falls between two incompatible definitions of
    responsive. For ``rossi`` x ``kemmeren`` at top 25 that reads 0.0% rather than
    Relaxed's 20.0%.

    :param conn: Read-only DuckDB connection.
    :param logger: Logger to warn on.
    :returns: ``True`` when the schema is stale.

    """
    try:
        cols = conn.execute("DESCRIBE topn_results").df()["column_name"].tolist()
    except duckdb.Error:
        # No topn_results at all is a different problem, reported where it is read.
        return False
    if "criteria" not in cols:
        return False
    logger.warning(
        "topn_results still has the retired 'criteria' column, so it holds rows "
        "scored by the deprecated per-row 'responsive' flag alongside the "
        "threshold-scored rows. Nothing filters those out any more, so every "
        "percent-responsive number on the Comparison and Figures pages is a median "
        "across both and will read low. Rebuild with 'tfbpshiny materialize'."
    )
    return True
