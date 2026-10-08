"""The collection config is the single source of dataset identity and presentation."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from tfbpshiny.config import DEFAULT_CONFIG_PATH, _parse, load_app_config
from tfbpshiny.datasets import (
    HEADLINE_PERTURBATION,
    METHOD_COMPARISON_ASSAYS,
    METHOD_LEVELS,
    PROMOTER_ENRICHMENT_500BP,
    PROMOTER_SET_LEVELS,
)


@pytest.fixture(scope="module")
def raw() -> dict:
    return yaml.safe_load(Path(DEFAULT_CONFIG_PATH).read_text())


def test_the_packaged_config_loads_every_binding_and_perturbation_dataset() -> None:
    cfg = load_app_config()
    assert len(cfg.datasets) == 29
    assert "dto" not in cfg.datasets
    assert {d.data_type for d in cfg.datasets.values()} == {"binding", "perturbation"}


def test_repository_tags_are_merged_under_dataset_tags() -> None:
    d = load_app_config().datasets["rossi_mindel"]
    # repository level
    assert (d.base_label, d.assay, d.primary_db_name) == (
        "2021 ChIP-exo",
        "ChIPexo",
        "rossi_500bp",
    )
    # dataset level
    assert (d.promoter_set_id, d.binding_method_id) == ("mindel", "promoter_enrichment")


def test_a_dataset_naming_itself_as_primary_is_a_primary() -> None:
    d = load_app_config().datasets["rossi_500bp"]
    assert d.is_primary and d.primary_db_name is None


def test_labels_chosen_for_the_app() -> None:
    cfg = load_app_config()
    assert cfg.promoter_sets["500bp"].display_name == "500bp"
    assert cfg.datasets["hughes_knockout"].base_label == "2006 TFKO"


def test_promoter_set_descriptions_come_from_the_region_sets() -> None:
    desc = load_app_config().promoter_sets["kang"].description
    assert desc.startswith("700 bp upstream of each start codon")


def test_every_level_and_dataset_group_is_declared() -> None:
    cfg = load_app_config()
    assert set(PROMOTER_SET_LEVELS) <= set(cfg.promoter_sets)
    assert set(METHOD_LEVELS) <= set(cfg.binding_methods)
    for db in (*PROMOTER_ENRICHMENT_500BP, *METHOD_COMPARISON_ASSAYS):
        d = cfg.datasets[db]
        assert d.is_primary and d.promoter_set_id == "500bp"
    for db in HEADLINE_PERTURBATION:
        assert cfg.datasets[db].data_type == "perturbation"


def test_each_binding_assay_has_one_colour() -> None:
    colours = load_app_config().colors_by_base_label("binding")
    assert set(colours) == {
        "2004 ChIP-chip",
        "2021 ChIP-exo",
        "2025 ChEC-seq",
        "2026 Calling Cards",
    }


def _set(raw: dict, repo: str, cfg: str, **tags: str) -> dict:
    out = copy.deepcopy(raw)
    out["repositories"][repo]["dataset"][cfg].setdefault("tags", {}).update(tags)
    return out


@pytest.mark.parametrize(
    "tags, message",
    [
        ({"promoter_set": "nope"}, "unknown promoter_set"),
        ({"binding_method": "nope"}, "unknown binding_method"),
        ({"primary": "kemmeren"}, "base_label"),
        ({"primary": "rossi_mindel"}, "not a primary"),
        ({"base_label": "Something else"}, "base_label"),
        ({"active_default": "yes"}, "active_default"),
    ],
)
def test_inconsistent_tags_are_rejected(raw: dict, tags: dict, message: str) -> None:
    broken = _set(raw, "BrentLab/rossi_2021", "macs_kang", **tags)
    with pytest.raises(ValueError, match=message):
        _parse(broken)


def test_a_perturbation_dataset_cannot_carry_a_promoter_set(raw: dict) -> None:
    broken = _set(raw, "BrentLab/kemmeren_2014", "kemmeren_2014", promoter_set="kang")
    with pytest.raises(ValueError, match="no promoter set"):
        _parse(broken)


def test_a_missing_label_is_rejected(raw: dict) -> None:
    broken = copy.deepcopy(raw)
    del broken["repositories"]["BrentLab/kemmeren_2014"]["dataset"]["kemmeren_2014"][
        "tags"
    ]["display_name"]
    with pytest.raises(ValueError, match="display_name"):
        _parse(broken)


def test_an_undeclared_region_set_is_rejected(raw: dict) -> None:
    broken = copy.deepcopy(raw)
    broken["tfbpshiny"]["promoter_sets"]["kang"]["region_set"] = "nope"
    with pytest.raises(ValueError, match="region_set"):
        _parse(broken)
