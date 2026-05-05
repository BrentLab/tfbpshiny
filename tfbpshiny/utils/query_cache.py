"""
Process-level query result cache for VirtualDB calls.

Provides a single dict-based LRU cache keyed on ``(sql, params_tuple)``
that survives across tab switches and regulator re-visits.  The
``reactive.Value`` scatter cache in each workspace module holds only
the most recent regulator's data; this cache fills the gap by making
repeated visits to previously-queried regulators instantaneous.

The cache is module-level and therefore shared across all Shiny sessions
within the same process.  All returned DataFrames are copies so callers
cannot mutate cached data.

"""

from __future__ import annotations

from typing import Any

import pandas as pd
from labretriever import VirtualDB

_CACHE: dict[tuple, pd.DataFrame] = {}

#: Maximum number of query results to retain.  At 9 scatter pairs per
#: regulator, this covers the ~57 most recently visited regulators.
#: Top-N entries are far fewer (12 pairs × a handful of slider combos).
MAXSIZE = 512


def cached_query(vdb: VirtualDB, sql: str, params: dict[str, Any]) -> pd.DataFrame:
    """
    Execute ``vdb.query`` with a process-level LRU-style cache.

    Results are stored keyed on ``(sql, tuple(sorted(params.items())))``
    so identical queries return from cache without hitting DuckDB.
    A copy is returned on every call to prevent callers from mutating
    the cached DataFrame.

    :param vdb: VirtualDB instance used to execute the query on cache miss.
    :param sql: SQL string passed to ``vdb.query``.
    :param params: Named parameters dict passed as ``**params`` to ``vdb.query``.
    :returns: DataFrame copy from cache or from a fresh query.

    """
    key = (sql, tuple(sorted(params.items())))
    if key in _CACHE:
        return _CACHE[key].copy()
    result = vdb.query(sql, **params)
    if len(_CACHE) >= MAXSIZE:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = result
    return result.copy()
