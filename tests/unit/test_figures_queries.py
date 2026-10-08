"""Unit tests for the Figures module's data access (``figures/queries.py``): scoring,
figure 6 selection and weighting, promoter-variant resolution."""

from __future__ import annotations

import matplotlib
import pandas as pd
import pytest

matplotlib.use("Agg")


#: Stand-in for `dataset_labels()`. Every promoter variant shares its assay's
#: base_label, which is what the colour maps are keyed on, so the Kang and 500 bp
#: entries of one assay deliberately map to the same string.
LABELS = {
    "harbison": "2004 ChIP-chip",
    "callingcards_kang": "2026 Calling Cards",
    "callingcards_500bp": "2026 Calling Cards",
    "rossi": "2021 ChIP-exo",
    "rossi_500bp": "2021 ChIP-exo",
    "chec_m2025": "2025 ChEC-seq",
    "chec_m2025_500bp": "2025 ChEC-seq",
    "kemmeren": "2014 TFKO",
    "hackett": "2020 Overexpression",
    "degron": "2025 Degron",
}


# --- scoring definition pinning -------------------------------------------------


def test_scoring_clause_resolves_preset_per_dataset() -> None:
    """
    Each dataset contributes its own threshold pair, not a global one.

    Kemmeren and Degron have different Stringent cutoffs, so a single global pair would
    silently misread one of them.

    """
    from tfbpshiny.modules.figures.queries import scoring_clause

    _, kem = scoring_clause("kemmeren", "Stringent")
    _, deg = scoring_clause("degron", "Stringent")
    assert kem == [0.77, 0.05]
    assert deg == [0.38, 0.1]


def test_stringent_matches_the_presets_table() -> None:
    """
    Stringent is each dataset's published criteria, so it must track the preset table.

    The figures pin thresholds by value, so a preset edited in `vdb_init.py` without a
    rebuild would read rows that do not exist and render empty.

    """
    from tfbpshiny.modules.figures.queries import scoring_clause
    from tfbpshiny.utils.vdb_init import DEFAULT_RESPONSIVENESS_PRESETS

    for name in ("Relaxed", "Stringent"):
        preset = DEFAULT_RESPONSIVENESS_PRESETS[name]
        for pr_db in ("kemmeren", "degron", "hackett", "hu_reimand"):
            _, params = scoring_clause(pr_db, name)
            assert params == list(preset.get(pr_db, preset["*"]))


def test_scoring_clause_always_pins_both_thresholds() -> None:
    """
    Every call pins the (effect, pvalue) pair.

    Both presets are materialized, so `topn_results` holds more than one row per
    (binding sample, perturbation sample, regulator, top_n); a query that does not
    pin the pair medians across two definitions of responsive and silently reports a
    different number.

    """
    from tfbpshiny.modules.figures.queries import scoring_clause

    for preset in ("Relaxed", "Stringent"):
        clause, params = scoring_clause("degron", preset)
        assert "effect_threshold = ?" in clause
        assert "pvalue_threshold = ?" in clause
        assert len(params) == 2


# --- figure 6 dataset selection --------------------------------------------------


def _agreement_db():
    """In-memory registry + agreement rows covering enrichment and peak variants."""
    import duckdb

    conn = duckdb.connect()
    conn.execute(
        "CREATE TABLE promoter_sets (promoter_set_id VARCHAR, display_name VARCHAR)"
    )
    conn.execute(
        "INSERT INTO promoter_sets VALUES ('kang','Kang'),('500bp','500 bp'),"
        "('peaks','Peaks')"
    )
    conn.execute(
        "CREATE TABLE dataset_registry (db_name VARCHAR, hf_repo VARCHAR,"
        " hf_config VARCHAR, data_type VARCHAR, base_label VARCHAR,"
        " primary_db_name VARCHAR, promoter_set_id VARCHAR,"
        " binding_method_id VARCHAR)"
    )
    conn.execute(
        """INSERT INTO dataset_registry VALUES
        ('rossi','R','kang','binding','ChIP-exo',NULL,'kang','promoter_enrichment'),
        ('rossi_500bp','R','b5','binding','ChIP-exo','rossi','500bp',
         'promoter_enrichment'),
        ('rossi_peaks_500bp','R','p5','binding','ChIP-exo','rossi','500bp',
         'peak_calling'),
        ('rossi_peaks','R','ap','binding','ChIP-exo','rossi','peaks','peak_calling')
        """
    )
    conn.execute(
        "CREATE TABLE topn_agreement (source_sample_a VARCHAR,"
        " source_sample_b VARCHAR, comparison_type VARCHAR,"
        " regulator_locus_tag VARCHAR, top_n INTEGER, n_a INTEGER, n_b INTEGER,"
        " n_intersect INTEGER, db_a VARCHAR, sample_a VARCHAR, db_b VARCHAR,"
        " sample_b VARCHAR)"
    )
    return conn


def test_authors_peaks_are_not_selectable() -> None:
    """
    The authors' own peak calls are excluded from figure 6.

    Their regions are not a fixed upstream window, so a pair involving one differs in
    both the caller and the region and cannot be attributed to either.

    """
    from tfbpshiny.modules.figures.queries import agreement_dataset_choices

    choices = agreement_dataset_choices(_agreement_db(), "binding")
    assert "rossi_peaks" not in choices
    assert "rossi_peaks_500bp" in choices


def test_variant_labels_are_distinguishable() -> None:
    """
    Every selectable dataset gets a distinct label.

    `base_label` alone is shared by all variants of one assay, so a promoter-set
    comparison would legend as "ChIP-exo vs ChIP-exo". The 500bp promoter set is the
    one exception left unstated (every default selection uses it, so naming it on
    every series would just be noise) -- Kang still must appear, or the two would
    collide.

    """
    from tfbpshiny.modules.figures.queries import agreement_dataset_choices

    labels = list(agreement_dataset_choices(_agreement_db(), "binding").values())
    assert len(labels) == len(set(labels)), labels
    assert "ChIP-exo" in labels
    assert "ChIP-exo peaks" in labels
    assert "ChIP-exo Kang" in labels


def test_expectation_uses_observed_set_sizes() -> None:
    """
    Enrichment divides by n_a * n_b, not top_n^2.

    A peak set is whatever the caller returned, often far below top_n. Dividing a
    30-target set by 500^2 understates its enrichment ~16-fold, worst at high N where
    the curve is read.

    """
    import math

    from tfbpshiny.modules.figures.queries import GENE_UNIVERSE, fetch_agreement

    conn = _agreement_db()
    # 30 peak targets vs 500 enrichment targets, overlapping in 20.
    conn.execute(
        "INSERT INTO topn_agreement VALUES"
        " ('R;b5;1','R;p5;1','binding','REG1',500,500,30,20,"
        " 'rossi_500bp','1','rossi_peaks_500bp','1')"
    )
    df = fetch_agreement(conn, "binding", ["rossi_500bp", "rossi_peaks_500bp"])
    assert len(df) == 1
    got = float(df["log2_enrichment"].iloc[0])
    assert math.isclose(got, math.log2(20 * GENE_UNIVERSE / (500 * 30)), rel_tol=1e-9)
    # The old top_n^2 denominator would have been far lower.
    assert got > math.log2(20 * GENE_UNIVERSE / (500 * 500))


def test_single_dataset_yields_no_pairs() -> None:
    """One dataset has nothing to compare against, so the query is skipped."""
    from tfbpshiny.modules.figures.queries import fetch_agreement

    assert fetch_agreement(_agreement_db(), "binding", ["rossi"]).empty
    assert fetch_agreement(_agreement_db(), "binding", []).empty


def test_default_selection_is_500bp_promoter_enrichment() -> None:
    """
    The headline view compares assays on one promoter definition.

    Using each assay's primary instead would have silently compared them on Kang.

    """
    from tfbpshiny.modules.figures.queries import AGREEMENT_DEFAULT_BINDING

    assert all(d.endswith("_500bp") for d in AGREEMENT_DEFAULT_BINDING)
    assert not any("peaks" in d for d in AGREEMENT_DEFAULT_BINDING)


# --- figure 6 exponential weighting ----------------------------------------------


def _curve(values: dict[int, float]) -> pd.DataFrame:
    """One (pair, regulator) curve as `fetch_agreement` would return it."""
    import pandas as pd

    return pd.DataFrame(
        {
            "pair": ["p"] * len(values),
            "regulator_locus_tag": ["R"] * len(values),
            "top_n": list(values),
            "log2_enrichment": list(values.values()),
        }
    )


def test_weighting_is_a_weighted_mean_not_a_sum() -> None:
    """
    A flat curve must collapse to its own value at every half-life.

    Weights are normalised within each group, so the result is on the same scale as the
    enrichment itself and stays comparable across groups with different coverage.

    """
    from tfbpshiny.modules.figures.queries import weighted_agreement

    flat = _curve({n: 2.5 for n in range(10, 210, 10)})
    for hl in (10, 50, 200):
        got = weighted_agreement(flat, half_life=hl)["weighted_enrichment"].iloc[0]
        assert got == pytest.approx(2.5), hl


def test_smaller_half_life_weights_the_top_more_heavily() -> None:
    """
    The parameter must actually change the emphasis, in the stated direction.

    A curve that falls with N should score higher the more the top dominates.

    """
    from tfbpshiny.modules.figures.queries import weighted_agreement

    falling = _curve({n: 10.0 - n / 20.0 for n in range(10, 210, 10)})
    scores = [
        weighted_agreement(falling, half_life=hl)["weighted_enrichment"].iloc[0]
        for hl in (10, 30, 100, 200)
    ]
    assert scores == sorted(scores, reverse=True), scores


def test_half_life_is_the_distance_over_which_weight_halves() -> None:
    """
    The parameter means what the UI label says.

    Two cutoffs one half-life apart must contribute in a 2:1 ratio, which is what makes
    the slider interpretable rather than an arbitrary knob.

    """
    import numpy as np

    hl = 40
    w = np.exp2(-np.array([10, 50]) / hl)
    assert w[0] / w[1] == pytest.approx(2.0)


def test_weights_normalise_over_the_cutoffs_actually_present() -> None:
    """
    A curve missing cutoffs must not be penalised against a complete one.

    `topn_agreement` uses a LEFT JOIN, so a regulator can be absent at some cutoffs;
    normalising over the whole grid instead of the present rows would bias it low.

    """
    from tfbpshiny.modules.figures.queries import weighted_agreement

    full = weighted_agreement(_curve({n: 3.0 for n in range(10, 210, 10)}))
    sparse = weighted_agreement(_curve({10: 3.0, 90: 3.0, 200: 3.0}))
    assert full["weighted_enrichment"].iloc[0] == pytest.approx(3.0)
    assert sparse["weighted_enrichment"].iloc[0] == pytest.approx(3.0)


def test_half_life_must_be_positive() -> None:
    """Zero or negative would divide by zero or invert the decay silently."""
    from tfbpshiny.modules.figures.queries import weighted_agreement

    for bad in (0, -10):
        with pytest.raises(ValueError):
            weighted_agreement(_curve({10: 1.0}), half_life=bad)


def test_slider_bounds_cover_the_materialized_grid() -> None:
    """
    The slider must not offer a half-life the cutoff grid cannot express.

    `AGREEMENT_TOP_N` runs 10-200; a slider wider than that would have a dead zone.

    """
    from tfbpshiny.materialize.comparison.agreement import AGREEMENT_TOP_N
    from tfbpshiny.modules.figures.queries import (
        AGREEMENT_HALF_LIFE_DEFAULT,
        AGREEMENT_HALF_LIFE_MAX,
        AGREEMENT_HALF_LIFE_MIN,
        AGREEMENT_HALF_LIFE_STEP,
    )

    assert AGREEMENT_HALF_LIFE_MIN == min(AGREEMENT_TOP_N)
    assert AGREEMENT_HALF_LIFE_MAX == max(AGREEMENT_TOP_N)
    assert AGREEMENT_HALF_LIFE_STEP == 10
    span = AGREEMENT_HALF_LIFE_MAX - AGREEMENT_HALF_LIFE_MIN
    assert span % AGREEMENT_HALF_LIFE_STEP == 0, "max is not reachable from min"
    assert AGREEMENT_HALF_LIFE_MIN <= AGREEMENT_HALF_LIFE_DEFAULT
    assert AGREEMENT_HALF_LIFE_DEFAULT <= AGREEMENT_HALF_LIFE_MAX


def test_figure_six_defaults_to_500bp_promoter_enrichment() -> None:
    """
    Figure 6 compares assays on one promoter definition unless told otherwise.

    The default must be 500 bp *promoter enrichment* for every entry: mixing promoter
    sets or slipping a peak-calling dataset in would silently make the headline view a
    confounded comparison rather than an assay comparison. Checked against the registry
    DDL rather than a hardcoded list, so a renamed db_name fails here instead of being
    dropped by the membership filter in `_agreement_selection`.

    """
    import duckdb

    from tests.unit._collection import CollectionVDB
    from tfbpshiny.materialize.coordinating.sql import (
        binding_methods_sql,
        dataset_registry_sql,
        promoter_set_descriptions,
        promoter_sets_sql,
        registry_rows,
    )
    from tfbpshiny.modules.figures.queries import AGREEMENT_DEFAULT_BINDING

    conn = duckdb.connect()
    vdb = CollectionVDB()
    for stmt in (
        promoter_sets_sql(promoter_set_descriptions(vdb)),
        binding_methods_sql(),
        dataset_registry_sql(registry_rows(vdb)),
    ):
        conn.execute(stmt)
    reg = {
        r[0]: (r[1], r[2])
        for r in conn.execute(
            "SELECT db_name, promoter_set_id, binding_method_id FROM dataset_registry"
        ).fetchall()
    }

    assert AGREEMENT_DEFAULT_BINDING, "figure 6 must have a default selection"
    for db in AGREEMENT_DEFAULT_BINDING:
        assert db in reg, f"{db} is not a registered db_name"
        promoter_set, method = reg[db]
        assert promoter_set == "500bp", f"{db} uses promoter set {promoter_set!r}"
        assert method == "promoter_enrichment", f"{db} uses method {method!r}"


def test_figure_six_default_covers_every_assay_that_can_have_500bp() -> None:
    """
    No assay with a 500 bp variant may be missing from the default.

    Harbison is the one exclusion and it is structural, not an oversight: its regions
    are microarray probes, so it has no 500 bp variant to include.

    """
    import duckdb

    from tests.unit._collection import CollectionVDB
    from tfbpshiny.materialize.coordinating.sql import (
        binding_methods_sql,
        dataset_registry_sql,
        promoter_set_descriptions,
        promoter_sets_sql,
        registry_rows,
    )
    from tfbpshiny.modules.figures.queries import AGREEMENT_DEFAULT_BINDING

    conn = duckdb.connect()
    vdb = CollectionVDB()
    for stmt in (
        promoter_sets_sql(promoter_set_descriptions(vdb)),
        binding_methods_sql(),
        dataset_registry_sql(registry_rows(vdb)),
    ):
        conn.execute(stmt)
    available = {
        r[0]
        for r in conn.execute(
            "SELECT db_name FROM dataset_registry"
            " WHERE promoter_set_id = '500bp'"
            "   AND binding_method_id = 'promoter_enrichment'"
        ).fetchall()
    }
    assert available, "no 500 bp promoter-enrichment datasets in the registry"
    assert set(AGREEMENT_DEFAULT_BINDING) == available, (
        "figure 6's default is out of sync with the registry: "
        f"missing {sorted(available - set(AGREEMENT_DEFAULT_BINDING))}, "
        f"unexpected {sorted(set(AGREEMENT_DEFAULT_BINDING) - available)}"
    )


# --- figures 7/8/9: promoter/method comparisons as box plots --------------------


def test_resolve_promoter_variant_finds_the_right_db_name() -> None:
    from tfbpshiny.modules.figures.queries import resolve_promoter_variant

    conn = _agreement_db()
    assert (
        resolve_promoter_variant(conn, "rossi", "500bp", "promoter_enrichment")
        == "rossi_500bp"
    )
    assert (
        resolve_promoter_variant(conn, "rossi", "500bp", "peak_calling")
        == "rossi_peaks_500bp"
    )


def test_resolve_promoter_variant_returns_none_for_no_match() -> None:
    from tfbpshiny.modules.figures.queries import resolve_promoter_variant

    conn = _agreement_db()
    # Harbison-shaped case: no such (primary, promoter_set, method) combination.
    assert (
        resolve_promoter_variant(conn, "rossi", "array", "promoter_enrichment") is None
    )
    # Calling-Cards-shaped case: a promoter set that exists, but not with this method.
    assert resolve_promoter_variant(conn, "rossi", "kang", "peak_calling") is None


def _dto_pvalue_db():
    """In-memory `dto` + `sample_regulator` covering two regulators, two samples."""
    import duckdb

    conn = duckdb.connect()
    conn.execute(
        "CREATE TABLE sample_regulator (db_name VARCHAR, sample_id VARCHAR,"
        " regulator_locus_tag VARCHAR)"
    )
    conn.execute(
        "INSERT INTO sample_regulator VALUES"
        " ('b1', 's1', 'REG1'), ('b1', 's2', 'REG2'),"
        " ('p1', 's1', 'REG1'), ('p1', 's2', 'REG2')"
    )
    conn.execute(
        "CREATE TABLE dto (binding_db VARCHAR, perturbation_db VARCHAR,"
        " regulator_locus_tag VARCHAR, pr_ranking_column VARCHAR,"
        " dto_empirical_pvalue DOUBLE)"
    )
    conn.execute(
        """INSERT INTO dto VALUES
        ('b1', 'p1', 'REG1', 'log2fc', 0.5),
        ('b1', 'p1', 'REG1', 'log2fc', 0.02),
        ('b1', 'p1', 'REG2', 'log2fc', 0.3)
        """
    )
    return conn


def test_fetch_dto_significance_for_universe_restricts_to_the_given_set() -> None:
    """REG2 is dropped from both numerator and denominator when it's not in the caller-
    supplied universe, even though it's DTO-tested and metadata-shared."""
    from tfbpshiny.modules.figures.queries import fetch_dto_significance_for_universe

    conn = _dto_pvalue_db()
    # REG1's best p is 0.02 (min of 0.5, 0.02) -- covered but not significant at the
    # default 0.01 threshold.
    stats = fetch_dto_significance_for_universe(conn, "b1", "p1", {"REG1"})
    assert stats == {"n_significant": 0, "n_covered": 1}


def test_fetch_dto_significance_for_universe_counts_both_regulators() -> None:
    from tfbpshiny.modules.figures.queries import fetch_dto_significance_for_universe

    conn = _dto_pvalue_db()
    stats = fetch_dto_significance_for_universe(conn, "b1", "p1", {"REG1", "REG2"})
    # REG1 best p=0.02 (significant at default 0.01? no -- 0.02 > 0.01, not
    # significant), REG2 best p=0.3 (not significant).
    assert stats["n_covered"] == 2
    assert stats["n_significant"] == 0


def test_fetch_dto_significance_for_universe_empty_universe() -> None:
    from tfbpshiny.modules.figures.queries import fetch_dto_significance_for_universe

    conn = _dto_pvalue_db()
    assert fetch_dto_significance_for_universe(conn, "b1", "p1", set()) == {
        "n_significant": 0,
        "n_covered": 0,
    }
