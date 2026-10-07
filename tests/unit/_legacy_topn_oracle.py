"""
The original per-variant top-N query, kept as a test oracle.

``topn_pair_select_sql`` computes one ``(top_n, effect, pvalue)`` variant of one
(binding, perturbation) pair by scanning the source views directly. The app materializes
with ``topn_pair_select_sql_v2`` (``tfbpshiny/materialize/comparison/topn.py``), which
emits every variant from one staged scan-and-rank. The two must agree row for row;
``test_topn_equivalence.py`` and ``test_topn_tie_rule.py`` run both on synthetic data
and compare. This copy is not used by the application.

"""

from __future__ import annotations

from typing import Any

from tfbpshiny.materialize.comparison.topn import (
    TOP_N_ALL,
    check_tie_rule,
    cutoff_rank_expr,
    responsive_expr,
)
from tfbpshiny.materialize.rounding import DEFAULT_FLOAT_DECIMALS, round_expr


def topn_pair_select_sql(
    binding_view: str,
    binding_hf_repo: str,
    binding_hf_config: str,
    perturbation_view: str,
    pert_hf_repo: str,
    pert_hf_config: str,
    binding_sample_col: str,
    rank_col: str,
    rank_asc: bool,
    target_blacklist: tuple[str, ...],
    binding_dedup_cte: str,
    top_n: int,
    effect_threshold: float,
    pvalue_threshold: float,
    regulator_subset: tuple[str, ...] = (),
    param_prefix: str = "p",
    round_decimals: int = DEFAULT_FLOAT_DECIMALS,
    tie_rule: str = "avg_rank",
    no_signal_value: float | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Return a SELECT that produces ``topn_results``-shaped rows for one pair.

    The SELECT includes composite ``source_sample`` IDs, analysis parameters,
    and result columns, in the shape the coordinator inserts into ``topn_results``.

    No user-level filters are applied; the query covers all samples in both
    datasets (subject to harbison YPD dedup when applicable).

    The result includes ``n_intersecting_targets``: the count of distinct targets
    shared by that specific binding/perturbation sample pair for that regulator,
    uncapped by ``top_n`` (unlike ``n``, which is capped at ``top_n``). This lets
    consumers require a regulator/sample-pair to have had at least ``top_n``
    candidate targets before the top-N cutoff was applied.

    :param binding_view: Binding dataset name (DuckDB view/table name).
    :param binding_hf_repo: HuggingFace repo for the binding dataset.
    :param binding_hf_config: HuggingFace config for the binding dataset.
    :param perturbation_view: Perturbation dataset name.
    :param pert_hf_repo: HuggingFace repo for the perturbation dataset.
    :param pert_hf_config: HuggingFace config for the perturbation dataset.
    :param binding_sample_col: Column in the binding view for sample identifier.
    :param rank_col: Column used to rank binding hits.
    :param rank_asc: If ``True``, lower values rank better (p-values).
    :param target_blacklist: Target locus tags excluded from ranking.
    :param binding_dedup_cte: Optional CTE body SQL replacing the default
        binding SELECT (used for Harbison YPD dedup).
    :param top_n: Number of top binding targets to keep per binding sample.
    :param effect_threshold: Minimum absolute effect size to count as responsive.
    :param pvalue_threshold: Maximum p-value to count as responsive.
    :param regulator_subset: If non-empty, restrict both CTEs to these
        ``regulator_locus_tag`` values (for chunked execution).
    :param param_prefix: Namespace prefix for SQL parameters.
    :param round_decimals: Decimal places kept for ``responsive_ratio``.
    :param tie_rule: How ties decide membership of the top N; see :data:`TIE_RULES`.
    :param no_signal_value: If given, a NULL ranking score is replaced by this value
        (see :func:`binding_stage_sql`).
    :returns: ``(sql, params)`` tuple.
    :rtype: tuple[str, dict]

    """
    check_tie_rule(tie_rule)
    params: dict[str, Any] = {}
    rank_dir = "ASC" if rank_asc else "DESC"

    reg_in_clause = ""
    if regulator_subset:
        reg_ph = ", ".join(
            f"$reg_{param_prefix}_{i}" for i in range(len(regulator_subset))
        )
        for i, reg in enumerate(regulator_subset):
            params[f"reg_{param_prefix}_{i}"] = reg
        reg_in_clause = f"regulator_locus_tag IN ({reg_ph})"

    # Build the binding CTE body.
    if binding_dedup_cte:
        binding_cte_body = binding_dedup_cte
    else:
        blacklist_clauses: list[str] = []
        if target_blacklist:
            ph = ", ".join(
                f"$bl_{param_prefix}_{i}" for i in range(len(target_blacklist))
            )
            blacklist_clauses.append(f"target_locus_tag NOT IN ({ph})")
            for i, tag in enumerate(target_blacklist):
                params[f"bl_{param_prefix}_{i}"] = tag
        binding_extra = (
            "WHERE " + " AND ".join(blacklist_clauses) if blacklist_clauses else ""
        )
        rank_select = (
            f"COALESCE({rank_col}, {float(no_signal_value)!r}) AS {rank_col}"
            if no_signal_value is not None
            else rank_col
        )
        binding_cte_body = f"""
        SELECT
            CAST({binding_sample_col} AS VARCHAR) AS binding_sample_id,
            regulator_locus_tag,
            target_locus_tag,
            {rank_select}
        FROM {binding_view}
        {binding_extra}
        """

    if reg_in_clause:
        binding_cte_body = (
            f"SELECT * FROM ({binding_cte_body}) AS _binding_batch"
            f" WHERE {reg_in_clause}"
        )

    # Perturbation responsive expression (uses $params for thresholds).
    responsive_case = responsive_expr(
        perturbation_view,
        effect_threshold,
        pvalue_threshold,
        param_prefix,
        params,
    )

    pert_clauses: list[str] = []
    if reg_in_clause:
        pert_clauses.append(f"p.{reg_in_clause}")
    pert_filter_where = f"WHERE {' AND '.join(pert_clauses)}" if pert_clauses else ""

    top_n_key = f"{param_prefix}_top_n"
    params[top_n_key] = top_n

    # TOP_N_ALL keeps every bound target. Used for the peak datasets, where the
    # authors' peak call already *is* the threshold and ranking would discard part of
    # their answer. `n` then carries the size of the authors' bound set.
    rank_cutoff_clause = "" if top_n == TOP_N_ALL else f"WHERE rnk <= ${top_n_key}"
    cutoff_rank = cutoff_rank_expr(
        tie_rule,
        "b.binding_sample_id",
        f"b.{rank_col} {rank_dir}",
        f"b.{rank_col}",
    )

    # Escaped literal strings for composite ID construction (no user input).
    b_prefix = f"{binding_hf_repo};{binding_hf_config};".replace("'", "''")
    p_prefix = f"{pert_hf_repo};{pert_hf_config};".replace("'", "''")

    # Literal values for the analysis-parameter columns.
    rank_col_safe = rank_col.replace("'", "''")
    rank_asc_sql = "TRUE" if rank_asc else "FALSE"
    ratio_expr = round_expr(
        "SUM(pert.is_responsive)::DOUBLE / COUNT(*)", round_decimals
    )

    sql = f"""
    WITH binding AS (
        {binding_cte_body}
    ),
    perturbation AS (
        SELECT
            CAST(p.sample_id AS VARCHAR) AS perturbation_sample_id,
            p.regulator_locus_tag,
            p.target_locus_tag,
            {responsive_case} AS is_responsive
        FROM {perturbation_view} p
        {pert_filter_where}
    ),
    intersecting_counts AS (
        SELECT
            b.binding_sample_id,
            b.regulator_locus_tag,
            pert.perturbation_sample_id,
            COUNT(DISTINCT b.target_locus_tag) AS n_intersecting_targets
        FROM binding b
        JOIN perturbation pert
            ON  b.regulator_locus_tag = pert.regulator_locus_tag
            AND b.target_locus_tag    = pert.target_locus_tag
        WHERE b.regulator_locus_tag != b.target_locus_tag
        GROUP BY b.binding_sample_id, b.regulator_locus_tag, pert.perturbation_sample_id
    ),
    intersecting_targets AS (
        SELECT DISTINCT b.regulator_locus_tag, b.target_locus_tag
        FROM binding b
        INNER JOIN perturbation pert
            ON  b.regulator_locus_tag = pert.regulator_locus_tag
            AND b.target_locus_tag    = pert.target_locus_tag
    ),
    binding_ranked AS (
        SELECT
            b.binding_sample_id,
            b.regulator_locus_tag,
            b.target_locus_tag,
            b.{rank_col},
            {cutoff_rank} AS rnk
        FROM binding b
        INNER JOIN intersecting_targets it
            ON  b.regulator_locus_tag = it.regulator_locus_tag
            AND b.target_locus_tag    = it.target_locus_tag
        WHERE b.regulator_locus_tag != b.target_locus_tag
    ),
    top_n_binding AS (
        SELECT binding_sample_id, regulator_locus_tag, target_locus_tag
        FROM binding_ranked
        {rank_cutoff_clause}
    ),
    summary AS (
        SELECT
            b.binding_sample_id,
            b.regulator_locus_tag,
            pert.perturbation_sample_id,
            COUNT(*)                               AS n,
            SUM(pert.is_responsive)::INTEGER       AS n_responsive,
            {ratio_expr}                           AS responsive_ratio
        FROM top_n_binding b
        JOIN perturbation pert
            ON  b.regulator_locus_tag = pert.regulator_locus_tag
            AND b.target_locus_tag    = pert.target_locus_tag
        GROUP BY b.binding_sample_id, b.regulator_locus_tag, pert.perturbation_sample_id
    )
    SELECT
        '{b_prefix}' || s.binding_sample_id         AS binding_source_sample,
        '{p_prefix}' || s.perturbation_sample_id    AS perturbation_source_sample,
        s.regulator_locus_tag,
        ${top_n_key}::INTEGER                       AS top_n,
        '{rank_col_safe}'                           AS rank_col,
        {rank_asc_sql}                              AS rank_asc,
        {effect_threshold!r}::DOUBLE                AS effect_threshold,
        {pvalue_threshold!r}::DOUBLE                AS pvalue_threshold,
        s.n,
        s.n_responsive,
        s.responsive_ratio,
        COALESCE(ic.n_intersecting_targets, 0)::INTEGER AS n_intersecting_targets
    FROM summary s
    LEFT JOIN intersecting_counts ic
        ON  s.binding_sample_id      = ic.binding_sample_id
        AND s.regulator_locus_tag    = ic.regulator_locus_tag
        AND s.perturbation_sample_id = ic.perturbation_sample_id
    """
    return sql, params
