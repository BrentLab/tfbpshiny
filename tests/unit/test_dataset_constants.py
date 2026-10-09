"""
``tfbpshiny.datasets`` is the one declaration of each per-dataset fact.

These tests check that the modules which re-export or build on a constant hold the same
object, and that the invariants the UI relies on hold.

"""

from __future__ import annotations

from tfbpshiny import datasets
from tfbpshiny.materialize.comparison import agreement
from tfbpshiny.materialize.comparison import method_promoter_model as mpm
from tfbpshiny.materialize.comparison import topn
from tfbpshiny.modules.comparison import queries as comparison_queries
from tfbpshiny.modules.figures import queries as figures_queries
from tfbpshiny.utils import vdb_init


def test_topn_module_uses_the_shared_constants() -> None:
    assert topn.TOP_N_ALL is datasets.TOP_N_ALL
    assert topn.PERTURBATION_DATASET_COLUMNS is datasets.PERTURBATION_DATASET_COLUMNS


def test_agreement_module_uses_the_shared_constants() -> None:
    assert agreement.GENE_UNIVERSE is datasets.GENE_UNIVERSE


def test_method_promoter_model_uses_the_shared_levels() -> None:
    assert mpm.PROMOTER_SET_LEVELS is datasets.PROMOTER_SET_LEVELS
    assert mpm.METHOD_LEVELS is datasets.METHOD_LEVELS


def test_figures_queries_use_the_shared_constants() -> None:
    assert figures_queries.TOP_N_ALL is datasets.TOP_N_ALL
    assert figures_queries.GENE_UNIVERSE is datasets.GENE_UNIVERSE
    assert figures_queries.DTO_PVALUE_THRESHOLD is datasets.DTO_PVALUE_THRESHOLD
    assert figures_queries.PROMOTER_SET_LEVELS is datasets.PROMOTER_SET_LEVELS
    assert figures_queries.METHOD_LEVELS is datasets.METHOD_LEVELS


def test_comparison_queries_use_the_shared_constants() -> None:
    assert comparison_queries.TOP_N_CHOICES is datasets.TOP_N_CHOICES
    assert comparison_queries.DEFAULT_TOP_N is datasets.DEFAULT_TOP_N
    assert comparison_queries.DTO_PVALUE_THRESHOLD is datasets.DTO_PVALUE_THRESHOLD
    assert comparison_queries.PROMOTER_SET_LEVELS is datasets.PROMOTER_SET_LEVELS
    assert comparison_queries.METHOD_LEVELS is datasets.METHOD_LEVELS


def test_vdb_init_uses_the_shared_constants() -> None:
    assert vdb_init.DEFAULT_RESPONSIVENESS_PRESET is datasets.DEFAULT_PRESET
    assert (
        vdb_init.PERTURBATION_DATASET_COLUMNS is datasets.PERTURBATION_DATASET_COLUMNS
    )


def test_presets_table_and_names_agree() -> None:
    """Every preset the UI lists has a threshold table, and vice versa."""
    assert set(vdb_init.DEFAULT_RESPONSIVENESS_PRESETS) == set(datasets.PRESET_NAMES)


def test_correlation_columns_differ_from_response_columns_only_for_hackett() -> None:
    a, b = (
        datasets.PERTURBATION_DATASET_COLUMNS,
        datasets.PERTURBATION_CORRELATION_COLUMNS,
    )
    assert set(a) == set(b)
    assert {k for k in a if a[k] != b[k]} == {"hackett"}
    assert b["hackett"] == ("log2_cleaned_ratio", "")


def test_ui_defaults_are_members_of_their_choice_sets() -> None:
    assert datasets.DEFAULT_TOP_N in datasets.TOP_N_CHOICES
    assert datasets.DEFAULT_PRESET in datasets.PRESET_NAMES
