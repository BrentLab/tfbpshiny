"""
SQL generators for the ``topn_agreement`` table.

Answers "how much do two datasets of the *same* type agree?" by intersecting each
regulator's top-N target sets. Enrichment over random expectation is computed at query
time rather than stored, so the gene-universe constant can be revisited without a
rebuild.

Functions return SQL strings (no side effects) so they can be inspected from a notebook;
the coordinator is the only thing that executes them.

"""

from __future__ import annotations

from typing import Any

#: Rank cutoffs at which set overlap is measured. Log-spaced to 500: agreement changes
#: fastest at the top of the ranking, and a linear grid would spend most of its points
#: in the flat tail.
AGREEMENT_TOP_N: tuple[int, ...] = (
    10,
    25,
    50,
    75,
    100,
    150,
    200,
    300,
    400,
    500,
)

#: Gene universe used for the random expectation, ``(N / GENE_UNIVERSE) * N``.
GENE_UNIVERSE = 6000

#: Binding datasets excluded from the agreement analysis.
#:
#: The authors' original peak calls carry ``promoter_set_id = 'peaks'`` -- regions from
#: their own pipeline, not a fixed upstream window. Any pair involving one therefore
#: differs in *both* the caller and the region definition, and a low overlap cannot be
#: attributed to either. The promoter-set-matched re-calls
#: (``rossi_peaks_500bp`` and friends) carry the same information against a defined
#: window, and are kept.
AGREEMENT_EXCLUDED: frozenset[str] = frozenset({"rossi_peaks", "chec_m2025_peaks"})


def agreement_schema_sql() -> str:
    """
    Return the ``CREATE TABLE topn_agreement`` DDL.

    Stores raw overlap counts only. Log enrichment is derived at read time as
    ``log2(n_intersect * GENE_UNIVERSE / top_n^2)``.

    :returns: ``CREATE TABLE`` SQL string.
    :rtype: str

    """
    return """
CREATE TABLE topn_agreement (
    source_sample_a     VARCHAR  NOT NULL,
    source_sample_b     VARCHAR  NOT NULL,
    comparison_type     VARCHAR  NOT NULL,
    regulator_locus_tag VARCHAR  NOT NULL,
    top_n               INTEGER  NOT NULL,
    n_a                 INTEGER  NOT NULL,
    n_b                 INTEGER  NOT NULL,
    n_intersect         INTEGER  NOT NULL,
    PRIMARY KEY (
        source_sample_a, source_sample_b, regulator_locus_tag, top_n
    )
);
"""


def agreement_pair_select_sql(
    view_a: str,
    hf_repo_a: str,
    hf_config_a: str,
    sample_col_a: str,
    rank_col_a: str,
    rank_asc_a: bool,
    view_b: str,
    hf_repo_b: str,
    hf_config_b: str,
    sample_col_b: str,
    rank_col_b: str,
    rank_asc_b: bool,
    comparison_type: str,
    top_n_values: tuple[int, ...] = AGREEMENT_TOP_N,
    regulator_subset: tuple[str, ...] = (),
    param_prefix: str = "a",
) -> tuple[str, dict[str, Any]]:
    """
    Return a SELECT producing ``topn_agreement`` rows for one same-type dataset pair.

    Each side is ranked independently within a sample, then the top-N sets are
    intersected per regulator at every cutoff.

    Ranking uses ``ROW_NUMBER()`` rather than the ``RANK()`` used by ``topn_results``.
    Set sizes must be exactly N here: the overlap is compared against an expectation of
    ``N^2 / GENE_UNIVERSE``, so a tie inflating one side's set would inflate the
    intersection and read as agreement.

    **Perturbation datasets are ranked by absolute effect**, so a knockout and an
    overexpression experiment are ordered by magnitude of response rather than sign and
    can be compared to each other.

    :param view_a: First dataset's VirtualDB view.
    :param hf_repo_a: First dataset's HF repo.
    :param hf_config_a: First dataset's HF config.
    :param sample_col_a: First dataset's sample id column.
    :param rank_col_a: First dataset's ranking column.
    :param rank_asc_a: Whether a smaller value ranks better for the first dataset.
    :param view_b: Second dataset's VirtualDB view.
    :param hf_repo_b: Second dataset's HF repo.
    :param hf_config_b: Second dataset's HF config.
    :param sample_col_b: Second dataset's sample id column.
    :param rank_col_b: Second dataset's ranking column.
    :param rank_asc_b: Whether a smaller value ranks better for the second dataset.
    :param comparison_type: ``'binding'`` or ``'perturbation'``.
    :param top_n_values: Cutoffs to measure at.
    :param regulator_subset: Restrict to these regulators (for batching).
    :param param_prefix: Namespace prefix for SQL parameters.
    :returns: ``(sql, params)``.

    """
    params: dict[str, Any] = {}

    dir_a = "ASC" if rank_asc_a else "DESC"
    dir_b = "ASC" if rank_asc_b else "DESC"

    # Perturbation effect sizes are signed; magnitude is what makes a knockout and an
    # overexpression comparable.
    expr_a = f"ABS({rank_col_a})" if comparison_type == "perturbation" else rank_col_a
    expr_b = f"ABS({rank_col_b})" if comparison_type == "perturbation" else rank_col_b

    reg_clause_a = reg_clause_b = ""
    if regulator_subset:
        ph = ", ".join(f"${param_prefix}_reg_{i}" for i in range(len(regulator_subset)))
        for i, reg in enumerate(regulator_subset):
            params[f"{param_prefix}_reg_{i}"] = reg
        reg_clause_a = f"WHERE regulator_locus_tag IN ({ph})"
        reg_clause_b = reg_clause_a

    n_list = ", ".join(f"({n})" for n in top_n_values)
    a_prefix = f"{hf_repo_a};{hf_config_a};".replace("'", "''")
    b_prefix = f"{hf_repo_b};{hf_config_b};".replace("'", "''")
    ctype = comparison_type.replace("'", "''")

    # Set sizes are computed independently of the intersection: measuring them inside
    # the intersection join would report the overlap rather than each set's true size.
    # The final join is a LEFT JOIN so regulators whose top-N sets are disjoint still
    # produce a row with n_intersect = 0, which is a real and interesting result.
    sql = f"""
    WITH cutoffs(top_n) AS (VALUES {n_list}),
    ranked_a AS (
        SELECT CAST({sample_col_a} AS VARCHAR) AS sample_id,
               regulator_locus_tag,
               target_locus_tag,
               ROW_NUMBER() OVER (
                   PARTITION BY {sample_col_a}, regulator_locus_tag
                   ORDER BY {expr_a} {dir_a}
               ) AS rnk
        FROM {view_a}
        {reg_clause_a}
    ),
    ranked_b AS (
        SELECT CAST({sample_col_b} AS VARCHAR) AS sample_id,
               regulator_locus_tag,
               target_locus_tag,
               ROW_NUMBER() OVER (
                   PARTITION BY {sample_col_b}, regulator_locus_tag
                   ORDER BY {expr_b} {dir_b}
               ) AS rnk
        FROM {view_b}
        {reg_clause_b}
    ),
    sizes_a AS (
        SELECT a.sample_id, a.regulator_locus_tag, c.top_n,
               count(*) AS n_a
        FROM cutoffs c JOIN ranked_a a ON a.rnk <= c.top_n
        GROUP BY a.sample_id, a.regulator_locus_tag, c.top_n
    ),
    sizes_b AS (
        SELECT b.sample_id, b.regulator_locus_tag, c.top_n,
               count(*) AS n_b
        FROM cutoffs c JOIN ranked_b b ON b.rnk <= c.top_n
        GROUP BY b.sample_id, b.regulator_locus_tag, c.top_n
    ),
    inter AS (
        SELECT a.sample_id AS sample_a, b.sample_id AS sample_b,
               a.regulator_locus_tag, c.top_n,
               count(*) AS n_intersect
        FROM cutoffs c
        JOIN ranked_a a ON a.rnk <= c.top_n
        JOIN ranked_b b
          ON  b.regulator_locus_tag = a.regulator_locus_tag
          AND b.target_locus_tag    = a.target_locus_tag
          AND b.rnk <= c.top_n
        GROUP BY a.sample_id, b.sample_id, a.regulator_locus_tag, c.top_n
    )
    SELECT
        '{a_prefix}' || sa.sample_id        AS source_sample_a,
        '{b_prefix}' || sb.sample_id        AS source_sample_b,
        '{ctype}'                           AS comparison_type,
        sa.regulator_locus_tag,
        sa.top_n::INTEGER                   AS top_n,
        sa.n_a::INTEGER                     AS n_a,
        sb.n_b::INTEGER                     AS n_b,
        COALESCE(i.n_intersect, 0)::INTEGER AS n_intersect
    FROM sizes_a sa
    JOIN sizes_b sb
      ON  sb.regulator_locus_tag = sa.regulator_locus_tag
      AND sb.top_n               = sa.top_n
    LEFT JOIN inter i
      ON  i.sample_a            = sa.sample_id
      AND i.sample_b            = sb.sample_id
      AND i.regulator_locus_tag = sa.regulator_locus_tag
      AND i.top_n               = sa.top_n
    """
    return sql, params


__all__ = [
    "AGREEMENT_EXCLUDED",
    "AGREEMENT_TOP_N",
    "GENE_UNIVERSE",
    "agreement_pair_select_sql",
    "agreement_schema_sql",
]
