"""
Is this database one the app knows how to read?

``tfbpshiny materialize`` stamps the layout it wrote into a one-row ``schema_version``
table. The app compares that stamp with :data:`tfbpshiny.datasets.SCHEMA_VERSION` once
at startup. A database built at another version may lack whole tables or columns the
read-side SQL names, so the mismatch is reported on every page and the figures refuse
to draw, instead of each query failing in its own way.

"""

from __future__ import annotations

import logging

import duckdb

from tfbpshiny.datasets import SCHEMA_VERSION


def read_schema_version(conn: duckdb.DuckDBPyConnection) -> int | None:
    """
    The schema version stamped into the database.

    :param conn: Read-only DuckDB connection.
    :returns: The stamped version, or ``None`` for a database built before the stamp
        existed (no ``schema_version`` table).

    """
    try:
        row = conn.execute("SELECT max(version) FROM schema_version").fetchone()
    except duckdb.Error:
        return None
    if row is None or row[0] is None:
        return None
    return int(row[0])


def schema_mismatch_message(db_version: int | None) -> str | None:
    """
    The sentence shown when the database's version is not the app's.

    :param db_version: From :func:`read_schema_version`.
    :returns: The message, or ``None`` when the versions agree.

    """
    if db_version == SCHEMA_VERSION:
        return None
    built = (
        "before schema versions were stamped"
        if db_version is None
        else f"at schema version {db_version}"
    )
    return (
        f"This database was built {built}; this version of the app reads schema "
        f"version {SCHEMA_VERSION}. Rebuild it with 'tfbpshiny materialize' before "
        "trusting any number on these pages."
    )


def check_schema_version(
    conn: duckdb.DuckDBPyConnection, logger: logging.Logger
) -> int | None:
    """
    Read the stamp and log one warning if it is not the app's version.

    :param conn: Read-only DuckDB connection.
    :param logger: Logger to warn on.
    :returns: The stamped version (``None`` when absent), for the caller to pass on.

    """
    db_version = read_schema_version(conn)
    message = schema_mismatch_message(db_version)
    if message is not None:
        logger.warning(message)
    return db_version


__all__ = ["check_schema_version", "read_schema_version", "schema_mismatch_message"]
