"""Unit tests for select_datasets export helpers."""

from __future__ import annotations

import ast
import runpy
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from tfbpshiny.modules.select_datasets.export import (
    EXPORT_DIR_NAME,
    ExportDataset,
    _safe_dir_name,
    build_export_archive,
    build_readme,
    fetch_and_write_dataset,
    new_export_run_name,
    render_fetch_data_script,
    render_requirements_txt,
    render_top_level_readme,
)

# --- _safe_dir_name ---


def test_safe_dir_name_replaces_special_chars():
    assert _safe_dir_name("a/b c!") == "a_b_c"


def test_safe_dir_name_strips_leading_trailing():
    assert _safe_dir_name("..foo__") == "foo"


def test_safe_dir_name_empty_fallback():
    assert _safe_dir_name("***") == "dataset"


# --- new_export_run_name ---


def test_new_export_run_name_format():
    name = new_export_run_name()
    assert name.startswith(f"{EXPORT_DIR_NAME}-")
    timestamp = name[len(f"{EXPORT_DIR_NAME}-") :]
    datetime.strptime(timestamp, "%Y%m%d-%H%M%S")


# --- build_readme ---


def test_build_readme_contents():
    text = build_readme("Harbison 2004", "A ChIP-chip dataset.")
    assert "# Harbison 2004" in text
    assert "A ChIP-chip dataset." in text
    assert "**metadata.csv**" in text
    assert "**annotated_features.csv**" in text


# --- fetch_and_write_dataset ---


class _StubVDB:
    def __init__(
        self, meta_df: pd.DataFrame, data_df: pd.DataFrame, description: str | None
    ):
        self._meta_df = meta_df
        self._data_df = data_df
        self._description = description
        self.queries: list[tuple[str, dict[str, Any]]] = []

    def query(self, sql: str, **params: Any) -> pd.DataFrame:
        self.queries.append((sql, params))
        return self._meta_df if "meta" in sql else self._data_df

    def get_dataset_description(self, db_name: str) -> str | None:
        return self._description


def _entry(db_name: str = "harbison", display_name: str = "Harbison 2004") -> dict:
    return {
        "db_name": db_name,
        "display_name": display_name,
        "metadata_sql": "SELECT * FROM harbison_meta",
        "metadata_params": {},
        "data_sql": "SELECT * FROM harbison",
        "data_params": {},
    }


def test_fetch_and_write_dataset_writes_csvs_and_readme(tmp_path: Path):
    meta_df = pd.DataFrame({"sample_id": [1, 2]})
    data_df = pd.DataFrame({"sample_id": [1, 2], "score": [0.1, 0.2]})
    vdb = _StubVDB(meta_df, data_df, description="A description.")

    fetch_and_write_dataset(vdb, tmp_path, _entry())

    out_dir = tmp_path / "Harbison_2004"
    assert (out_dir / "metadata.csv").exists()
    assert (out_dir / "annotated_features.csv").exists()
    readme = (out_dir / "README.md").read_text()
    assert "A description." in readme

    written_meta = pd.read_csv(out_dir / "metadata.csv")
    pd.testing.assert_frame_equal(written_meta, meta_df)


def test_fetch_and_write_dataset_no_description_omits_readme(tmp_path: Path):
    meta_df = pd.DataFrame({"sample_id": [1]})
    data_df = pd.DataFrame({"sample_id": [1], "score": [0.1]})
    vdb = _StubVDB(meta_df, data_df, description=None)

    fetch_and_write_dataset(vdb, tmp_path, _entry())

    out_dir = tmp_path / "Harbison_2004"
    assert (out_dir / "metadata.csv").exists()
    assert not (out_dir / "README.md").exists()


# --- render_requirements_txt ---


def test_render_requirements_txt_matches_pyproject_floor():
    text = render_requirements_txt()
    assert "labretriever" in text

    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text()
    )
    caret = pyproject["tool"]["poetry"]["dependencies"]["labretriever"]
    floor = caret.lstrip("^")
    assert f">={floor}" in text


# --- render_top_level_readme ---


def test_render_top_level_readme_contains_usage_steps():
    text = render_top_level_readme()
    assert "python -m venv" in text
    assert "pip install -r requirements.txt" in text
    assert "python fetch_data.py" in text
    assert "brentlab_yeast_collection.yaml" in text


# --- render_fetch_data_script ---


def _sample_export_datasets() -> list[ExportDataset]:
    return [
        ExportDataset(
            db_name="harbison",
            display_name="2004 ChIP-chip",
            metadata_sql=(
                'SELECT * FROM harbison_meta WHERE "strain" IN ($cat_strain_0)'
            ),
            metadata_params={"cat_strain_0": "O'Brien"},
            data_sql="SELECT * FROM harbison",
            data_params={},
        ),
        ExportDataset(
            db_name="kemmeren",
            display_name="2014 TFKO (Kemmeren)",
            metadata_sql="SELECT * FROM kemmeren_meta",
            metadata_params={},
            data_sql=(
                'SELECT * FROM kemmeren WHERE "time" BETWEEN '
                "$num_time_lo AND $num_time_hi"
            ),
            data_params={"num_time_lo": 0.0, "num_time_hi": 30.0},
        ),
    ]


def test_render_fetch_data_script_contains_embedded_function_source():
    import inspect

    from tfbpshiny.modules.select_datasets.export import _EMBEDDED_FUNCS

    script = render_fetch_data_script(_sample_export_datasets())
    for fn in _EMBEDDED_FUNCS:
        assert inspect.getsource(fn) in script


def test_render_fetch_data_script_is_valid_python():
    script = render_fetch_data_script(_sample_export_datasets())
    ast.parse(script)


def test_render_fetch_data_script_empty_datasets_still_valid():
    script = render_fetch_data_script([])
    ast.parse(script)
    assert "DATASETS = []" in script


def test_render_fetch_data_script_round_trips_sql_and_params(tmp_path: Path):
    datasets = _sample_export_datasets()
    script = render_fetch_data_script(datasets)

    script_path = tmp_path / "fetch_data.py"
    script_path.write_text(script)
    ns = runpy.run_path(str(script_path))

    expected = [
        {
            "db_name": ds.db_name,
            "display_name": ds.display_name,
            "metadata_sql": ds.metadata_sql,
            "metadata_params": ds.metadata_params,
            "data_sql": ds.data_sql,
            "data_params": ds.data_params,
        }
        for ds in datasets
    ]
    assert ns["DATASETS"] == expected
    assert ns["CONFIG_PATH"] == tmp_path / "brentlab_yeast_collection.yaml"
    assert callable(ns["run_fetch"])
    assert callable(ns["fetch_and_write_dataset"])


# --- build_export_archive ---


def test_build_export_archive_has_expected_entries():
    import tarfile

    buf = build_export_archive(_sample_export_datasets())
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        names = sorted(m.name for m in tar.getmembers())
        assert names == [
            f"{EXPORT_DIR_NAME}/README.md",
            f"{EXPORT_DIR_NAME}/brentlab_yeast_collection.yaml",
            f"{EXPORT_DIR_NAME}/fetch_data.py",
            f"{EXPORT_DIR_NAME}/requirements.txt",
        ]

        config_member = tar.extractfile(
            f"{EXPORT_DIR_NAME}/brentlab_yeast_collection.yaml"
        )
        assert config_member is not None
        archived_bytes = config_member.read()

    import tfbpshiny

    real_config = (
        Path(tfbpshiny.__file__).parent / "brentlab_yeast_collection.yaml"
    ).read_bytes()
    assert archived_bytes == real_config


def test_build_export_archive_honors_run_name():
    import tarfile

    buf = build_export_archive(_sample_export_datasets(), run_name="custom_run")
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        names = sorted(m.name for m in tar.getmembers())
        assert names == [
            "custom_run/README.md",
            "custom_run/brentlab_yeast_collection.yaml",
            "custom_run/fetch_data.py",
            "custom_run/requirements.txt",
        ]


def test_build_export_archive_missing_config_raises(monkeypatch: pytest.MonkeyPatch):
    import tfbpshiny.modules.select_datasets.export as export_module

    monkeypatch.setattr(
        export_module.Path,
        "exists",
        lambda self: False,
    )
    with pytest.raises(FileNotFoundError):
        build_export_archive(_sample_export_datasets())
