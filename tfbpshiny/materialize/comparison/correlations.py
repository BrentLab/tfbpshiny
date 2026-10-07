"""
SQL generators for the ``correlations`` comparison table.

Functions return SQL strings (no side effects) so they can be called from a
Jupyter notebook to inspect the query before running the full pipeline.
The coordinator is the only code that calls ``.execute()``. The per-dataset score
columns it correlates are ``tfbpshiny.datasets.BINDING_DATASET_COLUMNS`` and
``PERTURBATION_CORRELATION_COLUMNS``.

"""

from __future__ import annotations

from typing import Any

from tfbpshiny.materialize.rounding import DEFAULT_FLOAT_DECIMALS, round_expr

#: p-values below this are treated as this value before taking -log10, so a
#: single near-zero p-value can't blow up the log10pval scale. Matches the
#: capping convention described in the Binding/Perturbation "-log10(p-value)"
#: tooltip.
LOG10PVAL_FLOOR = 1e-10


# ---------------------------------------------------------------------------
# SQL generators
# ---------------------------------------------------------------------------


def correlations_schema_sql() -> str:
    """
    Return the ``CREATE TABLE correlations`` DDL (empty — no data).

    :returns: ``CREATE TABLE correlations (…)`` SQL string.
    :rtype: str

    """
    return """
CREATE TABLE correlations (
    source_sample_a      VARCHAR  NOT NULL,
    source_sample_b      VARCHAR  NOT NULL,
    regulator_locus_tag  VARCHAR  NOT NULL,
    comparison_type      VARCHAR  NOT NULL,
    method               VARCHAR  NOT NULL,
    score_type           VARCHAR  NOT NULL,
    score_col_a          VARCHAR  NOT NULL,
    score_col_b          VARCHAR  NOT NULL,
    correlation          DOUBLE   NOT NULL,
    n_shared_targets     INTEGER  NOT NULL,
    PRIMARY KEY (
        source_sample_a, source_sample_b,
        regulator_locus_tag,
        method, score_type
    )
);
"""


def _score_type_block(
    view_a: str,
    prefix_a_str: str,
    value_expr_a: str,
    null_check_col_a: str,
    view_b: str,
    prefix_b_str: str,
    value_expr_b: str,
    null_check_col_b: str,
    score_type: str,
    score_col_a_label: str,
    score_col_b_label: str,
    order_dir: str,
    method: str,
    comparison_type_safe: str,
    method_safe: str,
    round_decimals: int = DEFAULT_FLOAT_DECIMALS,
) -> str:
    """
    Build one parenthesized ``WITH ... SELECT`` block for a single score type.

    Multiple blocks (one per applicable score type) are combined with
    ``UNION ALL`` by :func:`correlation_pair_select_sql`. Each block has its
    own independent ``WITH`` scope, so CTE names don't need cross-block
    uniquing.

    :param value_expr_a: SQL expression to correlate for dataset A — either a
        bare column name (``effect``, ``pvalue``) or a derived expression
        (``log10pval``).
    :param null_check_col_a: Raw column name to filter NULL/inf/nan on for
        dataset A (the underlying pvalue column for both ``pvalue`` and
        ``log10pval``, since the latter is derived from it).
    :param order_dir: ``"ASC"`` (lower value ranks first — pvalue) or
        ``"DESC_ABS"`` (larger magnitude ranks first — effect, log10pval).
        Determines rank direction for spearman's ``RANK() OVER (...)`` clause.
    :returns: One parenthesized SQL ``SELECT`` statement (a UNION ALL member).

    """
    score_col_a_safe = score_col_a_label.replace("'", "''")
    score_col_b_safe = score_col_b_label.replace("'", "''")

    def _order(expr: str) -> str:
        return f"{expr} ASC" if order_dir == "ASC" else f"ABS({expr}) DESC"

    if method == "spearman":
        return f"""
(
  WITH
    a_raw AS (
      SELECT regulator_locus_tag, target_locus_tag,
             CAST(sample_id AS VARCHAR) AS sample_id,
             {value_expr_a} AS val
      FROM {view_a}
      WHERE {null_check_col_a} IS NOT NULL
        AND NOT isinf({null_check_col_a})
        AND NOT isnan({null_check_col_a})
    ),
    b_raw AS (
      SELECT regulator_locus_tag, target_locus_tag,
             CAST(sample_id AS VARCHAR) AS sample_id,
             {value_expr_b} AS val
      FROM {view_b}
      WHERE {null_check_col_b} IS NOT NULL
        AND NOT isinf({null_check_col_b})
        AND NOT isnan({null_check_col_b})
    ),
    joined AS (
      SELECT
        a_raw.regulator_locus_tag,
        a_raw.sample_id  AS id_a,
        b_raw.sample_id  AS id_b,
        a_raw.val        AS val_a,
        b_raw.val        AS val_b
      FROM a_raw
      INNER JOIN b_raw
        ON  a_raw.regulator_locus_tag = b_raw.regulator_locus_tag
       AND a_raw.target_locus_tag    = b_raw.target_locus_tag
    ),
    ranked AS (
      SELECT
        regulator_locus_tag,
        id_a, id_b,
        RANK() OVER (
          PARTITION BY regulator_locus_tag, id_a, id_b
          ORDER BY {_order('val_a')}
        ) AS rank_a,
        RANK() OVER (
          PARTITION BY regulator_locus_tag, id_a, id_b
          ORDER BY {_order('val_b')}
        ) AS rank_b
      FROM joined
    ),
    agg AS (
      SELECT
        regulator_locus_tag,
        id_a, id_b,
        {round_expr("corr(rank_a, rank_b)", round_decimals)} AS correlation,
        COUNT(*)             AS n_shared_targets
      FROM ranked
      GROUP BY regulator_locus_tag, id_a, id_b
      HAVING COUNT(*) >= 3
    )
  SELECT
    '{prefix_a_str}' || id_a  AS source_sample_a,
    '{prefix_b_str}' || id_b  AS source_sample_b,
    regulator_locus_tag,
    '{comparison_type_safe}'   AS comparison_type,
    '{method_safe}'            AS method,
    '{score_type}'             AS score_type,
    '{score_col_a_safe}'       AS score_col_a,
    '{score_col_b_safe}'       AS score_col_b,
    correlation,
    n_shared_targets::INTEGER
  FROM agg
  WHERE correlation IS NOT NULL AND NOT isnan(correlation)
)
"""
    # pearson
    return f"""
(
  WITH
    a_raw AS (
      SELECT regulator_locus_tag, target_locus_tag,
             CAST(sample_id AS VARCHAR) AS sample_id,
             {value_expr_a} AS val
      FROM {view_a}
      WHERE {null_check_col_a} IS NOT NULL
        AND NOT isinf({null_check_col_a})
        AND NOT isnan({null_check_col_a})
    ),
    b_raw AS (
      SELECT regulator_locus_tag, target_locus_tag,
             CAST(sample_id AS VARCHAR) AS sample_id,
             {value_expr_b} AS val
      FROM {view_b}
      WHERE {null_check_col_b} IS NOT NULL
        AND NOT isinf({null_check_col_b})
        AND NOT isnan({null_check_col_b})
    ),
    agg AS (
      SELECT
        a_raw.regulator_locus_tag,
        a_raw.sample_id       AS id_a,
        b_raw.sample_id       AS id_b,
        {round_expr("corr(a_raw.val, b_raw.val)", round_decimals)} AS correlation,
        COUNT(*)              AS n_shared_targets
      FROM a_raw
      INNER JOIN b_raw
        ON  a_raw.regulator_locus_tag = b_raw.regulator_locus_tag
       AND a_raw.target_locus_tag    = b_raw.target_locus_tag
      GROUP BY a_raw.regulator_locus_tag, a_raw.sample_id, b_raw.sample_id
      HAVING COUNT(*) >= 3
    )
  SELECT
    '{prefix_a_str}' || id_a  AS source_sample_a,
    '{prefix_b_str}' || id_b  AS source_sample_b,
    regulator_locus_tag,
    '{comparison_type_safe}'   AS comparison_type,
    '{method_safe}'            AS method,
    '{score_type}'             AS score_type,
    '{score_col_a_safe}'       AS score_col_a,
    '{score_col_b_safe}'       AS score_col_b,
    correlation,
    n_shared_targets::INTEGER
  FROM agg
  WHERE correlation IS NOT NULL
)
"""


def correlation_pair_select_sql(
    view_a: str,
    hf_repo_a: str,
    hf_config_a: str,
    effect_col_a: str,
    pvalue_col_a: str,
    view_b: str,
    hf_repo_b: str,
    hf_config_b: str,
    effect_col_b: str,
    pvalue_col_b: str,
    method: str,
    comparison_type: str,
    param_prefix: str = "p",
    round_decimals: int = DEFAULT_FLOAT_DECIMALS,
) -> tuple[str, dict[str, Any]]:
    """
    Return a SELECT that produces ``correlations``-shaped rows for one dataset pair,
    covering every applicable score type in a single query (one ``UNION ALL`` per score
    type) — one round trip per (pair, method), same as before this added
    pvalue/log10pval.

    Score types:

    - ``effect`` — always computed (every dataset has an effect column).
    - ``pvalue`` — only when both ``pvalue_col_a`` and ``pvalue_col_b`` are
      non-empty.
    - ``log10pval`` — same condition, and only for ``method="pearson"``.
      Computed as ``-log10(GREATEST(pvalue_col, LOG10PVAL_FLOOR))``. Not
      computed for ``spearman``: rank correlation is invariant to strictly
      monotonic transforms, so it is mathematically equivalent to
      ``pvalue`` — except that the ``LOG10PVAL_FLOOR`` clamp collapses
      distinct near-zero p-values into ties that don't exist on the raw
      scale, which would otherwise make the two disagree.

    Pair ordering is enforced by the caller: pass datasets in lexicographic
    order (``view_a <= view_b``) so each unordered pair is stored exactly once.
    No user-level filters are applied; the query covers all samples.

    :param view_a: First dataset name (DuckDB view/table name); must be <= view_b.
    :param hf_repo_a: HuggingFace repo for dataset A.
    :param hf_config_a: HuggingFace config for dataset A.
    :param effect_col_a: Effect-size measurement column from dataset A.
    :param pvalue_col_a: Raw p-value column from dataset A, or ``""`` if none.
    :param view_b: Second dataset name; must be >= view_a.
    :param hf_repo_b: HuggingFace repo for dataset B.
    :param hf_config_b: HuggingFace config for dataset B.
    :param effect_col_b: Effect-size measurement column from dataset B.
    :param pvalue_col_b: Raw p-value column from dataset B, or ``""`` if none.
    :param method: ``'pearson'`` or ``'spearman'``.
    :param comparison_type: ``'binding'`` or ``'perturbation'``.
    :param param_prefix: Namespace prefix for SQL parameters (unused today —
        kept for signature stability with callers that pass it positionally).
    :returns: ``(sql, params)`` tuple. ``params`` is always empty; no bound
        parameters are needed since every value is a validated identifier or
        SQL-escaped literal.
    :rtype: tuple[str, dict]

    """
    params: dict[str, Any] = {}

    prefix_a_str = f"{hf_repo_a};{hf_config_a};".replace("'", "''")
    prefix_b_str = f"{hf_repo_b};{hf_config_b};".replace("'", "''")
    comparison_type_safe = comparison_type.replace("'", "''")
    method_safe = method.replace("'", "''")

    blocks = [
        _score_type_block(
            view_a,
            prefix_a_str,
            effect_col_a,
            effect_col_a,
            view_b,
            prefix_b_str,
            effect_col_b,
            effect_col_b,
            "effect",
            effect_col_a,
            effect_col_b,
            "DESC_ABS",
            method,
            comparison_type_safe,
            method_safe,
            round_decimals,
        )
    ]

    if pvalue_col_a and pvalue_col_b:
        blocks.append(
            _score_type_block(
                view_a,
                prefix_a_str,
                pvalue_col_a,
                pvalue_col_a,
                view_b,
                prefix_b_str,
                pvalue_col_b,
                pvalue_col_b,
                "pvalue",
                pvalue_col_a,
                pvalue_col_b,
                "ASC",
                method,
                comparison_type_safe,
                method_safe,
                round_decimals,
            )
        )
        # Not computed for spearman — see docstring above.
        if method != "spearman":
            log10_a = f"(-LOG10(GREATEST({pvalue_col_a}, {LOG10PVAL_FLOOR})))"
            log10_b = f"(-LOG10(GREATEST({pvalue_col_b}, {LOG10PVAL_FLOOR})))"
            blocks.append(
                _score_type_block(
                    view_a,
                    prefix_a_str,
                    log10_a,
                    pvalue_col_a,
                    view_b,
                    prefix_b_str,
                    log10_b,
                    pvalue_col_b,
                    "log10pval",
                    pvalue_col_a,
                    pvalue_col_b,
                    "DESC_ABS",
                    method,
                    comparison_type_safe,
                    method_safe,
                    round_decimals,
                )
            )

    sql = "\nUNION ALL\n".join(blocks)
    return sql, params


__all__ = [
    "LOG10PVAL_FLOOR",
    "correlations_schema_sql",
    "correlation_pair_select_sql",
]
