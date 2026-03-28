"""Unit tests for the dataset export helpers."""

from __future__ import annotations

import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from tfbpshiny.modules.select_datasets.export import (
    ExportDataset,
    _safe_dir_name,
    build_export_tarball,
    build_readme,
    get_dataset_description,
)

# --- _safe_dir_name ---


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026 Calling Cards", "2026_Calling_Cards"),
        ("simple", "simple"),
        ("has-hyphen", "has-hyphen"),
        ("has.dot", "has.dot"),
        ("../evil", "evil"),
        ("../../etc/passwd", "etc_passwd"),
        ("/absolute/path", "absolute_path"),
        ("name\x00null", "name_null"),
        ("a/b", "a_b"),
        ("   spaces   ", "spaces"),
        ("...", "dataset"),
        ("___", "dataset"),
        ("", "dataset"),
    ],
)
def test_safe_dir_name(raw: str, expected: str) -> None:
    assert _safe_dir_name(raw) == expected


# --- build_readme ---


def test_build_readme_includes_display_name():
    result = build_readme("2026 Calling Cards", "A binding dataset.")
    assert "# 2026 Calling Cards" in result


def test_build_readme_includes_description():
    result = build_readme("Test", "Some description text.")
    assert "Some description text." in result


def test_build_readme_includes_file_explanations():
    result = build_readme("Test", "desc")
    assert "metadata.csv" in result
    assert "annotated_features.csv" in result
    assert "Sample-level metadata" in result
    assert "Full genomic data" in result


# --- get_dataset_description ---


def _make_mock_vdb(
    db_name: str = "harbison",
    repo_id: str = "BrentLab/repo",
    config_name: str = "harbison",
    description: str | None = "A description",
) -> MagicMock:
    # Mocks private VirtualDB attrs; update when public API lands (issue #213).
    vdb = MagicMock()
    vdb._db_name_map = {db_name: (repo_id, config_name)}
    config = SimpleNamespace(description=description)
    card = MagicMock()
    card.get_config.return_value = config
    vdb._datacards = {repo_id: card}
    return vdb


def test_get_dataset_description_happy_path():
    vdb = _make_mock_vdb(description="Harbison ChIP-chip data.")
    assert get_dataset_description(vdb, "harbison") == "Harbison ChIP-chip data."


def test_get_dataset_description_no_card():
    vdb = _make_mock_vdb()
    vdb._datacards = {}
    assert get_dataset_description(vdb, "harbison") is None


def test_get_dataset_description_no_config():
    vdb = _make_mock_vdb()
    vdb._datacards["BrentLab/repo"].get_config.return_value = None
    assert get_dataset_description(vdb, "harbison") is None


def test_get_dataset_description_unknown_db_name():
    vdb = _make_mock_vdb()
    assert get_dataset_description(vdb, "nonexistent") is None


def test_get_dataset_description_empty_description():
    vdb = _make_mock_vdb(description="")
    assert get_dataset_description(vdb, "harbison") is None


# --- build_export_tarball ---


def _sample_metadata() -> pd.DataFrame:
    return pd.DataFrame({"sample_id": ["s1", "s2"], "strain": ["BY4741", "BY4741"]})


def _sample_data() -> pd.DataFrame:
    return pd.DataFrame(
        {"sample_id": ["s1", "s1"], "gene": ["YAL001C", "YAL002W"], "value": [1.0, 2.0]}
    )


def test_single_dataset_with_description(tmp_path: Path):
    ds = ExportDataset(
        display_name="2026 Calling Cards",
        metadata_df=_sample_metadata(),
        data_df=_sample_data(),
        description="A binding dataset.",
    )
    out = build_export_tarball([ds], tmp_path / "export.tar.gz")
    assert out.exists()

    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
        assert "2026_Calling_Cards/metadata.csv" in names
        assert "2026_Calling_Cards/annotated_features.csv" in names
        assert "2026_Calling_Cards/README.md" in names


def test_single_dataset_without_description(tmp_path: Path):
    ds = ExportDataset(
        display_name="Test Dataset",
        metadata_df=_sample_metadata(),
        data_df=_sample_data(),
        description=None,
    )
    out = build_export_tarball([ds], tmp_path / "export.tar.gz")

    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
        assert "Test_Dataset/metadata.csv" in names
        assert "Test_Dataset/annotated_features.csv" in names
        assert "Test_Dataset/README.md" not in names


def test_multiple_datasets(tmp_path: Path):
    ds1 = ExportDataset(
        display_name="Dataset A",
        metadata_df=_sample_metadata(),
        data_df=_sample_data(),
        description="First.",
    )
    ds2 = ExportDataset(
        display_name="Dataset B",
        metadata_df=_sample_metadata(),
        data_df=_sample_data(),
        description=None,
    )
    out = build_export_tarball([ds1, ds2], tmp_path / "export.tar.gz")

    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
        assert "Dataset_A/metadata.csv" in names
        assert "Dataset_B/metadata.csv" in names
        assert "Dataset_A/README.md" in names
        assert "Dataset_B/README.md" not in names


def test_csv_content_matches_input(tmp_path: Path):
    meta = _sample_metadata()
    data = _sample_data()
    ds = ExportDataset(
        display_name="Check",
        metadata_df=meta,
        data_df=data,
        description=None,
    )
    out = build_export_tarball([ds], tmp_path / "export.tar.gz")

    with tarfile.open(out, "r:gz") as tar:
        meta_member = tar.extractfile("Check/metadata.csv")
        assert meta_member is not None
        recovered_meta = pd.read_csv(meta_member)
        pd.testing.assert_frame_equal(recovered_meta, meta)

        data_member = tar.extractfile("Check/annotated_features.csv")
        assert data_member is not None
        recovered_data = pd.read_csv(data_member)
        pd.testing.assert_frame_equal(recovered_data, data)


def test_empty_dataframes(tmp_path: Path):
    ds = ExportDataset(
        display_name="Empty",
        metadata_df=pd.DataFrame(columns=["sample_id"]),
        data_df=pd.DataFrame(columns=["sample_id", "gene"]),
        description=None,
    )
    out = build_export_tarball([ds], tmp_path / "export.tar.gz")

    with tarfile.open(out, "r:gz") as tar:
        meta_member = tar.extractfile("Empty/metadata.csv")
        assert meta_member is not None
        recovered = pd.read_csv(meta_member)
        assert list(recovered.columns) == ["sample_id"]
        assert len(recovered) == 0


def test_empty_dataset_list(tmp_path: Path):
    out = build_export_tarball([], tmp_path / "empty.tar.gz")
    assert out.exists()
    with tarfile.open(out, "r:gz") as tar:
        assert tar.getnames() == []


def test_tarball_no_path_traversal(tmp_path: Path):
    """Verify that adversarial display_names never produce traversal paths."""
    ds = ExportDataset(
        display_name="../../../etc/cron.d/backdoor",
        metadata_df=_sample_metadata(),
        data_df=_sample_data(),
        description=None,
    )
    out = build_export_tarball([ds], tmp_path / "export.tar.gz")

    with tarfile.open(out, "r:gz") as tar:
        for member in tar.getmembers():
            assert not member.name.startswith("/")
            assert ".." not in member.name.split("/")
