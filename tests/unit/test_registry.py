"""The dataset registry comes from the collection config's tags, read through
labretriever, and is checked before it is written."""

from __future__ import annotations

import duckdb
import pytest

from tests.unit._collection import CollectionVDB
from tfbpshiny.datasets import (
    HEADLINE_PERTURBATION,
    METHOD_COMPARISON_ASSAYS,
    PROMOTER_ENRICHMENT_500BP,
    PROMOTER_SETS,
)
from tfbpshiny.materialize.coordinating.sql import (
    binding_methods_sql,
    dataset_registry_sql,
    promoter_set_descriptions,
    promoter_sets_sql,
    registry_rows,
)


@pytest.fixture(scope="module")
def rows() -> dict:
    return {r.db_name: r for r in registry_rows(CollectionVDB())}


def test_every_binding_and_perturbation_dataset_is_registered(rows: dict) -> None:
    assert len(rows) == 29
    assert "dto" not in rows
    assert {r.data_type for r in rows.values()} == {"binding", "perturbation"}


def test_repository_tags_reach_every_dataset(rows: dict) -> None:
    r = rows["rossi_mindel"]
    assert (r.base_label, r.assay, r.primary_db_name) == (
        "2021 ChIP-exo",
        "ChIPexo",
        "rossi_500bp",
    )
    assert (r.promoter_set_id, r.binding_method_id) == ("mindel", "promoter_enrichment")
    assert (r.hf_repo, r.hf_config) == (
        "BrentLab/rossi_2021",
        "rossi_2021_af_combined_mindel",
    )


def test_a_dataset_naming_itself_as_primary_is_a_primary(rows: dict) -> None:
    assert rows["rossi_500bp"].is_primary
    assert rows["rossi_500bp"].primary_db_name is None


def test_labels_chosen_for_the_app(rows: dict) -> None:
    assert rows["hughes_knockout"].base_label == "2006 TFKO"
    assert PROMOTER_SETS["500bp"].display_name == "500bp"


def test_dataset_groups_name_registered_primaries(rows: dict) -> None:
    for db in (*PROMOTER_ENRICHMENT_500BP, *METHOD_COMPARISON_ASSAYS):
        assert rows[db].is_primary and rows[db].promoter_set_id == "500bp"
    for db in HEADLINE_PERTURBATION:
        assert rows[db].data_type == "perturbation"


def test_each_binding_experiment_has_one_colour(rows: dict) -> None:
    colours = {
        r.base_label: r.color
        for r in rows.values()
        if r.data_type == "binding" and r.is_primary and r.color
    }
    assert set(colours) == {
        "2004 ChIP-chip",
        "2021 ChIP-exo",
        "2025 ChEC-seq",
        "2026 Calling Cards",
    }


@pytest.mark.parametrize(
    "tags, message",
    [
        ({"promoter_set": "nope"}, "unknown promoter_set"),
        ({"binding_method": "nope"}, "unknown binding_method"),
        ({"primary": "kemmeren"}, "base_label"),
        ({"primary": "rossi_mindel"}, "not a primary"),
        ({"base_label": "Something else"}, "base_label"),
        ({"active_default": "yes"}, "active_default"),
        ({"display_name": ""}, "display_name"),
    ],
)
def test_inconsistent_tags_are_rejected(tags: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        registry_rows(CollectionVDB({"rossi_peaks_kang": tags}))


def test_perturbation_data_cannot_carry_a_promoter_set() -> None:
    with pytest.raises(ValueError, match="no promoter set"):
        registry_rows(CollectionVDB({"kemmeren": {"promoter_set": "kang"}}))


def test_promoter_set_descriptions_come_from_the_region_sets() -> None:
    desc = promoter_set_descriptions(CollectionVDB())
    assert desc["kang"].startswith("700 bp upstream of each start codon")
    assert set(desc) == set(PROMOTER_SETS)


def test_the_generated_tables_load_and_link() -> None:
    vdb = CollectionVDB()
    conn = duckdb.connect()
    conn.execute(promoter_sets_sql(promoter_set_descriptions(vdb)))
    conn.execute(binding_methods_sql())
    conn.execute(dataset_registry_sql(registry_rows(vdb)))
    assert conn.execute("SELECT count(*) FROM dataset_registry").fetchone()[0] == 29
    assert conn.execute(
        "SELECT count(*) FROM dataset_registry WHERE color IS NOT NULL"
    ).fetchone()[0] == len(PROMOTER_ENRICHMENT_500BP) + 1 + len(HEADLINE_PERTURBATION)


def test_dataset_descriptions_reach_the_registry() -> None:
    """The selection page's row tooltips read ``dataset_registry.description``."""
    vdb = CollectionVDB()
    conn = duckdb.connect()
    conn.execute(promoter_sets_sql(promoter_set_descriptions(vdb)))
    conn.execute(binding_methods_sql())
    conn.execute(dataset_registry_sql(registry_rows(vdb)))
    desc = conn.execute(
        "SELECT description FROM dataset_registry WHERE db_name = 'rossi_500bp'"
    ).fetchone()[0]
    assert desc == vdb.get_dataset_description("rossi_500bp")
    assert desc.startswith("ChIP-exo")


def test_filter_rules_are_keyed_by_primary_datasets(rows: dict) -> None:
    """A rule keyed by a name that is not a primary applies to nothing."""
    from tfbpshiny.utils.vdb_init import (
        DEFAULT_DATASET_FILTERS,
        HIDDEN_FILTER_FIELDS,
    )

    primaries = {db for db, r in rows.items() if r.is_primary}
    assert set(DEFAULT_DATASET_FILTERS) <= primaries
    assert set(HIDDEN_FILTER_FIELDS) - {"*"} <= primaries


def test_hidden_filter_fields_reach_every_variant() -> None:
    from tfbpshiny.utils.vdb_init import hidden_filter_fields

    for db, primary in (
        ("chec_m2025_500bp", None),
        ("chec_m2025_peaks_kang", "chec_m2025_500bp"),
    ):
        hidden = hidden_filter_fields(db, primary)
        assert {"condition", "mahendrawada_symbol", "regulator_symbol"} <= hidden
    assert "mahendrawada_symbol" not in hidden_filter_fields("rossi_500bp")
    assert {"antibody", "growth_media"} <= hidden_filter_fields(
        "rossi_mindel", "rossi_500bp"
    )
