"""
Unit tests for the method x promoter-set model.

These test the pure-function core (`fit_method_promoter_model`, `build_method_
promoter_panel`) against synthetic data -- no database, no reactive context, matching
this project's convention that server logic without a Shiny-testing API is only
unit-tested through the pure functions extracted from it.

"""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd
import pytest

from tfbpshiny.materialize.comparison.method_promoter_model import (
    ASSAY_PRIMARIES,
    METHOD_LEVELS,
    PROMOTER_SET_LEVELS,
    _allowed_sample_ids,
    _regulator_intersection,
    _resolve_cell,
    build_method_promoter_panel,
    default_filters,
    fit_method_promoter_model,
    method_promoter_model_schema_sql,
    method_promoter_model_topn_schema_sql,
    pair_methods_on_regulators,
    promoter_set_target_universe,
    resolve_panel_cells,
)


def _synthetic_panel(
    n_regulators: int = 30,
    *,
    seed: int = 0,
    method_effect: float = 0.0,
    promoter_set_effect: dict[str, float] | None = None,
    regulator_baseline_spread: float = 0.3,
) -> pd.DataFrame:
    """
    Build a full 16-cell panel over `n_regulators` synthetic regulators.

    :param method_effect: Uniform peak-calling effect (percentage points, on the
        response-rate scale) applied to every regulator.
    :param promoter_set_effect: Per-promoter-set additive shift (vs. kang), for
        planting a recoverable promoter-set contrast.
    :param regulator_baseline_spread: Std. dev. of each regulator's own baseline
        responsiveness -- the heterogeneity the fixed effect must absorb.

    """
    rng = np.random.default_rng(seed)
    promoter_set_effect = promoter_set_effect or {}
    rows = []
    for i in range(n_regulators):
        reg = f"REG{i}"
        reg_baseline = float(
            np.clip(rng.normal(0.3, regulator_baseline_spread), 0.05, 0.95)
        )
        for assay in ASSAY_PRIMARIES:
            for method in METHOD_LEVELS:
                for promoter_set in PROMOTER_SET_LEVELS:
                    n = int(max(5, rng.normal(25, 2)))
                    shift = (
                        method_effect if method == "peak_calling" else 0.0
                    ) + promoter_set_effect.get(promoter_set, 0.0)
                    p = float(np.clip(reg_baseline + shift, 0.01, 0.99))
                    succ = int(rng.binomial(n, p))
                    rows.append(
                        {
                            "regulator_locus_tag": reg,
                            "method": method,
                            "promoter_set": promoter_set,
                            "assay": assay,
                            "n": n,
                            "n_responsive": succ,
                            "n_intersecting_targets": n + int(rng.integers(0, 5)),
                        }
                    )
    panel = pd.DataFrame(rows)
    panel["n_non_responsive"] = panel["n"] - panel["n_responsive"]
    panel["responsive_ratio"] = panel["n_responsive"] / panel["n"]
    return panel


def _registry_df() -> pd.DataFrame:
    """A minimal `dataset_registry`-shaped frame covering the 16-cell panel."""
    rows = []
    for assay in ASSAY_PRIMARIES:
        rows.append(
            {
                "db_name": assay,
                "hf_repo": "R",
                "hf_config": assay,
                "primary_db_name": None,
                "promoter_set_id": "500bp",
                "binding_method_id": "promoter_enrichment",
            }
        )
        for promoter_set in PROMOTER_SET_LEVELS:
            if promoter_set != "500bp":
                rows.append(
                    {
                        "db_name": f"{assay}_{promoter_set}",
                        "hf_repo": "R",
                        "hf_config": f"{assay}_{promoter_set}",
                        "primary_db_name": assay,
                        "promoter_set_id": promoter_set,
                        "binding_method_id": "promoter_enrichment",
                    }
                )
            rows.append(
                {
                    "db_name": f"{assay}_peaks_{promoter_set}",
                    "hf_repo": "R",
                    "hf_config": f"{assay}_peaks_{promoter_set}",
                    "primary_db_name": assay,
                    "promoter_set_id": promoter_set,
                    "binding_method_id": "peak_calling",
                }
            )
    # A non-participating dataset: no peak arm (like Calling Cards).
    rows.append(
        {
            "db_name": "callingcards_500bp",
            "hf_repo": "R",
            "hf_config": "callingcards_500bp",
            "primary_db_name": None,
            "promoter_set_id": "500bp",
            "binding_method_id": "promoter_enrichment",
        }
    )
    # Harbison: array probes, excluded structurally.
    rows.append(
        {
            "db_name": "harbison",
            "hf_repo": "R",
            "hf_config": "harbison_2004",
            "primary_db_name": None,
            "promoter_set_id": "array",
            "binding_method_id": "promoter_enrichment",
        }
    )
    # The authors' original peaks: `promoter_set_id='peaks'`, excluded structurally.
    for assay in ASSAY_PRIMARIES:
        rows.append(
            {
                "db_name": f"{assay}_authors_peaks",
                "hf_repo": "R",
                "hf_config": f"{assay}_authors_peaks",
                "primary_db_name": assay,
                "promoter_set_id": "peaks",
                "binding_method_id": "peak_calling",
            }
        )
    rows.append(
        {
            "db_name": "kemmeren",
            "hf_repo": "R",
            "hf_config": "kemmeren_2014",
            "primary_db_name": None,
            "promoter_set_id": None,
            "binding_method_id": None,
        }
    )
    return pd.DataFrame(rows)


def _meta_conn(regulators_by_db: dict[str, list[str]]) -> duckdb.DuckDBPyConnection:
    """An in-memory connection with one `{db}_meta` table per entry, sample_id=1."""
    conn = duckdb.connect()
    for db, regs in regulators_by_db.items():
        df = pd.DataFrame({"sample_id": [1] * len(regs), "regulator_locus_tag": regs})
        conn.register(f"_{db}", df)
        conn.execute(f'CREATE TABLE "{db}_meta" AS SELECT * FROM _{db}')
    return conn


# --- schema --------------------------------------------------------------------


def test_schema_creates_both_tables() -> None:
    """The DDL string must be valid SQL that creates both tables."""
    conn = duckdb.connect()
    conn.execute(method_promoter_model_schema_sql())
    conn.execute(method_promoter_model_topn_schema_sql())
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT table_name FROM duckdb_tables() WHERE table_name LIKE"
            " 'method_promoter_model%'"
        ).fetchall()
    }
    assert tables == {
        "method_promoter_model_coefs",
        "method_promoter_model_fit_summary",
        "method_promoter_model_topn",
    }


# --- panel assembly / exclusions ------------------------------------------------


def test_resolve_cell_finds_the_right_db_name() -> None:
    registry = _registry_df()
    assert (
        _resolve_cell(registry, "rossi_500bp", "500bp", "promoter_enrichment")
        == "rossi_500bp"
    )
    assert (
        _resolve_cell(registry, "rossi_500bp", "kang", "peak_calling")
        == "rossi_500bp_peaks_kang"
    )
    assert _resolve_cell(registry, "rossi_500bp", "nonexistent", "peak_calling") is None


def test_panel_excludes_harbison_callingcards_and_authors_peaks() -> None:
    """
    The panel must never include the three structurally-excluded dataset groups.

    Harbison has no re-quantifiable window (`promoter_set_id='array'`); the authors'
    original peaks have no fixed window (`promoter_set_id='peaks'`); Calling Cards has
    no peak-calling arm. This test pins the resolved *db_names* directly.

    """
    registry = _registry_df()
    resolved = set()
    for assay in ASSAY_PRIMARIES:
        for method in METHOD_LEVELS:
            for promoter_set in PROMOTER_SET_LEVELS:
                db = _resolve_cell(registry, assay, promoter_set, method)
                if db is not None:
                    resolved.add(db)
    assert len(resolved) == 16, sorted(resolved)
    assert "harbison" not in resolved
    assert "callingcards_500bp" not in resolved
    assert not any("authors_peaks" in d for d in resolved)


def test_resolve_panel_cells_matches_resolve_cell_for_all_16() -> None:
    """`resolve_panel_cells` must agree with individually calling `_resolve_cell`."""
    registry = _registry_df()
    cells = resolve_panel_cells(registry)
    assert len(cells) == 16
    for (assay, promoter_set, method), db in cells.items():
        assert _resolve_cell(registry, assay, promoter_set, method) == db


class _FakeVdb:
    """Stub with a `.query()` returning canned per-view target lists."""

    def __init__(self, targets_by_view: dict[str, list[str]]) -> None:
        self._targets_by_view = targets_by_view

    def query(self, sql: str) -> pd.DataFrame:
        for view, targets in self._targets_by_view.items():
            if sql.strip().endswith(f"FROM {view}"):
                return pd.DataFrame({"target_locus_tag": targets})
        raise AssertionError(f"unexpected query: {sql}")


def _eight_views(assay: str, targets: dict[str, list[str]]) -> dict[str, list[str]]:
    """
    Target lists for the assay's 8 views, keyed by the db_name the registry gives them.

    ``targets`` maps ``"<method>:<promoter_set>"`` to that view's list.

    """
    views = {}
    for method in ("promoter_enrichment", "peak_calling"):
        for ps in PROMOTER_SET_LEVELS:
            if method == "peak_calling":
                name = f"{assay}_peaks_{ps}"
            else:
                name = assay if ps == "500bp" else f"{assay}_{ps}"
            views[name] = targets[f"{method}:{ps}"]
    return views


def test_promoter_set_target_universe_intersects_all_eight_views() -> None:
    """Both methods contribute: no view is privileged as the source of truth."""
    registry = _registry_df()
    base = {
        f"{m}:{ps}": ["B", "C", "X"]
        for m in METHOD_LEVELS
        for ps in PROMOTER_SET_LEVELS
    }
    base["promoter_enrichment:500bp"] = ["A", "B", "C", "X"]
    # A target present in all four enrichment views but missing from ONE peak view is
    # excluded -- an enrichment-only intersection would have kept it.
    base["peak_calling:kang"] = ["B", "C"]
    vdb = _FakeVdb(_eight_views("rossi_500bp", base))
    assert promoter_set_target_universe(vdb, registry, "rossi_500bp") == frozenset(
        {"B", "C"}
    )


def test_promoter_set_target_universe_empty_when_a_view_is_missing() -> None:
    """If any of the eight views doesn't resolve, the universe must be empty rather than
    silently computed from fewer than eight."""
    registry = _registry_df()
    registry = registry[registry["db_name"] != "rossi_500bp_peaks_mindel"]
    base = {
        f"{m}:{ps}": ["A", "B"] for m in METHOD_LEVELS for ps in PROMOTER_SET_LEVELS
    }
    vdb = _FakeVdb(_eight_views("rossi_500bp", base))
    assert promoter_set_target_universe(vdb, registry, "rossi_500bp") == frozenset()


def _populate_method_promoter_topn(
    conn: duckdb.DuckDBPyConnection, registry: pd.DataFrame, regulators: list[str]
) -> None:
    conn.execute(
        "CREATE TABLE method_promoter_model_topn (binding_source_sample VARCHAR,"
        " perturbation_source_sample VARCHAR, regulator_locus_tag VARCHAR,"
        " top_n INTEGER, effect_threshold DOUBLE, pvalue_threshold DOUBLE,"
        " n INTEGER, n_responsive INTEGER, n_intersecting_targets INTEGER,"
        " binding_db VARCHAR, binding_sample_id VARCHAR, perturbation_db VARCHAR,"
        " perturbation_sample_id VARCHAR)"
    )
    rows = []
    for _, r in registry.iterrows():
        if pd.isna(r["promoter_set_id"]) or r["promoter_set_id"] in ("array", "peaks"):
            continue
        if r["db_name"] == "callingcards_500bp":
            continue
        prefix = f"{r['hf_repo']};{r['hf_config']};"
        for reg in regulators:
            rows.append(
                (
                    f"{prefix}s1",
                    "R;kemmeren_2014;s1",
                    reg,
                    25,
                    0.0,
                    0.05,
                    20,
                    10,
                    20,
                    r["db_name"],
                    "s1",
                    "kemmeren",
                    "s1",
                )
            )
    conn.executemany(
        "INSERT INTO method_promoter_model_topn VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )


#: The default-filter column and passing value for each assay primary, as in
#: ``DEFAULT_DATASET_FILTERS``. Fixture meta tables must carry the column, because the
#: panel now (correctly) applies that filter to these datasets.
_ASSAY_FILTER_COLUMN = {
    "rossi_500bp": ("treatment", "Normal"),
    "chec_m2025_500bp": ("Experimental condition", "standard"),
}


def _assay_meta(db: str, rows: list[tuple[str, str, str | None]]) -> pd.DataFrame:
    """``(sample_id, regulator, filter_value)`` rows as an assay meta frame; a ``None``
    filter value takes the dataset's passing default."""
    col, passing = _ASSAY_FILTER_COLUMN[db]
    return pd.DataFrame(
        {
            "sample_id": [r[0] for r in rows],
            "regulator_locus_tag": [r[1] for r in rows],
            col: [passing if r[2] is None else r[2] for r in rows],
        }
    )


def _create_assay_metas(
    conn: duckdb.DuckDBPyConnection,
    rows_by_assay: dict[str, list[tuple[str, str, str | None]]],
) -> None:
    """
    Create ``{db}_meta`` for each assay primary *and every variant of it*.

    Variants inherit their primary's default filter, so the panel queries each variant's
    own meta table; the real database has one per variant, with the same filter column.

    """
    registry = _registry_df()
    prim = registry["primary_db_name"].fillna(registry["db_name"])
    for db, assay in zip(registry["db_name"], prim):
        if assay in rows_by_assay:
            conn.register("_meta_tmp", _assay_meta(assay, rows_by_assay[assay]))
            conn.execute(f'CREATE TABLE "{db}_meta" AS SELECT * FROM _meta_tmp')
            conn.unregister("_meta_tmp")


def _base_conn(regulators: list[str]) -> duckdb.DuckDBPyConnection:
    """A connection with `dataset_registry`, `method_promoter_model_topn`, and
    `{db}_meta` tables."""
    registry = _registry_df()
    conn = duckdb.connect()
    conn.register("_registry", registry)
    conn.execute("CREATE TABLE dataset_registry AS SELECT * FROM _registry")
    _populate_method_promoter_topn(conn, registry, regulators)
    _create_assay_metas(
        conn, {a: [("s1", r, None) for r in regulators] for a in ASSAY_PRIMARIES}
    )
    conn.register(
        "_kemmeren",
        pd.DataFrame(
            {"sample_id": ["s1"] * len(regulators), "regulator_locus_tag": regulators}
        ),
    )
    conn.execute('CREATE TABLE "kemmeren_meta" AS SELECT * FROM _kemmeren')
    return conn


def test_build_method_promoter_panel_reads_the_16_cells() -> None:
    """
    End-to-end panel assembly against a real (in-memory) `topn_results` table.

    Confirms the SQL join actually runs and produces the expected 16 x n_regulators
    row count, not just that `_resolve_cell` returns the right names.

    """
    conn = _base_conn(["REG0", "REG1"])
    panel = build_method_promoter_panel(
        conn, _registry_df(), "kemmeren", 25, {"*": (0.0, 0.05)}
    )
    assert not panel.empty
    assert set(panel["regulator_locus_tag"].unique()) == {"REG0", "REG1"}
    # 16 cells x 2 regulators.
    assert len(panel) == 32
    assert set(panel["method"].unique()) == set(METHOD_LEVELS)
    assert set(panel["assay"].unique()) == set(ASSAY_PRIMARIES)
    assert "responsive_ratio" in panel.columns


def test_panel_empty_when_perturbation_db_unknown() -> None:
    conn = duckdb.connect()
    conn.execute("CREATE TABLE method_promoter_model_topn (x INTEGER)")
    panel = build_method_promoter_panel(
        conn, _registry_df(), "not_a_real_dataset", 25, {"*": (0.0, 0.05)}
    )
    assert panel.empty


# --- sample-level filtering ------------------------------------------------------


def test_allowed_sample_ids_propagates_primary_filter_to_variant(monkeypatch) -> None:
    """A variant (`rossi_mindel`) is filtered like its primary (`rossi_500bp`)."""
    from tfbpshiny.materialize.comparison import method_promoter_model as mpm

    monkeypatch.setitem(
        mpm.DEFAULT_DATASET_FILTERS,
        "rossi_500bp",
        {"treatment": {"type": "categorical", "value": ["Normal"]}},
    )
    conn = duckdb.connect()
    df = pd.DataFrame(
        {"sample_id": [1, 2, 3], "treatment": ["Normal", "Normal", "Heat shock"]}
    )
    conn.register("_meta", df)
    for db in ("rossi_500bp", "rossi_mindel"):
        conn.execute(f'CREATE TABLE "{db}_meta" AS SELECT * FROM _meta')
    registry = pd.DataFrame(
        [
            {"db_name": "rossi_500bp", "primary_db_name": None},
            {"db_name": "rossi_mindel", "primary_db_name": "rossi_500bp"},
        ]
    )
    for db in ("rossi_500bp", "rossi_mindel"):
        ids = _allowed_sample_ids(conn, default_filters(conn, registry), db)
        assert ids is not None
        assert set(ids) == {"1", "2"}


def test_allowed_sample_ids_returns_none_when_no_default_filter() -> None:
    registry = pd.DataFrame([{"db_name": "kemmeren", "primary_db_name": None}])
    conn = duckdb.connect()
    assert (
        _allowed_sample_ids(conn, default_filters(conn, registry), "kemmeren") is None
    )


def test_panel_respects_default_sample_filter(monkeypatch) -> None:
    """
    A dataset with a default filter must only contribute its allowed samples.

    Two perturbation samples are materialized for the same regulator, one passing the
    fake default filter and one not; only the passing one's row should survive.

    """
    from tfbpshiny.materialize.comparison import method_promoter_model as mpm

    monkeypatch.setitem(
        mpm.DEFAULT_DATASET_FILTERS,
        "kemmeren",
        {"batch": {"type": "categorical", "value": ["keep"]}},
    )
    registry = _registry_df()
    conn = duckdb.connect()
    conn.register("_registry", registry)
    conn.execute("CREATE TABLE dataset_registry AS SELECT * FROM _registry")
    conn.execute(
        "CREATE TABLE method_promoter_model_topn (binding_source_sample VARCHAR,"
        " perturbation_source_sample VARCHAR, regulator_locus_tag VARCHAR,"
        " top_n INTEGER, effect_threshold DOUBLE, pvalue_threshold DOUBLE,"
        " n INTEGER, n_responsive INTEGER, n_intersecting_targets INTEGER,"
        " binding_db VARCHAR, binding_sample_id VARCHAR, perturbation_db VARCHAR,"
        " perturbation_sample_id VARCHAR)"
    )
    b_row = registry[registry["db_name"] == "rossi_500bp"].iloc[0]
    b_prefix = f"{b_row['hf_repo']};{b_row['hf_config']};"
    conn.execute(
        "INSERT INTO method_promoter_model_topn VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            f"{b_prefix}b1",
            "R;kemmeren_2014;keep_s",
            "REG0",
            25,
            0.0,
            0.05,
            20,
            10,
            20,
            "rossi_500bp",
            "b1",
            "kemmeren",
            "keep_s",
        ],
    )
    conn.execute(
        "INSERT INTO method_promoter_model_topn VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            f"{b_prefix}b1",
            "R;kemmeren_2014;drop_s",
            "REG0",
            25,
            0.0,
            0.05,
            20,
            10,
            20,
            "rossi_500bp",
            "b1",
            "kemmeren",
            "drop_s",
        ],
    )
    # A peak-calling partner for the same cell, so REG0 is paired across methods.
    pc_row = registry[registry["db_name"] == "rossi_500bp_peaks_500bp"].iloc[0]
    pc_prefix = f"{pc_row['hf_repo']};{pc_row['hf_config']};"
    conn.execute(
        "INSERT INTO method_promoter_model_topn VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            f"{pc_prefix}b1",
            "R;kemmeren_2014;keep_s",
            "REG0",
            25,
            0.0,
            0.05,
            20,
            4,
            20,
            "rossi_500bp_peaks_500bp",
            "b1",
            "kemmeren",
            "keep_s",
        ],
    )
    conn.execute(
        "INSERT INTO method_promoter_model_topn VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            f"{pc_prefix}b1",
            "R;kemmeren_2014;drop_s",
            "REG0",
            25,
            0.0,
            0.05,
            20,
            4,
            20,
            "rossi_500bp_peaks_500bp",
            "b1",
            "kemmeren",
            "drop_s",
        ],
    )
    conn.execute(
        "CREATE TABLE kemmeren_meta (sample_id VARCHAR, batch VARCHAR,"
        " regulator_locus_tag VARCHAR)"
    )
    conn.execute(
        "INSERT INTO kemmeren_meta VALUES ('keep_s', 'keep', 'REG0'),"
        " ('drop_s', 'drop', 'REG0')"
    )
    _create_assay_metas(conn, {a: [("b1", "REG0", None)] for a in ASSAY_PRIMARIES})

    panel = build_method_promoter_panel(
        conn, registry, "kemmeren", 25, {"*": (0.0, 0.05)}
    )
    assert not panel.empty
    assert (panel["n"] == 20).all()
    # Only the "keep_s" sample should appear -- the "drop_s" rows are filtered out. REG0
    # has a row under both methods in this cell, so it is paired and kept.
    assert len(panel) == 2
    assert set(panel["method"]) == {"promoter_enrichment", "peak_calling"}
    assert set(panel["n_responsive"]) == {10, 4}


def test_a_regulator_with_no_peak_calling_row_is_dropped_not_zero_filled() -> None:
    """The panel invents nothing: REG0 has a promoter-enrichment row but no peak-calling
    row in its cell, so it cannot be compared across methods and is left out."""
    registry = _registry_df()
    conn = duckdb.connect()
    conn.register("_registry", registry)
    conn.execute("CREATE TABLE dataset_registry AS SELECT * FROM _registry")
    conn.execute(
        "CREATE TABLE method_promoter_model_topn (binding_source_sample VARCHAR,"
        " perturbation_source_sample VARCHAR, regulator_locus_tag VARCHAR,"
        " top_n INTEGER, effect_threshold DOUBLE, pvalue_threshold DOUBLE,"
        " n INTEGER, n_responsive INTEGER, n_intersecting_targets INTEGER,"
        " binding_db VARCHAR, binding_sample_id VARCHAR, perturbation_db VARCHAR,"
        " perturbation_sample_id VARCHAR)"
    )
    b_row = registry[registry["db_name"] == "rossi_500bp"].iloc[0]
    conn.execute(
        "INSERT INTO method_promoter_model_topn VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            f"R;{b_row['hf_config']};b1",
            "R;kemmeren_2014;s",
            "REG0",
            25,
            0.0,
            0.05,
            20,
            10,
            20,
            "rossi_500bp",
            "b1",
            "kemmeren",
            "s",
        ],
    )
    conn.execute(
        "CREATE TABLE kemmeren_meta (sample_id VARCHAR, regulator_locus_tag VARCHAR)"
    )
    conn.execute("INSERT INTO kemmeren_meta VALUES ('s', 'REG0')")
    _create_assay_metas(conn, {a: [("b1", "REG0", None)] for a in ASSAY_PRIMARIES})
    panel = build_method_promoter_panel(
        conn, registry, "kemmeren", 25, {"*": (0.0, 0.05)}
    )
    assert panel.empty


def test_rossi_and_chec_default_filters_apply_and_give_one_sample_per_regulator() -> (
    None
):
    """
    Regression: ``DEFAULT_DATASET_FILTERS`` used to be keyed ``rossi`` / ``chec_m2025``
    while the panel looks filters up under the assay primaries ``rossi_500bp`` /
    ``chec_m2025_500bp``. The lookup found nothing, so both assays kept every sample --
    e.g. 14 ChEC-seq conditions for one regulator -- and a regulator appeared several
    times per cell. With the filter keyed correctly, only the default condition
    survives, which is one sample per regulator.
    """
    conn = duckdb.connect()
    for db in ASSAY_PRIMARIES:
        other = "Heat Shock" if db == "rossi_500bp" else "galactose"
        df = _assay_meta(db, [("keep", "REG0", None), ("drop", "REG0", other)])
        conn.register(f"_{db}", df)
        conn.execute(f'CREATE TABLE "{db}_meta" AS SELECT * FROM _{db}')
        assert _allowed_sample_ids(conn, default_filters(conn, _registry_df()), db) == [
            "keep"
        ]


# --- regulator intersection -------------------------------------------------------


def test_regulator_intersection_requires_all_three_datasets() -> None:
    conn = _meta_conn(
        {
            "kemmeren": ["REG0", "REG1", "REG2"],
            "rossi_500bp": ["REG0", "REG1"],
            "chec_m2025_500bp": ["REG0"],
        }
    )
    assert _regulator_intersection(conn, "kemmeren") == {"REG0"}


def test_panel_drops_regulators_outside_the_intersection() -> None:
    """A regulator present in only one binding assay must not appear in the panel."""
    registry = _registry_df()
    conn = duckdb.connect()
    conn.register("_registry", registry)
    conn.execute("CREATE TABLE dataset_registry AS SELECT * FROM _registry")
    _populate_method_promoter_topn(conn, registry, ["REG0", "REG1"])
    # REG1 is missing from chec_m2025_500bp's meta -- fails the 3-way intersection.
    _create_assay_metas(
        conn,
        {
            "rossi_500bp": [("s1", "REG0", None), ("s1", "REG1", None)],
            "chec_m2025_500bp": [("s1", "REG0", None)],
        },
    )
    conn.execute(
        "CREATE TABLE kemmeren_meta (sample_id VARCHAR, regulator_locus_tag VARCHAR)"
    )
    conn.execute("INSERT INTO kemmeren_meta VALUES ('s1', 'REG0'), ('s1', 'REG1')")

    panel = build_method_promoter_panel(
        conn, registry, "kemmeren", 25, {"*": (0.0, 0.05)}
    )
    assert set(panel["regulator_locus_tag"].unique()) == {"REG0"}


# --- fit: degenerate / singular panels --------------------------------------------

METHOD_TERM = "C(method, Treatment('peak_calling'))[T.promoter_enrichment]"


def test_empty_panel_does_not_raise() -> None:
    empty = pd.DataFrame(
        columns=[
            "regulator_locus_tag",
            "method",
            "promoter_set",
            "assay",
            "n",
            "n_responsive",
            "responsive_ratio",
        ]
    )
    coefs, summary = fit_method_promoter_model(empty)
    assert coefs.empty
    row = summary.iloc[0]
    assert not row["converged"]
    assert row["note"] == "empty panel"
    assert row["n_obs"] == 0


def test_too_few_regulators_is_caught_not_raised() -> None:
    coefs, summary = fit_method_promoter_model(_synthetic_panel(n_regulators=1))
    assert coefs.empty
    row = summary.iloc[0]
    assert not row["converged"]
    assert "fewer than" in row["note"]
    assert row["n_regulators"] == 1


def test_no_variation_in_method_is_caught() -> None:
    panel = _synthetic_panel(n_regulators=10)
    one_method = panel[panel["method"] == "promoter_enrichment"]
    coefs, summary = fit_method_promoter_model(one_method)
    assert coefs.empty
    assert not summary.iloc[0]["converged"]
    assert summary.iloc[0]["note"] == "no variation in method"


def test_recovers_a_known_method_effect_despite_regulator_heterogeneity() -> None:
    """
    Plant +10 points for peak calling over regulators with very different baselines.

    The reference level is peak calling, so promoter enrichment's coefficient is the
    negative of the planted effect, in percentage points.

    """
    panel = _synthetic_panel(
        n_regulators=60, seed=1, method_effect=0.10, regulator_baseline_spread=0.2
    )
    coefs, summary = fit_method_promoter_model(panel)
    assert summary.iloc[0]["converged"]
    estimate = coefs.set_index("term").loc[METHOD_TERM, "estimate"]
    assert estimate == pytest.approx(-10.0, abs=3.0)


def test_recovers_a_known_promoter_set_effect() -> None:
    """Plant +8 and +4 points for the 500 bp and Kang windows; the reference is
    intergenic, so those are the contrasts the model should report."""
    panel = _synthetic_panel(
        n_regulators=60, seed=2, promoter_set_effect={"500bp": 0.08, "kang": 0.04}
    )
    coefs, _ = fit_method_promoter_model(panel)
    est = coefs.set_index("term")["estimate"]
    assert est["C(promoter_set, Treatment('intergenic'))[T.500bp]"] == pytest.approx(
        8.0, abs=3.0
    )
    assert est["C(promoter_set, Treatment('intergenic'))[T.kang]"] == pytest.approx(
        4.0, abs=3.0
    )
    assert est["C(promoter_set, Treatment('intergenic'))[T.mindel]"] == pytest.approx(
        0.0, abs=3.0
    )


# --- peak-calling / promoter-enrichment regulator pairing ------------------


def _topn_shape_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "assay": "rossi_500bp",
        "promoter_set": "500bp",
        "regulator_locus_tag": "REG0",
        "method": "promoter_enrichment",
        "n": 20,
        "n_responsive": 10,
        "n_intersecting_targets": 20,
        "responsive_ratio": 0.5,
    }
    row.update(overrides)
    return row


GROUP = ["assay", "promoter_set"]


def test_pairing_drops_a_regulator_missing_from_peak_calling() -> None:
    """Promoter enrichment alone cannot be compared with peak calling: dropped, and
    nothing is invented for the missing method."""
    df = pd.DataFrame([_topn_shape_row()])
    assert pair_methods_on_regulators(df, GROUP).empty


def test_pairing_drops_a_regulator_missing_from_promoter_enrichment() -> None:
    df = pd.DataFrame(
        [
            _topn_shape_row(regulator_locus_tag="REG0"),
            _topn_shape_row(regulator_locus_tag="REG0", method="peak_calling"),
            _topn_shape_row(
                regulator_locus_tag="REG1", method="peak_calling", n_responsive=3
            ),
        ]
    )
    out = pair_methods_on_regulators(df, GROUP)
    assert set(out["regulator_locus_tag"]) == {"REG0"}
    assert set(out["method"]) == {"promoter_enrichment", "peak_calling"}


def test_pairing_keeps_a_regulator_present_in_both_untouched() -> None:
    df = pd.DataFrame(
        [
            _topn_shape_row(n_responsive=10),
            _topn_shape_row(method="peak_calling", n_responsive=4),
        ]
    )
    out = pair_methods_on_regulators(df, GROUP)
    assert len(out) == 2
    assert set(out["n_responsive"]) == {10, 4}  # no value changed, none invented


def test_pairing_keeps_every_row_of_a_paired_regulator() -> None:
    """Several samples per regulator are all kept; only the method pairing matters."""
    df = pd.DataFrame(
        [
            _topn_shape_row(n_responsive=10),
            _topn_shape_row(n_responsive=11),
            _topn_shape_row(method="peak_calling", n_responsive=4),
        ]
    )
    assert len(pair_methods_on_regulators(df, GROUP)) == 3


def test_pairing_does_not_leak_across_groups() -> None:
    """Missing a method in one (assay, promoter set) group says nothing about
    another."""
    df = pd.DataFrame(
        [
            _topn_shape_row(assay="rossi_500bp"),  # no peak_calling: dropped
            _topn_shape_row(assay="chec_m2025_500bp"),
            _topn_shape_row(assay="chec_m2025_500bp", method="peak_calling"),
        ]
    )
    out = pair_methods_on_regulators(df, GROUP)
    assert set(out["assay"]) == {"chec_m2025_500bp"}
    assert len(out) == 2


def test_pairing_supports_the_comparison_modules_column_names() -> None:
    """The Comparison tab's per-regulator frame names the method column differently."""
    df = pd.DataFrame(
        [
            {
                "perturbation_db": "kemmeren",
                "promoter_set_id": "500bp",
                "regulator_locus_tag": r,
                "binding_method_id": m,
                "med_pct": 33.0,
            }
            for r, m in (
                ("REG0", "promoter_enrichment"),
                ("REG0", "peak_calling"),
                ("REG1", "promoter_enrichment"),
            )
        ]
    )
    out = pair_methods_on_regulators(
        df,
        group_cols=["perturbation_db", "promoter_set_id"],
        method_col="binding_method_id",
    )
    assert set(out["regulator_locus_tag"]) == {"REG0"}


def test_pairing_empty_frame_returns_empty() -> None:
    empty = pd.DataFrame(
        columns=["assay", "promoter_set", "regulator_locus_tag", "method", "n"]
    )
    assert pair_methods_on_regulators(empty, GROUP).empty


def test_pairing_reports_a_missing_column() -> None:
    import pytest

    with pytest.raises(KeyError, match="regulator_locus_tag"):
        pair_methods_on_regulators(
            pd.DataFrame({"assay": ["x"], "promoter_set": ["y"], "method": ["m"]}),
            GROUP,
        )


def test_coefs_exclude_regulator_dummies() -> None:
    """The ~n_regulators fixed-effect coefficients must never reach the display
    table."""
    panel = _synthetic_panel(n_regulators=40, seed=3)
    coefs, summary = fit_method_promoter_model(panel)
    assert summary.iloc[0]["converged"]
    assert not coefs["term"].str.contains("regulator_locus_tag").any()
    # Intercept + method + 3 promoter_set contrasts + assay = 6 rows.
    assert len(coefs) == 6


# --- the full-overlap floor -------------------------------------------------------


def _staged_conn() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect()
    conn.execute(
        "CREATE TABLE method_promoter_model_topn (binding_source_sample VARCHAR,"
        " regulator_locus_tag VARCHAR, top_n INTEGER, n INTEGER, n_responsive INTEGER)"
    )
    conn.executemany(
        "INSERT INTO method_promoter_model_topn VALUES ('b', ?, ?, ?, 1)",
        [
            ("FULL", 25, 25),  # exactly N: kept
            ("OVER", 25, 31),  # a tie group kept whole pushed n above N: kept
            ("SHORT", 25, 19),  # a tie group around rank N was excluded: dropped
            ("FEWPEAKS", 25, 3),  # fewer than N scored targets: dropped
            ("SHORT", 50, 50),  # a different N for the same regulator is judged alone
        ],
    )
    return conn


def test_the_floor_drops_short_lists_and_keeps_full_or_longer_ones() -> None:
    from tfbpshiny.materialize.comparison.method_promoter_model import (
        apply_full_overlap_floor,
    )

    conn = _staged_conn()
    dropped, regulators = apply_full_overlap_floor(conn)
    assert (dropped, regulators) == (2, 2)
    kept = conn.execute(
        "SELECT regulator_locus_tag, top_n FROM method_promoter_model_topn"
        " ORDER BY 1, 2"
    ).fetchall()
    assert kept == [("FULL", 25), ("OVER", 25), ("SHORT", 50)]


def test_a_regulator_removed_by_the_floor_is_not_resurrected_by_pairing() -> None:
    """Floor, then pairing: a regulator whose peak-calling row was removed has no
    partner, so it is dropped from the promoter-enrichment side too -- never scored as
    zero."""
    df = pd.DataFrame(
        [
            _topn_shape_row(
                regulator_locus_tag="R", method="promoter_enrichment", n=25
            ),
            _topn_shape_row(regulator_locus_tag="R", method="peak_calling", n=19),
            _topn_shape_row(
                regulator_locus_tag="S", method="promoter_enrichment", n=25
            ),
            _topn_shape_row(regulator_locus_tag="S", method="peak_calling", n=25),
        ]
    )
    after_floor = df[df["n"] >= 25]
    out = pair_methods_on_regulators(after_floor, GROUP)
    assert set(out["regulator_locus_tag"]) == {"S"}
