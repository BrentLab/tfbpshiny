"""
Unit tests for the method-comparison-aware DTO query, ``fetch_dto_results_method_
intersected``.

DTO significance is pre-computed entirely externally, so a regulator missing from one
method's binding data can never get a real empirical p-value -- the fair comparison for
the Compare Analysis Methods tab is a shared 3-way regulator intersection (promoter_
enrichment x peak_calling x perturbation), not each bar's own pairwise intersection.
Uses an in-memory DuckDB connection, same convention as ``test_figures.py``'s DTO
fixtures -- no reactive context, no real materialized database.

"""

from __future__ import annotations

import duckdb

from tfbpshiny.modules.comparison.queries import fetch_dto_results_method_intersected


def _dto_method_db() -> duckdb.DuckDBPyConnection:
    """
    Rossi-shaped fixture: promoter_enrichment covers REG1/REG2/REG3, peak_calling
    covers only REG1/REG2 (REG3 has no called peaks), perturbation covers all three.
    DTO itself only has rows for REG1 (both methods) and REG2 (promoter_enrichment
    only, to exercise ``n_covered`` staying below ``n_intersect``).

    """
    conn = duckdb.connect()
    conn.execute(
        "CREATE TABLE sample_regulator (db_name VARCHAR, sample_id VARCHAR,"
        " regulator_locus_tag VARCHAR)"
    )
    conn.execute(
        "INSERT INTO sample_regulator VALUES"
        " ('pe', 's1', 'REG1'), ('pe', 's2', 'REG2'), ('pe', 's3', 'REG3'),"
        " ('pc', 's1', 'REG1'), ('pc', 's2', 'REG2'),"
        " ('pr', 's1', 'REG1'), ('pr', 's2', 'REG2'), ('pr', 's3', 'REG3')"
    )
    for db in ("pe", "pc", "pr"):
        conn.execute(f'CREATE TABLE "{db}_meta" (sample_id VARCHAR)')
        rows = conn.execute(
            f"SELECT DISTINCT sample_id FROM sample_regulator WHERE db_name = '{db}'"
        ).fetchall()
        for (sid,) in rows:
            conn.execute(f'INSERT INTO "{db}_meta" VALUES (?)', [sid])
    conn.execute(
        "CREATE TABLE dto (binding_db VARCHAR, perturbation_db VARCHAR,"
        " regulator_locus_tag VARCHAR, pr_ranking_column VARCHAR,"
        " binding_sample_id VARCHAR, perturbation_sample_id VARCHAR,"
        " dto_empirical_pvalue DOUBLE)"
    )
    conn.execute(
        """INSERT INTO dto VALUES
        ('pe', 'pr', 'REG1', 'log2fc', 's1', 's1', 0.001),
        ('pc', 'pr', 'REG1', 'log2fc', 's1', 's1', 0.5),
        ('pe', 'pr', 'REG2', 'log2fc', 's2', 's2', 0.02)
        """
    )
    return conn


def test_both_methods_share_the_3way_intersected_denominator() -> None:
    """REG3 (promoter_enrichment only) must not inflate either method's denominator;
    both rows get the same n_intersect, restricted to REG1/REG2."""
    conn = _dto_method_db()
    df = fetch_dto_results_method_intersected(conn, [("pe", "pc", "pr")], {})
    assert set(df["n_intersect"]) == {2}
    assert set(df["binding_db"]) == {"pe", "pc"}


def test_significance_counted_within_the_shared_universe() -> None:
    conn = _dto_method_db()
    df = fetch_dto_results_method_intersected(conn, [("pe", "pc", "pr")], {})
    pe_row = df[df["binding_db"] == "pe"].iloc[0]
    pc_row = df[df["binding_db"] == "pc"].iloc[0]
    # pe: REG1 (0.001, significant) + REG2 (0.02, not significant at 0.01) covered.
    assert pe_row["n_significant"] == 1
    assert pe_row["n_covered"] == 2
    # pc: only REG1 tested (0.5, not significant); REG2 was never tested for pc.
    assert pc_row["n_significant"] == 0
    assert pc_row["n_covered"] == 1


def test_empty_intersection_is_omitted() -> None:
    conn = _dto_method_db()
    conn.execute("DELETE FROM sample_regulator WHERE db_name = 'pr'")
    df = fetch_dto_results_method_intersected(conn, [("pe", "pc", "pr")], {})
    assert df.empty


def test_no_cells_returns_empty_frame() -> None:
    conn = _dto_method_db()
    df = fetch_dto_results_method_intersected(conn, [], {})
    assert df.empty
