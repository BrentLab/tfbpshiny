"""Unit tests for the registry-driven binding index used by the Comparison module."""

from __future__ import annotations

import pandas as pd
import pytest

from tfbpshiny.config import load_app_config
from tfbpshiny.modules.comparison.queries import (
    METHOD_LEVELS,
    PROMOTER_SET_LEVELS,
    build_binding_index,
)


def _row(
    db_name: str,
    *,
    data_type: str = "binding",
    display_name: str | None = None,
    base_label: str | None = None,
    primary_db_name: str | None = None,
    promoter_set_id: str | None = None,
    binding_method_id: str | None = None,
) -> dict:
    return {
        "db_name": db_name,
        "data_type": data_type,
        "display_name": display_name or db_name,
        "base_label": base_label or db_name,
        "primary_db_name": primary_db_name,
        "promoter_set_id": promoter_set_id,
        "binding_method_id": binding_method_id,
    }


@pytest.fixture
def registry_df() -> pd.DataFrame:
    """Registry fixture mirroring the materialized schema for two binding datasets."""
    rows: list[dict] = [
        # Rossi: promoter enrichment over 4 sets, MACS peaks over the same 4,
        # plus the authors' original ChExMix peaks (no fixed window).
        _row(
            "rossi",
            display_name="2021 ChIP-exo (Rossi)",
            base_label="2021 ChIP-exo",
            promoter_set_id="kang",
            binding_method_id="promoter_enrichment",
        ),
        _row(
            "rossi_peaks",
            display_name="2021 ChIP-exo Peaks",
            base_label="2021 ChIP-exo",
            primary_db_name="rossi",
            promoter_set_id="peaks",
            binding_method_id="peak_calling",
        ),
        # Perturbation rows must be ignored entirely.
        _row("kemmeren", data_type="perturbation", base_label="2014 TFKO"),
        # Harbison: promoter enrichment only, no peak variants.
        _row(
            "harbison",
            display_name="2004 ChIP-chip (Harbison)",
            base_label="2004 ChIP-chip",
            promoter_set_id="kang",
            binding_method_id="promoter_enrichment",
        ),
    ]
    for ps in ("mindel", "500bp", "intergenic"):
        rows.append(
            _row(
                f"rossi_{ps}",
                base_label="2021 ChIP-exo",
                primary_db_name="rossi",
                promoter_set_id=ps,
                binding_method_id="promoter_enrichment",
            )
        )
    for ps in PROMOTER_SET_LEVELS:
        rows.append(
            _row(
                f"rossi_peaks_{ps}",
                base_label="2021 ChIP-exo",
                primary_db_name="rossi",
                promoter_set_id=ps,
                binding_method_id="peak_calling",
            )
        )
    return pd.DataFrame(rows)


def test_every_promoter_set_resolves_both_methods(registry_df: pd.DataFrame) -> None:
    """Each promoter set has both a promoter-enrichment and a peak-calling db."""
    index = build_binding_index(registry_df)
    assert index.resolve("rossi", "kang", "promoter_enrichment") == "rossi"
    assert index.resolve("rossi", "mindel", "promoter_enrichment") == "rossi_mindel"
    for ps in PROMOTER_SET_LEVELS:
        assert index.resolve("rossi", ps, "peak_calling") == f"rossi_peaks_{ps}"


def test_original_peaks_excluded_from_promoter_set_columns(
    registry_df: pd.DataFrame,
) -> None:
    """The authors' peaks keep promoter_set_id='peaks' and never fill a column."""
    index = build_binding_index(registry_df)
    assert index.promoter_set_id["rossi_peaks"] == "peaks"
    assert "peaks" not in PROMOTER_SET_LEVELS
    resolved = {
        index.resolve("rossi", ps, m)
        for ps in PROMOTER_SET_LEVELS
        for m in METHOD_LEVELS
    }
    assert "rossi_peaks" not in resolved


def test_promoter_sets_with_both_methods_is_ordered(registry_df: pd.DataFrame) -> None:
    """Returned promoter sets follow PROMOTER_SET_LEVELS, not registry row order."""
    index = build_binding_index(registry_df)
    assert index.promoter_sets_with_both_methods("rossi") == list(PROMOTER_SET_LEVELS)


def test_dataset_without_peaks_is_not_method_comparable(
    registry_df: pd.DataFrame,
) -> None:
    """Harbison has no peak variants, so it cannot appear in the method tab."""
    index = build_binding_index(registry_df)
    assert index.promoter_sets_with_both_methods("harbison") == []
    assert index.supports_method_comparison("harbison") is False
    assert index.supports_method_comparison("rossi") is True


def test_perturbation_rows_are_ignored(registry_df: pd.DataFrame) -> None:
    """Only binding datasets enter the index."""
    index = build_binding_index(registry_df)
    assert "kemmeren" not in index.label
    assert "rossi" in index.label


def test_labels_come_from_the_registry(registry_df: pd.DataFrame) -> None:
    """display_name and base_label are read through, not reconstructed."""
    cfg = load_app_config()
    index = build_binding_index(
        registry_df,
        {k: v.display_name for k, v in cfg.promoter_sets.items()},
        {k: v.display_name for k, v in cfg.binding_methods.items()},
    )
    assert index.label["rossi"] == "2021 ChIP-exo (Rossi)"
    assert index.base_label["rossi_peaks_mindel"] == "2021 ChIP-exo"
    assert index.promoter_set["rossi_peaks_500bp"] == "500bp"
    assert index.method["rossi_peaks_kang"] == "Peak Calling"
    assert index.method["rossi"] == "Promoter Enrichment"


def test_primary_maps_to_self_for_primary_datasets(registry_df: pd.DataFrame) -> None:
    """A primary dataset is its own primary; variants point at it."""
    index = build_binding_index(registry_df)
    assert index.primary["rossi"] == "rossi"
    assert index.primary["rossi_peaks_intergenic"] == "rossi"


def test_unknown_combination_returns_none(registry_df: pd.DataFrame) -> None:
    """Unmaterialized cells resolve to None rather than raising."""
    index = build_binding_index(registry_df)
    assert index.resolve("rossi", "nonexistent", "peak_calling") is None
    assert index.resolve("harbison", "mindel", "promoter_enrichment") is None
    assert index.resolve("no_such_db", "kang", "promoter_enrichment") is None


def test_sidebar_promoter_set_keys_match_data_keys() -> None:
    """
    The promoter-set selector must emit the same ids the data is keyed by.

    Regression guard: the selector once used display labels ("Kang") while the
    aggregated frames were keyed by raw ids ("kang"), so every column except
    ``500bp`` -- the one value where label and id coincide -- rendered empty.

    """
    from tfbpshiny.modules.comparison.server.context import (
        PROMOTER_SET_ALIAS,
        PROMOTER_TOOLTIPS,
    )

    assert set(PROMOTER_SET_ALIAS) == set(PROMOTER_SET_LEVELS)
    assert set(PROMOTER_TOOLTIPS) == set(PROMOTER_SET_LEVELS)


def test_index_promoter_set_ids_are_known(registry_df: pd.DataFrame) -> None:
    """Every promoter_set_id is either a real column or the 'peaks' catch-all."""
    index = build_binding_index(registry_df)
    assert set(index.promoter_set_id.values()) <= set(PROMOTER_SET_LEVELS) | {"peaks"}


def test_empty_registry_yields_empty_index() -> None:
    """An empty registry produces an index with no entries and no crash."""
    empty = pd.DataFrame(
        columns=[
            "db_name",
            "data_type",
            "display_name",
            "base_label",
            "primary_db_name",
            "promoter_set_id",
            "binding_method_id",
        ]
    )
    index = build_binding_index(empty)
    assert index.label == {}
    assert index.supports_method_comparison("rossi") is False


# --- platform-fixed datasets -----------------------------------------------------


def test_array_dataset_is_not_a_promoter_definition() -> None:
    """
    Harbison's regions come from the microarray, not a promoter window.

    Tagging it `kang` put it in the Kang column of the promoter-definition grid and
    implied a comparison that cannot be made: there is no signal track to re-summarise
    over Mindel/500bp/intergenic, so no variants exist or could.

    """
    index = build_binding_index(
        pd.DataFrame(
            [
                _row(
                    "harbison",
                    promoter_set_id="array",
                    binding_method_id="promoter_enrichment",
                ),
                _row(
                    "rossi",
                    promoter_set_id="kang",
                    binding_method_id="promoter_enrichment",
                ),
            ]
        )
    )
    assert index.has_promoter_variants("rossi")
    assert not index.has_promoter_variants("harbison")
    # It must not answer to any real promoter set.
    for ps in ("kang", "mindel", "500bp", "intergenic"):
        assert index.resolve("harbison", ps, "promoter_enrichment") is None


def test_platform_fixed_dataset_survives_the_promoter_selector() -> None:
    """
    A promoter selector must not filter away a dataset the choice cannot apply to.

    Compare Datasets resolves every active dataset against the selected promoter set; a
    strict resolve drops Harbison from every column of the tab.

    """
    index = build_binding_index(
        pd.DataFrame(
            [
                _row(
                    "harbison",
                    promoter_set_id="array",
                    binding_method_id="promoter_enrichment",
                )
            ]
        )
    )
    for ps in ("kang", "mindel", "500bp", "intergenic"):
        got = index.resolve_or_self("harbison", ps, "promoter_enrichment")
        assert got == "harbison", ps


def test_platform_fixed_fallback_still_respects_the_method() -> None:
    """
    The fallback covers the promoter axis only.

    Harbison has no peak calls, so asking for peaks must still exclude it -- otherwise
    the Peaks view would silently show an enrichment dataset.

    """
    index = build_binding_index(
        pd.DataFrame(
            [
                _row(
                    "harbison",
                    promoter_set_id="array",
                    binding_method_id="promoter_enrichment",
                )
            ]
        )
    )
    assert index.resolve_or_self("harbison", "kang", "peak_calling") is None


def test_fallback_does_not_rescue_a_missing_variant() -> None:
    """
    A dataset that *does* sit on a promoter definition is filtered normally.

    Calling Cards has no peak variants; that is a real absence, not an inapplicable
    selector, and must not fall back to the enrichment dataset.

    """
    index = build_binding_index(
        pd.DataFrame(
            [
                _row(
                    "callingcards_kang",
                    promoter_set_id="kang",
                    binding_method_id="promoter_enrichment",
                )
            ]
        )
    )
    assert index.resolve_or_self("callingcards_kang", "kang", "peak_calling") is None
