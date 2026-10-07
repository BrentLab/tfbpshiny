"""
SQL generators for the ``topn_results`` comparison table.

Adapted from ``modules/comparison/queries.py::topn_responsive_ratio``.
Functions return SQL strings (no side effects) so they can be called from a
Jupyter notebook to inspect the query before running the full pipeline.
The coordinator is the only code that calls ``.execute()``.

"""

from __future__ import annotations

from typing import Any

from tfbpshiny.materialize.rounding import DEFAULT_FLOAT_DECIMALS, round_expr

# ---------------------------------------------------------------------------
# Per-dataset configuration (self-contained copy, not imported from modules/)
# ---------------------------------------------------------------------------

#: callingcards target locus tags excluded from top-N (matching R analysis)
CC_TARGET_BLACKLIST: tuple[str, ...] = (
    "YOR201C",
    "YOR202W",
    "YOR203W",
    "YCL018W",
    "YEL021W",
)

#: Harbison dedup CTE: aggregate to one row per (binding_sample, regulator, target)
#: keeping the minimum p-value, restricted to YPD condition.
_HARBISON_DEDUP_CTE = """
    SELECT
        CAST(sample_id AS VARCHAR) AS binding_sample_id,
        regulator_locus_tag,
        target_locus_tag,
        MIN(pvalue) AS pvalue
    FROM harbison
    WHERE sample_id IN (
        SELECT sample_id FROM harbison_meta WHERE condition = 'YPD'
    )
    GROUP BY sample_id, regulator_locus_tag, target_locus_tag
"""

#: Per-binding-dataset kwargs for top-N analysis.
#: Keys: binding_sample_col, rank_col, rank_asc, target_blacklist, binding_dedup_cte,
#: and optionally ``no_signal_value`` (the score a NULL ranks as; see the peak entries
#: below).
BINDING_TOPN_CONFIGS: dict[str, dict[str, Any]] = {
    "callingcards_kang": dict(
        binding_sample_col="sample_id",
        rank_col="poisson_pval",
        rank_asc=True,
        target_blacklist=CC_TARGET_BLACKLIST,
        binding_dedup_cte="",
    ),
    "callingcards_mindel": dict(
        binding_sample_col="sample_id",
        rank_col="poisson_pval",
        rank_asc=True,
        target_blacklist=CC_TARGET_BLACKLIST,
        binding_dedup_cte="",
    ),
    "callingcards_500bp": dict(
        binding_sample_col="sample_id",
        rank_col="poisson_pval",
        rank_asc=True,
        target_blacklist=CC_TARGET_BLACKLIST,
        binding_dedup_cte="",
    ),
    "callingcards_intergenic": dict(
        binding_sample_col="sample_id",
        rank_col="poisson_pval",
        rank_asc=True,
        target_blacklist=CC_TARGET_BLACKLIST,
        binding_dedup_cte="",
    ),
    "harbison": dict(
        binding_sample_col="sample_id",
        rank_col="pvalue",
        rank_asc=True,
        target_blacklist=(),
        binding_dedup_cte=_HARBISON_DEDUP_CTE,
    ),
    "chec_m2025": dict(
        binding_sample_col="sample_id",
        rank_col="enrichment",
        rank_asc=False,
        target_blacklist=(),
        binding_dedup_cte="",
    ),
    "chec_m2025_mindel": dict(
        binding_sample_col="sample_id",
        rank_col="enrichment",
        rank_asc=False,
        target_blacklist=(),
        binding_dedup_cte="",
    ),
    "chec_m2025_500bp": dict(
        binding_sample_col="sample_id",
        rank_col="enrichment",
        rank_asc=False,
        target_blacklist=(),
        binding_dedup_cte="",
    ),
    "chec_m2025_intergenic": dict(
        binding_sample_col="sample_id",
        rank_col="enrichment",
        rank_asc=False,
        target_blacklist=(),
        binding_dedup_cte="",
    ),
    "chec_m2025_peaks": dict(
        binding_sample_col="sample_id",
        rank_col="peak_score",
        rank_asc=False,
        target_blacklist=(),
        binding_dedup_cte="",
    ),
    "rossi": dict(
        binding_sample_col="sample_id",
        rank_col="enrichment",
        rank_asc=False,
        target_blacklist=(),
        binding_dedup_cte="",
    ),
    "rossi_mindel": dict(
        binding_sample_col="sample_id",
        rank_col="enrichment",
        rank_asc=False,
        target_blacklist=(),
        binding_dedup_cte="",
    ),
    "rossi_500bp": dict(
        binding_sample_col="sample_id",
        rank_col="enrichment",
        rank_asc=False,
        target_blacklist=(),
        binding_dedup_cte="",
    ),
    "rossi_intergenic": dict(
        binding_sample_col="sample_id",
        rank_col="enrichment",
        rank_asc=False,
        target_blacklist=(),
        binding_dedup_cte="",
    ),
    "rossi_peaks": dict(
        binding_sample_col="sample_id",
        rank_col="peak_score",
        rank_asc=False,
        target_blacklist=(),
        binding_dedup_cte="",
    ),
    # Promoter-set-matched peak calls. Rossi uses MACS, Mahendrawada uses HOMER
    # (replicating the reference publication's method); both expose the same
    # nearest/median/max score columns, so all eight rank on max_score.
    #
    # These tables report every promoter for every sample; a promoter with no
    # qualifying peak has a NULL score. ``no_signal_value`` is the score a NULL ranks
    # as:
    # 0, which is below every real score (Rossi max_score is -log10(q) >= 1 after the
    # q < 0.1 filter; ChEC-seq max_score is HOMER's normalized tag count, >= 89). The
    # authors' own peak calls (``rossi_peaks``, ``chec_m2025_peaks``) are sparse and
    # need none.
    "rossi_peaks_kang": dict(
        binding_sample_col="sample_id",
        rank_col="max_score",
        rank_asc=False,
        target_blacklist=(),
        binding_dedup_cte="",
        no_signal_value=0.0,
    ),
    "rossi_peaks_mindel": dict(
        binding_sample_col="sample_id",
        rank_col="max_score",
        rank_asc=False,
        target_blacklist=(),
        binding_dedup_cte="",
        no_signal_value=0.0,
    ),
    "rossi_peaks_500bp": dict(
        binding_sample_col="sample_id",
        rank_col="max_score",
        rank_asc=False,
        target_blacklist=(),
        binding_dedup_cte="",
        no_signal_value=0.0,
    ),
    "rossi_peaks_intergenic": dict(
        binding_sample_col="sample_id",
        rank_col="max_score",
        rank_asc=False,
        target_blacklist=(),
        binding_dedup_cte="",
        no_signal_value=0.0,
    ),
    "chec_m2025_peaks_kang": dict(
        binding_sample_col="sample_id",
        rank_col="max_score",
        rank_asc=False,
        target_blacklist=(),
        binding_dedup_cte="",
        no_signal_value=0.0,
    ),
    "chec_m2025_peaks_mindel": dict(
        binding_sample_col="sample_id",
        rank_col="max_score",
        rank_asc=False,
        target_blacklist=(),
        binding_dedup_cte="",
        no_signal_value=0.0,
    ),
    "chec_m2025_peaks_500bp": dict(
        binding_sample_col="sample_id",
        rank_col="max_score",
        rank_asc=False,
        target_blacklist=(),
        binding_dedup_cte="",
        no_signal_value=0.0,
    ),
    "chec_m2025_peaks_intergenic": dict(
        binding_sample_col="sample_id",
        rank_col="max_score",
        rank_asc=False,
        target_blacklist=(),
        binding_dedup_cte="",
        no_signal_value=0.0,
    ),
}

#: Sentinel ``top_n`` meaning "every bound target, no rank cutoff". Used for the
#: authors'-binding-threshold figure, where the peak datasets already encode the
#: authors' binary call so there is nothing left to threshold.
TOP_N_ALL = 0

#: Binding datasets whose rows *are* the authors' binding call, so a rank cutoff would
#: discard part of their answer. These additionally get ``TOP_N_ALL`` rows.
PEAK_BINDING_DATASETS: frozenset[str] = frozenset({"rossi_peaks", "chec_m2025_peaks"})

#: Fixed top-N cutoffs materialized into `topn_results`. The Comparison module's UI
#: offers exactly these choices (see modules/comparison/queries.py, ui.py) — defined
#: once here so materialization and the UI selector can't drift out of sync.
TOP_N_CHOICES: tuple[int, ...] = (10, 25, 50, 75, 100)

#: Perturbation datasets eligible for top-N analysis (no per-dataset kwargs needed).
PERTURBATION_TOPN_DATASETS: frozenset[str] = frozenset(
    {
        "hackett",
        "hughes_overexpression",
        "hughes_knockout",
        "hu_reimand",
        "kemmeren",
        "degron",
    }
)

#: Map: perturbation db_name → (effect_col, pvalue_col).
#: Empty string means the column does not exist.
PERTURBATION_DATASET_COLUMNS: dict[str, tuple[str, str]] = {
    "degron": ("log2FoldChange", "padj"),
    "hughes_overexpression": ("mean_norm_log2fc", ""),
    "hughes_knockout": ("mean_norm_log2fc", ""),
    "kemmeren": ("Madj", "pval"),
    "hackett": ("log2_shrunken_timecourses", ""),
    "hu_reimand": ("effect", "pval"),
}


# ---------------------------------------------------------------------------
# SQL generators
# ---------------------------------------------------------------------------


#: How ties in the binding score decide membership of the top N.
#:
#: * ``"rank"``     -- ``RANK()``: a tie group is in whenever its *first* member's
#:   rank is within N, so the whole group enters and ``n`` can far exceed N. The
#:   original rule.
#: * ``"avg_rank"`` -- a tie group is in only if its *average* rank is within N (a group
#:   spanning ranks a..b has average (a+b)/2). A large group straddling the cutoff drops
#:   out entirely, so ``n`` can fall below N, and a group that is kept whole can push
#:   ``n`` above N. The no-signal group never qualifies unless the pool is <= 2N.
TIE_RULES: tuple[str, ...] = ("rank", "avg_rank")


def _check_tie_rule(tie_rule: str) -> None:
    if tie_rule not in TIE_RULES:
        raise ValueError(f"tie_rule must be one of {TIE_RULES}, got {tie_rule!r}")


def _cutoff_rank_expr(tie_rule: str, partition: str, order_by: str, score: str) -> str:
    """
    SQL for the quantity compared with ``top_n`` to decide membership of the top N.

    :param tie_rule: One of :data:`TIE_RULES`.
    :param partition: Window partition (the binding sample).
    :param order_by: Window ordering, e.g. ``"b.rank_value DESC"``.
    :param score: The score expression defining a tie group.
    :returns: A SQL expression: the ``RANK()`` for ``"rank"``, or the tie group's
        average rank, ``RANK() + (group size - 1) / 2``, for ``"avg_rank"``.

    """
    rank = f"RANK() OVER (PARTITION BY {partition} ORDER BY {order_by})"
    if tie_rule == "rank":
        return rank
    size = f"COUNT(*) OVER (PARTITION BY {partition}, {score})"
    return f"({rank} + ({size} - 1) / 2.0)"


def topn_schema_sql() -> str:
    """
    Return the ``CREATE TABLE topn_results`` DDL (empty — no data).

    :returns: ``CREATE TABLE topn_results (…)`` SQL string.
    :rtype: str

    """
    return """
CREATE TABLE topn_results (
    binding_source_sample       VARCHAR  NOT NULL,
    perturbation_source_sample  VARCHAR  NOT NULL,
    regulator_locus_tag         VARCHAR  NOT NULL,
    top_n                       INTEGER  NOT NULL,
    rank_col                    VARCHAR  NOT NULL,
    rank_asc                    BOOLEAN  NOT NULL,
    effect_threshold            DOUBLE   NOT NULL,
    pvalue_threshold            DOUBLE   NOT NULL,
    n                           INTEGER  NOT NULL,
    n_responsive                INTEGER  NOT NULL,
    responsive_ratio            DOUBLE   NOT NULL,
    n_intersecting_targets      INTEGER  NOT NULL,
    PRIMARY KEY (
        binding_source_sample,
        perturbation_source_sample,
        regulator_locus_tag,
        top_n, rank_col, rank_asc,
        effect_threshold, pvalue_threshold
    )
);
"""


def responsive_expr(
    perturbation_view: str,
    effect_threshold: float,
    pvalue_threshold: float,
    param_prefix: str,
    params: dict[str, Any],
) -> str:
    """
    Build a SQL expression evaluating to 1 (responsive) or 0.

    Public (not `materialize/comparison/`-local) because
    ``callingcards_authors_bound.py`` reuses it directly rather than reimplementing
    the same threshold logic a second time -- this is the one place responsiveness is
    decided.

    Responsiveness is always decided by the ``(effect, pvalue)`` thresholds passed in,
    which the coordinator resolves per dataset from
    :data:`~tfbpshiny.utils.vdb_init.DEFAULT_RESPONSIVENESS_PRESETS`. The ``Stringent``
    preset holds each dataset's published criteria. The ``responsive`` boolean some
    source parquets ship is deprecated upstream and is deliberately not read.

    :param perturbation_view: Dataset name (key in ``PERTURBATION_DATASET_COLUMNS``).
    :param effect_threshold: Absolute effect magnitude must exceed this.
    :param pvalue_threshold: P-value must be below this (ignored when no pvalue col).
    :param param_prefix: Namespace prefix for SQL parameter names.
    :param params: Dict populated in-place with threshold values.
    :returns: SQL CASE expression string evaluating to 1 or 0.
    :rtype: str
    :raises KeyError: If the dataset declares no effect column to threshold on.

    """
    cols = PERTURBATION_DATASET_COLUMNS.get(perturbation_view, ("", ""))
    effect_col, pvalue_col = cols[0], cols[1]

    eff_key = f"{param_prefix}_eff_thresh"
    pval_key = f"{param_prefix}_pval_thresh"
    params[eff_key] = effect_threshold

    if effect_col and pvalue_col:
        params[pval_key] = pvalue_threshold
        return (
            f"CASE WHEN ABS(p.{effect_col}) > ${eff_key} "
            f"AND p.{pvalue_col} < ${pval_key} THEN 1 ELSE 0 END"
        )
    elif effect_col:
        return f"CASE WHEN ABS(p.{effect_col}) > ${eff_key} THEN 1 ELSE 0 END"
    raise KeyError(
        f"{perturbation_view!r} declares no effect column in "
        "PERTURBATION_DATASET_COLUMNS, so responsiveness cannot be thresholded. "
        "Add one there."
    )


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
    and result columns — ready for the coordinator to wrap in
    ``INSERT INTO topn_results``.  Adapted from
    ``modules/comparison/queries.py::topn_responsive_ratio``.

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
    _check_tie_rule(tie_rule)
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
    cutoff_rank = _cutoff_rank_expr(
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


# ---------------------------------------------------------------------------
# Staged SQL generators
# ---------------------------------------------------------------------------
#
# :func:`topn_pair_select_sql` above rescans both parquet sources for every
# ``(top_n, effect, pvalue)`` variant of every pair -- ~1170 full scans for a complete
# build, with Rossi's 8.7 M-row config re-read some 60 times. The three functions below
# split that into a scan phase and a compute phase:
#
#   A. :func:`binding_stage_sql`       -- once per binding dataset      (23 scans)
#   B. :func:`perturbation_stage_sql`  -- once per perturbation dataset  (6 scans)
#   C. :func:`topn_pair_select_sql_v2` -- once per pair, no parquet     (138 queries)
#
# What can *not* be hoisted: ``binding_ranked`` joins ``intersecting_targets`` before
# ranking, so "top 25" means "top 25 of the targets measured in both datasets" and the
# rank genuinely differs per perturbation dataset. Stage A hoists the scan feeding the
# rank, never the rank itself.


def binding_stage_sql(
    binding_view: str,
    binding_sample_col: str,
    rank_col: str,
    target_blacklist: tuple[str, ...],
    binding_dedup_cte: str,
    target_universe: frozenset[str] | None = None,
    param_prefix: str = "bs",
    no_signal_value: float | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Return a SELECT materializing one binding dataset's ranked-input rows (stage A).

    Applies exactly what the ``binding`` CTE of :func:`topn_pair_select_sql` applies --
    projection, target blacklist, and the Harbison YPD dedup where configured -- and
    nothing that depends on a perturbation dataset or on any threshold.

    The ranking column is aliased to ``rank_value`` so stage C need not know its name.

    :param binding_view: Binding dataset name (DuckDB view name).
    :param binding_sample_col: Column holding the sample identifier.
    :param rank_col: Column used to rank binding hits.
    :param target_blacklist: Target locus tags excluded before ranking.
    :param binding_dedup_cte: Optional CTE body replacing the default SELECT.
    :param target_universe: If given, restrict candidate rows to these
        ``target_locus_tag`` values before ranking -- used by
        ``method_promoter_model.py`` to hold the candidate target pool fixed across
        promoter-set variants. ``None`` (default) applies no restriction, unchanged
        from prior behaviour.
    :param param_prefix: Namespace prefix for SQL parameter names.
    :param no_signal_value: If given, a NULL ranking score is replaced by this value, so
        "reported but no signal" promoters rank as the lowest-scoring tie group rather
        than depending on how NULLs sort. ``None`` (default) leaves the score as is.
    :returns: ``(sql, params)`` producing ``binding_sample_id``,
        ``regulator_locus_tag``, ``target_locus_tag``, ``rank_value``.
    :rtype: tuple[str, dict]

    """
    params: dict[str, Any] = {}
    if binding_dedup_cte:
        body = binding_dedup_cte
    else:
        where = ""
        if target_blacklist:
            ph = ", ".join(
                f"$bl_{param_prefix}_{i}" for i in range(len(target_blacklist))
            )
            for i, tag in enumerate(target_blacklist):
                params[f"bl_{param_prefix}_{i}"] = tag
            where = f"WHERE target_locus_tag NOT IN ({ph})"
        body = f"""
        SELECT
            CAST({binding_sample_col} AS VARCHAR) AS binding_sample_id,
            regulator_locus_tag,
            target_locus_tag,
            {rank_col}
        FROM {binding_view}
        {where}
        """
    universe_where = ""
    if target_universe is not None:
        universe_key = f"{param_prefix}_universe"
        params[universe_key] = sorted(target_universe)
        universe_where = (
            f"WHERE target_locus_tag IN (SELECT unnest(${universe_key}::VARCHAR[]))"
        )
    rank_value = (
        f"COALESCE({rank_col}, {float(no_signal_value)!r})"
        if no_signal_value is not None
        else rank_col
    )
    sql = f"""
    SELECT
        binding_sample_id,
        regulator_locus_tag,
        target_locus_tag,
        {rank_value} AS rank_value
    FROM ({body}) AS _binding_stage
    {universe_where}
    """
    return sql, params


def perturbation_stage_sql(perturbation_view: str) -> tuple[str, dict[str, Any]]:
    """
    Return a SELECT materializing one perturbation dataset (stage B).

    Stores the raw effect and p-value rather than a thresholded ``is_responsive`` flag,
    so one row per measurement serves every threshold pair. Datasets with no p-value
    column emit ``NULL`` for it; stage C is told separately not to threshold on it, so a
    NULL can never be silently read as "passes".

    :param perturbation_view: Perturbation dataset name (DuckDB view name).
    :returns: ``(sql, params)`` producing ``perturbation_sample_id``,
        ``regulator_locus_tag``, ``target_locus_tag``, ``effect``, ``pvalue``.
    :rtype: tuple[str, dict]
    :raises KeyError: If the dataset declares no effect column.

    """
    effect_col, pvalue_col = PERTURBATION_DATASET_COLUMNS.get(
        perturbation_view, ("", "")
    )
    if not effect_col:
        raise KeyError(
            f"{perturbation_view!r} declares no effect column in "
            "PERTURBATION_DATASET_COLUMNS, so responsiveness cannot be thresholded. "
            "Add one there."
        )
    pvalue_expr = f"p.{pvalue_col}" if pvalue_col else "NULL"
    sql = f"""
    SELECT
        CAST(p.sample_id AS VARCHAR) AS perturbation_sample_id,
        p.regulator_locus_tag,
        p.target_locus_tag,
        p.{effect_col}       AS effect,
        {pvalue_expr}::DOUBLE AS pvalue
    FROM {perturbation_view} p
    """
    return sql, {}


def topn_pair_select_sql_v2(
    binding_table: str,
    binding_hf_repo: str,
    binding_hf_config: str,
    perturbation_table: str,
    pert_hf_repo: str,
    pert_hf_config: str,
    rank_col: str,
    rank_asc: bool,
    top_n_values: tuple[int, ...],
    threshold_pairs: tuple[tuple[float, float], ...],
    has_pvalue: bool,
    regulator_subset: tuple[str, ...] = (),
    param_prefix: str = "p",
    round_decimals: int = DEFAULT_FLOAT_DECIMALS,
    tie_rule: str = "avg_rank",
) -> tuple[str, dict[str, Any]]:
    """
    Return a SELECT producing every variant of one pair at once (stage C).

    Reads the stage A and stage B tables, never parquet. Ranking, the
    intersecting-target restriction and the aggregation are identical to
    :func:`topn_pair_select_sql`; the difference is that all ``top_n`` cutoffs and all
    threshold pairs are emitted from a single scan-and-rank instead of one query each.

    ``TOP_N_ALL`` is handled inline by the cutoff join rather than as a separate query:
    ``c.top_n = 0`` keeps every ranked row, which is what the sentinel means.

    :param binding_table: Stage A table name.
    :param binding_hf_repo: HuggingFace repo for the binding dataset.
    :param binding_hf_config: HuggingFace config for the binding dataset.
    :param perturbation_table: Stage B table name.
    :param pert_hf_repo: HuggingFace repo for the perturbation dataset.
    :param pert_hf_config: HuggingFace config for the perturbation dataset.
    :param rank_col: Ranking column name, emitted as a literal result column.
    :param rank_asc: If ``True``, lower values rank better (p-values).
    :param top_n_values: Cutoffs to emit; ``TOP_N_ALL`` means "no cutoff".
    :param threshold_pairs: ``(effect, pvalue)`` pairs to emit.
    :param has_pvalue: Whether the perturbation dataset has a usable p-value column.
    :param regulator_subset: If non-empty, restrict to these regulators (for batching).
    :param param_prefix: Namespace prefix for SQL parameters.
    :param round_decimals: Decimal places kept for ``responsive_ratio``.
    :param tie_rule: How ties decide membership of the top N; see :data:`TIE_RULES`.
    :returns: ``(sql, params)`` tuple.
    :rtype: tuple[str, dict]

    """
    _check_tie_rule(tie_rule)
    if not top_n_values or not threshold_pairs:
        raise ValueError("top_n_values and threshold_pairs must both be non-empty")

    params: dict[str, Any] = {}
    rank_dir = "ASC" if rank_asc else "DESC"

    reg_where = ""
    if regulator_subset:
        reg_ph = ", ".join(
            f"$reg_{param_prefix}_{i}" for i in range(len(regulator_subset))
        )
        for i, reg in enumerate(regulator_subset):
            params[f"reg_{param_prefix}_{i}"] = reg
        reg_where = f"WHERE regulator_locus_tag IN ({reg_ph})"

    cutoff_key = f"{param_prefix}_cutoffs"
    params[cutoff_key] = list(top_n_values)

    # Threshold pairs as a literal VALUES list. These are floats resolved from
    # DEFAULT_RESPONSIVENESS_PRESETS, never user input.
    pairs_sql = ", ".join(f"({e!r}, {pv!r})" for e, pv in threshold_pairs)

    responsive_expr = (
        "CASE WHEN ABS(pert.effect) > v.eff_thresh"
        " AND pert.pvalue < v.pval_thresh THEN 1 ELSE 0 END"
        if has_pvalue
        else "CASE WHEN ABS(pert.effect) > v.eff_thresh THEN 1 ELSE 0 END"
    )

    b_prefix = f"{binding_hf_repo};{binding_hf_config};".replace("'", "''")
    p_prefix = f"{pert_hf_repo};{pert_hf_config};".replace("'", "''")
    rank_col_safe = rank_col.replace("'", "''")
    rank_asc_sql = "TRUE" if rank_asc else "FALSE"
    ratio_expr = round_expr(
        f"SUM({responsive_expr})::DOUBLE / COUNT(*)", round_decimals
    )
    cutoff_rank = _cutoff_rank_expr(
        tie_rule,
        "b.binding_sample_id",
        f"b.rank_value {rank_dir}",
        "b.rank_value",
    )

    sql = f"""
    WITH binding AS (
        SELECT * FROM {binding_table}
        {reg_where}
    ),
    perturbation AS (
        SELECT * FROM {perturbation_table}
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
            {cutoff_rank} AS rnk
        FROM binding b
        INNER JOIN intersecting_targets it
            ON  b.regulator_locus_tag = it.regulator_locus_tag
            AND b.target_locus_tag    = it.target_locus_tag
        WHERE b.regulator_locus_tag != b.target_locus_tag
    ),
    cutoffs AS (
        SELECT unnest(${cutoff_key}::INTEGER[]) AS top_n
    ),
    thresholds AS (
        SELECT * FROM (VALUES {pairs_sql}) AS v(eff_thresh, pval_thresh)
    ),
    top_n_binding AS (
        SELECT
            r.binding_sample_id,
            r.regulator_locus_tag,
            r.target_locus_tag,
            c.top_n
        FROM binding_ranked r
        JOIN cutoffs c
            ON c.top_n = {TOP_N_ALL} OR r.rnk <= c.top_n
    ),
    summary AS (
        SELECT
            b.binding_sample_id,
            b.regulator_locus_tag,
            pert.perturbation_sample_id,
            b.top_n,
            v.eff_thresh,
            v.pval_thresh,
            COUNT(*)                                   AS n,
            SUM({responsive_expr})::INTEGER            AS n_responsive,
            {ratio_expr}                               AS responsive_ratio
        FROM top_n_binding b
        JOIN perturbation pert
            ON  b.regulator_locus_tag = pert.regulator_locus_tag
            AND b.target_locus_tag    = pert.target_locus_tag
        CROSS JOIN thresholds v
        GROUP BY b.binding_sample_id, b.regulator_locus_tag,
                 pert.perturbation_sample_id, b.top_n, v.eff_thresh, v.pval_thresh
    )
    SELECT
        '{b_prefix}' || s.binding_sample_id         AS binding_source_sample,
        '{p_prefix}' || s.perturbation_sample_id    AS perturbation_source_sample,
        s.regulator_locus_tag,
        s.top_n::INTEGER                            AS top_n,
        '{rank_col_safe}'                           AS rank_col,
        {rank_asc_sql}                              AS rank_asc,
        s.eff_thresh::DOUBLE                        AS effect_threshold,
        s.pval_thresh::DOUBLE                       AS pvalue_threshold,
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
