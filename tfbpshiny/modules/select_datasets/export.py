"""Pure-function helpers for exporting selected datasets as a tarball."""

from __future__ import annotations

import io
import logging
import re
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from labretriever import VirtualDB

logger = logging.getLogger("shiny")

_SAFE_NAME_RE = re.compile(r"[^\w.\-]")


def _safe_dir_name(display_name: str) -> str:
    """
    Sanitize a display name for use as a tarball directory entry.

    Replaces any character outside ``[a-zA-Z0-9_.-]`` with ``_`` and strips
    leading/trailing dots and underscores to prevent path traversal.

    :param display_name: Raw display name.
    :returns: Filesystem-safe directory name.

    """
    sanitized = _SAFE_NAME_RE.sub("_", display_name)
    sanitized = sanitized.strip("_.")
    return sanitized or "dataset"


@dataclass(frozen=True)
class ExportDataset:
    """
    One dataset's worth of export data.

    .. note::
        ``frozen=True`` prevents attribute reassignment but does not prevent
        in-place mutation of the contained DataFrames. Callers should treat
        ``metadata_df`` and ``data_df`` as read-only.

    """

    display_name: str
    metadata_df: pd.DataFrame
    data_df: pd.DataFrame
    description: str | None = None


def build_readme(display_name: str, description: str) -> str:
    """
    Build README.md content for a single dataset subdirectory.

    :param display_name: Human-readable dataset name.
    :param description: Dataset description from the DataCard config.
    :returns: Markdown string.

    """
    return (
        f"# {display_name}\n"
        f"\n"
        f"{description}\n"
        f"\n"
        f"## Contents\n"
        f"\n"
        f"- **metadata.csv** -- Sample-level metadata for this dataset. Each row\n"
        f"  represents one sample (one regulator interrogation under specific\n"
        f"  experimental conditions).\n"
        f"\n"
        f"- **annotated_features.csv** -- Full genomic data for this dataset. Each\n"
        f"  row represents a measurement at a specific genomic feature (gene) for a\n"
        f"  specific sample.\n"
    )


def get_dataset_description(vdb: VirtualDB, db_name: str) -> str | None:
    """
    Retrieve the DataCard config description for a dataset.

    Uses private VirtualDB attributes; returns ``None`` on any failure.

    .. todo:: Replace with public VirtualDB API when available (issue #213).

    :param vdb: VirtualDB instance.
    :param db_name: Dataset name.
    :returns: Description string or ``None``.

    """
    try:
        repo_id, config_name = vdb._db_name_map[db_name]
        card = vdb._datacards.get(repo_id)
        if card is None:
            return None
        config = card.get_config(config_name)
        if config is None:
            return None
        return config.description or None
    except Exception:
        logger.warning(
            "Failed to retrieve DataCard description for %s (private API)", db_name
        )
        return None


def build_export_tarball(datasets: list[ExportDataset], output_path: Path) -> Path:
    """
    Assemble a ``.tar.gz`` archive from a list of export datasets.

    Each dataset becomes a subdirectory with a sanitized name (see
    :func:`_safe_dir_name`).
    The subdirectory contains ``metadata.csv``, ``annotated_features.csv``, and
    optionally ``README.md`` (when the dataset has a description).

    :param datasets: Datasets to include.
    :param output_path: Path for the resulting ``.tar.gz`` file.
    :returns: ``output_path``.

    """
    with tarfile.open(output_path, "w:gz") as tar:
        for ds in datasets:
            dir_name = _safe_dir_name(ds.display_name)

            # metadata.csv
            meta_buf = io.BytesIO()
            ds.metadata_df.to_csv(meta_buf, index=False)
            meta_buf.seek(0)
            meta_info = tarfile.TarInfo(name=f"{dir_name}/metadata.csv")
            meta_info.size = len(meta_buf.getvalue())
            tar.addfile(meta_info, meta_buf)

            # annotated_features.csv
            data_buf = io.BytesIO()
            ds.data_df.to_csv(data_buf, index=False)
            data_buf.seek(0)
            data_info = tarfile.TarInfo(name=f"{dir_name}/annotated_features.csv")
            data_info.size = len(data_buf.getvalue())
            tar.addfile(data_info, data_buf)

            # README.md (optional)
            if ds.description:
                readme_content = build_readme(ds.display_name, ds.description)
                readme_buf = io.BytesIO(readme_content.encode("utf-8"))
                readme_info = tarfile.TarInfo(name=f"{dir_name}/README.md")
                readme_info.size = len(readme_buf.getvalue())
                tar.addfile(readme_info, readme_buf)

    return output_path


__all__ = [
    "ExportDataset",
    "build_readme",
    "get_dataset_description",
    "build_export_tarball",
    "_safe_dir_name",
]
