"""The schema stamp is written by the build and checked by the app."""

from __future__ import annotations

import logging

import duckdb

from tfbpshiny.datasets import SCHEMA_VERSION
from tfbpshiny.materialize.coordinating.sql import schema_version_sql
from tfbpshiny.utils.schema_check import (
    check_schema_version,
    read_schema_version,
    schema_mismatch_message,
)


def _stamped(version: int, sha: str | None = "abc123") -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect()
    conn.execute(schema_version_sql(version, sha))
    return conn


def test_the_build_stamps_the_current_version() -> None:
    conn = _stamped(SCHEMA_VERSION)
    assert read_schema_version(conn) == SCHEMA_VERSION
    version, built_at, sha = conn.execute("SELECT * FROM schema_version").fetchone()
    assert version == SCHEMA_VERSION and built_at is not None and sha == "abc123"


def test_a_build_outside_git_stores_a_null_sha() -> None:
    conn = _stamped(SCHEMA_VERSION, sha=None)
    assert conn.execute("SELECT git_sha FROM schema_version").fetchone()[0] is None


def test_a_database_without_the_table_reads_as_unstamped() -> None:
    assert read_schema_version(duckdb.connect()) is None


def test_current_version_raises_no_message() -> None:
    assert schema_mismatch_message(SCHEMA_VERSION) is None


def test_older_and_unstamped_databases_are_named_in_the_message() -> None:
    assert "before schema versions" in (schema_mismatch_message(None) or "")
    assert f"schema version {SCHEMA_VERSION - 1}" in (
        schema_mismatch_message(SCHEMA_VERSION - 1) or ""
    )


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def test_check_logs_once_only_on_mismatch() -> None:
    logger = logging.getLogger("test_schema_version")
    handler = _ListHandler()
    logger.addHandler(handler)
    try:
        assert check_schema_version(_stamped(SCHEMA_VERSION), logger) == SCHEMA_VERSION
        assert handler.messages == []
        assert check_schema_version(duckdb.connect(), logger) is None
        assert len(handler.messages) == 1 and "materialize" in handler.messages[0]
    finally:
        logger.removeHandler(handler)
