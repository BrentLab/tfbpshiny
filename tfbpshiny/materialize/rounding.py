"""
Rounding of computed floating-point results before they are stored.

DuckDB sums in whatever order its parallel aggregation happens to schedule, so a
correlation recomputed from identical inputs can differ in its last bits. Two builds of
the same database from the same commit disagreed on 60,347 of 92,498 `correlations`
rows for this reason -- all key columns matching, `n_shared_targets` identical, and the
largest disagreement 1.17e-13.

That noise is harmless numerically but it makes builds impossible to diff, which hides
real regressions. Rounding the computed columns removes it: at 9 decimals those 60,347
rows drop to 0, while 12 decimals still leaves 39. Nine therefore sits three to four
orders of magnitude above the noise floor and far below any precision the figures use.

Only values this pipeline *computes* are rounded. Columns read straight from the
source parquet -- `dto_empirical_pvalue`, `dto_fdr` and the DTO set sizes -- are stored
as published, since rounding those would alter source data rather than remove
computation noise.

"""

from __future__ import annotations

#: Decimal places kept for computed floating-point columns. Raise it to keep more
#: precision, lower it to be more aggressive about build-to-build noise; pass
#: ``--float-decimals`` to ``tfbpshiny materialize`` to override per build.
DEFAULT_FLOAT_DECIMALS: int = 9

#: Passing this disables rounding entirely, storing the raw computed value.
NO_ROUNDING: int = -1


def round_expr(expr: str, decimals: int = DEFAULT_FLOAT_DECIMALS) -> str:
    """
    Wrap a SQL expression in ``round(...)``, or return it unchanged.

    :param expr: SQL expression producing a DOUBLE.
    :param decimals: Decimal places to keep; :data:`NO_ROUNDING` leaves ``expr`` alone.
    :returns: SQL expression.
    :rtype: str
    :raises ValueError: If ``decimals`` is negative and not :data:`NO_ROUNDING`.

    """
    if decimals == NO_ROUNDING:
        return expr
    if decimals < 0:
        raise ValueError(
            f"decimals must be >= 0 or NO_ROUNDING ({NO_ROUNDING}), got {decimals}"
        )
    return f"round({expr}, {decimals})"


__all__ = ["DEFAULT_FLOAT_DECIMALS", "NO_ROUNDING", "round_expr"]
