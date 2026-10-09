"""Unit tests for the top-N materialization planner, ``coordinator._topn_plan``."""

from __future__ import annotations

import pytest

from tfbpshiny.materialize.comparison.topn import TOP_N_ALL
from tfbpshiny.materialize.coordinator import _topn_plan
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


def _pairs(binding: str, pr_db: str, effects, pvalues, presets=None) -> set:
    _, threshold_pairs = _topn_plan(binding, pr_db, [25], effects, pvalues, presets)
    return set(threshold_pairs)


@pytest.mark.parametrize("pr_db", PR_DATASETS)
def test_both_presets_are_materialized(pr_db: str) -> None:
    """
    Every dataset stores the pair each preset needs.

    The app filters `topn_results` on exact (effect, pvalue), so a preset whose pair
    was never materialized silently renders nothing.

    """
    stored = _pairs("rossi", pr_db, [0.0], [0.05], BOTH)
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
    stored = _pairs("rossi", pr_db, [2.5], [0.2], BOTH)
    for name in BOTH:
        preset = DEFAULT_RESPONSIVENESS_PRESETS[name]
        assert preset.get(pr_db, preset["*"]) in stored


def test_per_dataset_resolution_beats_the_cross_product() -> None:
    """
    Resolving per dataset stores only the pairs the presets name, never a cross product.

    Each preset resolves to one (effect, pvalue) pair per dataset, so at most two pairs
    are stored for any dataset.

    """
    for pr_db in PR_DATASETS:
        assert len(_pairs("rossi", pr_db, [0.0], [0.05], BOTH)) <= 2


def test_every_threshold_pair_is_a_pair_of_floats() -> None:
    """
    Responsiveness is decided by thresholds and nothing else: every planned variant
    is an (effect, p-value) pair of floats.

    """
    cutoffs, pairs = _topn_plan("rossi", "degron", [10, 25], [0.0], [0.05], BOTH)
    assert cutoffs == (10, 25)
    assert pairs, "planner emitted nothing"
    for effect, pvalue in pairs:
        assert isinstance(effect, float) and isinstance(pvalue, float)


def test_plan_is_independent_of_preset_order() -> None:
    """Listing presets in either order must plan the same work."""
    a = _topn_plan("rossi", "degron", [25], [0.0], [0.05], BOTH)
    b = _topn_plan("rossi", "degron", [25], [0.0], [0.05], list(reversed(BOTH)))
    assert a[0] == b[0] and set(a[1]) == set(b[1])


def test_only_peak_datasets_get_the_all_targets_sentinel() -> None:
    """
    TOP_N_ALL rows exist only where the authors' peak call is itself the threshold.

    Applying a rank cutoff to a peak dataset would discard part of the authors' answer,
    which is exactly what figure 3 needs to avoid.

    """
    peaks, _ = _topn_plan("rossi_peaks", "degron", [25], [0.0], [0.05])
    enrich, _ = _topn_plan("rossi", "degron", [25], [0.0], [0.05])
    assert TOP_N_ALL in peaks
    assert TOP_N_ALL not in enrich


def test_no_presets_leaves_only_the_cli_thresholds() -> None:
    """Passing no presets falls back to exactly what the flags specify."""
    assert _pairs("rossi", "degron", [1.5], [0.01]) == {(1.5, 0.01)}
