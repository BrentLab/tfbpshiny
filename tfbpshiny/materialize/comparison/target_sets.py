"""
SQL generators for the ``topn_target_sets`` table.

Stores the *actual* ranked target lists, per sample and regulator, for the datasets
figure 10 draws. ``topn_agreement`` keeps only overlap counts, which cannot draw a Venn
diagram, and is measured on a fixed 10-200 grid that does not contain every Top N the
Figures sidebar offers (25 and 75 are missing). Holding the lists lets figure 10 derive
both the Venn sets and the pairwise overlap counts at whatever Top N is selected, from
one source, so the two panels cannot disagree.

Ranking follows ``agreement.py`` (``ROW_NUMBER``, the same rank-column overrides,
absolute effect for perturbation datasets, ``target_locus_tag`` as the final sort key),
with one deliberate difference: **duplicate rows for a target are collapsed first**.
Kemmeren and Hackett measure some genes with several probes, so the same
(sample, regulator, target) appears twice; ranking those rows separately would count one
target twice and leave fewer than N distinct targets in a "top N" set. ``agreement.py``
does not do this, so where a duplicated target sits near a cutoff the two can differ
by a target or so.

Functions return SQL strings (no side effects); the coordinator is the only code that
executes them.

"""

from __future__ import annotations

from tfbpshiny.datasets import FIGURE_BINDING_500BP, HEADLINE_PERTURBATION

#: Largest Top N the Figures sidebar offers. Ranks beyond this are not stored.
TARGET_SET_MAX_N = 100

#: Binding datasets figure 10 compares: the three 500bp figure datasets.
TARGET_SET_BINDING: tuple[str, ...] = FIGURE_BINDING_500BP

#: Perturbation datasets figure 10 compares: the three headline datasets.
TARGET_SET_PERTURBATION: tuple[str, ...] = HEADLINE_PERTURBATION


def target_sets_schema_sql() -> str:
    """
    Return the ``CREATE TABLE topn_target_sets`` DDL.

    :returns: ``CREATE TABLE`` SQL string.

    """
    return """
CREATE TABLE topn_target_sets (
    source_sample       VARCHAR  NOT NULL,
    comparison_type     VARCHAR  NOT NULL,
    regulator_locus_tag VARCHAR  NOT NULL,
    target_locus_tag    VARCHAR  NOT NULL,
    rnk                 INTEGER  NOT NULL,
    db_name             VARCHAR  NOT NULL,
    sample_id           VARCHAR  NOT NULL,
    PRIMARY KEY (source_sample, regulator_locus_tag, target_locus_tag)
);
"""


def target_sets_select_sql(
    view: str,
    hf_repo: str,
    hf_config: str,
    sample_col: str,
    rank_col: str,
    rank_asc: bool,
    comparison_type: str,
    max_n: int = TARGET_SET_MAX_N,
    drop_null_scores: bool = False,
) -> str:
    """
    Return a SELECT producing ``topn_target_sets`` rows for one dataset.

    Every sample's top ``max_n`` targets per regulator, with their rank. Whether a
    target is "in the top N" is then ``rnk <= N`` at read time, for any ``N`` up to
    ``max_n``.

    Perturbation datasets are ranked by absolute effect, as in ``agreement.py``.

    :param view: The dataset's VirtualDB view.
    :param hf_repo: The dataset's HF repo.
    :param hf_config: The dataset's HF config.
    :param sample_col: The dataset's sample id column.
    :param rank_col: Ranking column.
    :param rank_asc: Whether a smaller value ranks better.
    :param comparison_type: ``'binding'`` or ``'perturbation'``.
    :param max_n: Deepest rank to keep.
    :param drop_null_scores: Rank only rows with a non-NULL score. Required for the
        dense peak-calling datasets, which list every promoter with a NULL score where
        no peak qualified; without it a short list is padded with no-peak promoters
        (see ``agreement.py``'s ``drop_null_scores_a``).
    :returns: SELECT SQL (no parameters).

    """
    direction = "ASC" if rank_asc else "DESC"
    expr = f"ABS({rank_col})" if comparison_type == "perturbation" else rank_col
    prefix = f"{hf_repo};{hf_config};".replace("'", "''")
    ctype = comparison_type.replace("'", "''")
    db_safe = view.replace("'", "''")
    where = f"WHERE {rank_col} IS NOT NULL" if drop_null_scores else ""
    return f"""
    WITH dedup AS (
        SELECT CAST({sample_col} AS VARCHAR) AS sample_id,
               regulator_locus_tag,
               target_locus_tag,
               {expr} AS rank_value
        FROM {view}
        {where}
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY {sample_col}, regulator_locus_tag, target_locus_tag
            ORDER BY {expr} {direction}
        ) = 1
    ),
    ranked AS (
        SELECT sample_id,
               regulator_locus_tag,
               target_locus_tag,
               ROW_NUMBER() OVER (
                   PARTITION BY sample_id, regulator_locus_tag
                   ORDER BY rank_value {direction}, target_locus_tag
               ) AS rnk
        FROM dedup
    )
    SELECT '{prefix}' || sample_id AS source_sample,
           '{ctype}'              AS comparison_type,
           regulator_locus_tag,
           target_locus_tag,
           rnk::INTEGER           AS rnk,
           '{db_safe}'            AS db_name,
           sample_id
    FROM ranked
    WHERE rnk <= {int(max_n)}
    """


__all__ = [
    "TARGET_SET_BINDING",
    "TARGET_SET_MAX_N",
    "TARGET_SET_PERTURBATION",
    "target_sets_schema_sql",
    "target_sets_select_sql",
]
