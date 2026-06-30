# flake8: noqa
"""
DTO (Directional Transcription Overlap) query helpers for the Comparison module.

DTO was removed from the app-facing Comparison UI in
``7a50fcb removing dto, adjusting topn and fixing the misalignment btwn sidebar
and workspace (#262) (#266)``, in favor of the topN-by-binding analysis. These
constants and ``fetch_dto_data`` were left behind in
``tfbpshiny/modules/comparison/queries.py`` with no remaining callers; moved
here for reference. The materialized ``dto`` table itself (built via
``tfbpshiny/materialize/comparison/dto.py``) is left in place and still
materialized -- this file only concerns the now-orphaned app-side reader.

"""

from __future__ import annotations

import duckdb
import pandas as pd

#: Pseudo-value added before -log10 to avoid log(0)
DTO_LOG_PSEUDO = 1e-3

#: Default effect size threshold (|effect| must exceed this to be "responsive")
DEFAULT_EFFECT_THRESHOLD = 0.0

#: Default p-value threshold (pvalue must be below this to be "responsive")
DEFAULT_PVALUE_THRESHOLD = 0.05

#: Per-perturbation-source kwargs (informational).
PERTURBATION_CONFIGS: dict[str, dict] = {
    "hackett": {},
    "hughes_overexpression": {},
    "hughes_knockout": {},
    "hu_reimand": {},
    "kemmeren": {},
    "degron": {},
}


def fetch_dto_data(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """
    Fetch DTO empirical p-value data from the materialized dto table.

    :param conn: Read-only DuckDB connection.
    :returns: DataFrame with all columns from the ``dto`` table.

    """
    return conn.execute("SELECT * FROM dto").df()
