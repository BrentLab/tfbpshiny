"""Unit tests for the top-N materialization variant planner."""

from __future__ import annotations

import pytest

from tfbpshiny.materialize.comparison.topn import TOP_N_ALL
from tfbpshiny.materialize.coordinator import _topn_variants
from tfbpshiny.utils.vdb_init import DEFAULT_RESPONSIVENESS_PRESETS

BOTH = ["Relaxed", "Stringent"]
PR_DATASETS = [
    "kemmeren",
    "hackett",
    "degron",
    "hu_reimand",
    "hughes_overexpression",
    "hughes_knockout",
]


def _threshold_pairs(variants) -> set[tuple[float, float]]:
    return {(e, p) for _, e, p in variants}


@pytest.mark.parametrize("pr_db", PR_DATASETS)
def test_both_presets_are_materialized(pr_db: str) -> None:
    """
    Every dataset stores the pair each preset needs.

    The app filters `topn_results` on exact (effect, pvalue), so a preset whose pair
    was never materialized silently renders nothing.

    """
    variants = _topn_variants("rossi", pr_db, [25], [0.0], [0.05], preset_names=BOTH)
    stored = _threshold_pairs(variants)
    for name in BOTH:
        preset = DEFAULT_RESPONSIVENESS_PRESETS[name]
        want = preset.get(pr_db, preset["*"])
        assert want in stored, f"{name} pair {want} missing for {pr_db}"


@pytest.mark.parametrize("pr_db", PR_DATASETS)
def test_presets_do_not_depend_on_threshold_flags(pr_db: str) -> None:
    """
    Preset pairs are added explicitly, not inherited from the CLI defaults.

    Relaxed's (0.0, 0.05) happens to equal the default --effect-threshold /
    --pvalue-threshold, so a planner that only cross-produced those flags would look
    correct until someone changed a default.

    """
    variants = _topn_variants("rossi", pr_db, [25], [2.5], [0.2], preset_names=BOTH)
    stored = _threshold_pairs(variants)
    for name in BOTH:
        preset = DEFAULT_RESPONSIVENESS_PRESETS[name]
        assert preset.get(pr_db, preset["*"]) in stored


def test_per_dataset_resolution_beats_the_cross_product() -> None:
    """
    Resolving per dataset costs far less than cross-producting the distinct pairs.

    Across the six datasets the two presets use four distinct (effect, pvalue) pairs; a
    global cross product would be eight combinations for every dataset.

    """
    for pr_db in PR_DATASETS:
        variants = _topn_variants(
            "rossi", pr_db, [25], [0.0], [0.05], preset_names=BOTH
        )
        assert len(_threshold_pairs(variants)) <= 2


def test_every_variant_carries_a_threshold_pair() -> None:
    """
    Responsiveness is decided by thresholds and nothing else.

    The deprecated per-row `responsive` column used to give a second, thresholdless
    way to score a row; this asserts no such variant survives.

    """
    variants = _topn_variants(
        "rossi", "degron", [10, 25], [0.0], [0.05], preset_names=BOTH
    )
    assert variants, "planner emitted nothing"
    for v in variants:
        assert len(v) == 3, f"unexpected variant shape: {v}"
        top_n, effect, pvalue = v
        assert isinstance(effect, float) and isinstance(pvalue, float)


def test_variant_order_is_independent_of_preset_order() -> None:
    """Listing presets in either order must plan the same work."""
    a = _topn_variants("rossi", "degron", [25], [0.0], [0.05], preset_names=BOTH)
    b = _topn_variants(
        "rossi", "degron", [25], [0.0], [0.05], preset_names=list(reversed(BOTH))
    )
    assert sorted(a) == sorted(b)


def test_only_peak_datasets_get_the_all_targets_sentinel() -> None:
    """
    TOP_N_ALL rows exist only where the authors' peak call is itself the threshold.

    Applying a rank cutoff to a peak dataset would discard part of the authors' answer,
    which is exactly what figure 3 needs to avoid.

    """
    peaks = _topn_variants("rossi_peaks", "degron", [25], [0.0], [0.05])
    enrich = _topn_variants("rossi", "degron", [25], [0.0], [0.05])
    assert any(top_n == TOP_N_ALL for top_n, *_ in peaks)
    assert not any(top_n == TOP_N_ALL for top_n, *_ in enrich)


def test_no_presets_leaves_only_the_cli_thresholds() -> None:
    """Passing no presets falls back to exactly what the flags specify."""
    variants = _topn_variants("rossi", "degron", [25], [1.5], [0.01])
    assert _threshold_pairs(variants) == {(1.5, 0.01)}
