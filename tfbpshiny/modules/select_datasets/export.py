"""
Pure-function helpers for exporting selected datasets as a client-side fetch kit.

The exported ``.tar.gz`` holds no data. It bundles the VirtualDB yaml config, a
generated ``fetch_data.py`` script (embedding each active dataset's SQL + bound
params), a ``requirements.txt``, and a top-level ``README.md`` -- the user runs the
script locally to pull the data via ``labretriever``. See
``docs/select_datasets_workflow.md`` ("Export").

:func:`fetch_and_write_dataset` and :func:`run_fetch` are never called inside the
running app -- their source is extracted verbatim via ``inspect.getsource()`` and
embedded in the generated script by :func:`render_fetch_data_script`. Keeping them
as real, importable functions here (rather than as hand-written template text)
means there is exactly one copy of this logic, and it is independently testable.

"""

from __future__ import annotations

import inspect
import io
import pprint
import re
import tarfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from labretriever import VirtualDB

_REQUIREMENTS_TXT = "labretriever>=1.1.3,<2.0\n"

# Base name for the export run -- timestamped to build each run's name.
EXPORT_DIR_NAME = "tfbpshiny_export"

# Placeholder shown in static UI text, where the real timestamp isn't known yet.
EXPORT_RUN_NAME_PLACEHOLDER = f"{EXPORT_DIR_NAME}-<datetime>"


def new_export_run_name() -> str:
    """
    Build a timestamped run name shared by the downloaded archive's filename and the
    directory it extracts into, so repeated exports don't collide or overwrite each
    other on disk.

    :returns: ``tfbpshiny_export-<YYYYmmdd-HHMMSS>``

    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{EXPORT_DIR_NAME}-{timestamp}"


@dataclass(frozen=True)
class ExportDataset:
    """
    One dataset's export specification.

    The SQL and bound params are embedded verbatim into the generated
    ``fetch_data.py`` script (see :func:`render_fetch_data_script`) rather than
    executed server-side.

    :param db_name: Dataset key as registered in the VirtualDB config (e.g.
        ``"harbison"``) -- used by the generated script to call
        ``vdb.get_dataset_description(db_name)`` at runtime.
    :param display_name: Human-readable dataset name.
    :param metadata_sql: SQL for the dataset's metadata query.
    :param metadata_params: Bound params for ``metadata_sql``.
    :param data_sql: SQL for the dataset's full-data query.
    :param data_params: Bound params for ``data_sql``.
    :param description: Currently always ``None`` at the call site -- the
        running app has no live VirtualDB instance to source descriptions
        from. Descriptions are instead resolved client-side by the generated
        script via ``vdb.get_dataset_description(db_name)``. Reserved for a
        future caller that does have a live VirtualDB instance.

    """

    db_name: str
    display_name: str
    metadata_sql: str
    metadata_params: dict[str, Any]
    data_sql: str
    data_params: dict[str, Any]
    description: str | None = None


def _safe_dir_name(display_name: str) -> str:
    """
    Sanitize a display name for use as an output directory name.

    Replaces any character outside ``[a-zA-Z0-9_.-]`` with ``_`` and strips
    leading/trailing dots and underscores to prevent path traversal.

    Self-contained (no module-level dependency) so its source can be embedded
    verbatim in the generated ``fetch_data.py`` script via
    :func:`render_fetch_data_script`.

    :param display_name: Raw display name.
    :returns: Filesystem-safe directory name.

    """
    sanitized = re.sub(r"[^\w.\-]", "_", display_name)
    sanitized = sanitized.strip("_.")
    return sanitized or "dataset"


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


def fetch_and_write_dataset(
    vdb: VirtualDB, out_root: Path, entry: dict[str, Any]
) -> None:
    """
    Query one dataset via VirtualDB and write its CSV/README output.

    Never called inside the running tfbpshiny app -- this function's source is
    embedded verbatim in the generated ``fetch_data.py`` script (see
    :func:`render_fetch_data_script`) and only ever executes on the user's
    machine.

    :param vdb: A VirtualDB instance (or any object exposing ``.query()`` and
        ``.get_dataset_description()``).
    :param out_root: Directory under which the dataset's subdirectory is
        created.
    :param entry: One dataset's dict -- keys ``db_name``, ``display_name``,
        ``metadata_sql``, ``metadata_params``, ``data_sql``, ``data_params``.

    """
    db_name = entry["db_name"]
    display_name = entry["display_name"]
    print(f"Fetching {display_name} ({db_name}) ...")

    meta_df = vdb.query(entry["metadata_sql"], **entry["metadata_params"])
    data_df = vdb.query(entry["data_sql"], **entry["data_params"])

    dir_name = _safe_dir_name(display_name)
    out_dir = out_root / dir_name
    out_dir.mkdir(parents=True, exist_ok=True)

    meta_df.to_csv(out_dir / "metadata.csv", index=False, lineterminator="\n")
    data_df.to_csv(out_dir / "annotated_features.csv", index=False, lineterminator="\n")

    description = vdb.get_dataset_description(db_name)
    if description:
        (out_dir / "README.md").write_text(
            build_readme(display_name, description), encoding="utf-8"
        )

    print(f"  wrote {dir_name}/metadata.csv, {dir_name}/annotated_features.csv")


def run_fetch(config_path: Path, datasets: list[dict[str, Any]]) -> None:
    """
    Entry point embedded as the generated script's ``__main__`` call.

    Never called inside the running tfbpshiny app -- this function's source is
    embedded verbatim in the generated ``fetch_data.py`` script (see
    :func:`render_fetch_data_script`). Lazily imports ``VirtualDB`` so this
    module never needs ``labretriever`` imported at load time in the running
    app process.

    :param config_path: Path to the VirtualDB yaml config (bundled alongside
        the generated script in the export tarball).
    :param datasets: List of dataset entry dicts -- see
        :func:`fetch_and_write_dataset`.

    """
    from labretriever import VirtualDB

    vdb = VirtualDB(config_path)
    out_root = config_path.parent
    for entry in datasets:
        fetch_and_write_dataset(vdb, out_root, entry)
    print("Done.")


# Functions whose source is embedded verbatim in the generated fetch_data.py
# script. Order matters: later functions may reference earlier ones.
_EMBEDDED_FUNCS = (_safe_dir_name, build_readme, fetch_and_write_dataset, run_fetch)


def _render_dataset_block(ds: ExportDataset) -> dict[str, Any]:
    """
    Build the literal dict for one dataset's entry in the generated script.

    :param ds: Export specification for one active dataset.
    :returns: Plain dict with keys ``db_name``, ``display_name``,
        ``metadata_sql``, ``metadata_params``, ``data_sql``, ``data_params``.

    """
    return {
        "db_name": ds.db_name,
        "display_name": ds.display_name,
        "metadata_sql": ds.metadata_sql,
        "metadata_params": ds.metadata_params,
        "data_sql": ds.data_sql,
        "data_params": ds.data_params,
    }


def render_fetch_data_script(
    datasets: list[ExportDataset],
    config_filename: str = "brentlab_yeast_collection.yaml",
) -> str:
    """
    Render the full ``fetch_data.py`` script text for the given datasets.

    The script embeds each dataset's SQL + params as a literal ``DATASETS``
    list, plus the verbatim source of :data:`_EMBEDDED_FUNCS` (extracted via
    ``inspect.getsource()``), so it has no dependency on ``tfbpshiny`` at
    runtime -- only on ``labretriever``.

    :param datasets: Export specs for all datasets active at export time.
    :param config_filename: Name of the VirtualDB config yaml bundled
        alongside the script in the export tarball.
    :returns: Complete Python source for ``fetch_data.py``.

    """
    blocks = [_render_dataset_block(ds) for ds in datasets]
    datasets_literal = pprint.pformat(blocks, indent=4, width=88, sort_dicts=False)
    helper_source = "\n\n".join(inspect.getsource(fn) for fn in _EMBEDDED_FUNCS)

    return (
        '"""\n'
        'Auto-generated by tfbpshiny\'s "Export Selected Datasets" feature.\n'
        "\n"
        "Run this script to download the selected datasets via labretriever and\n"
        "write them to disk: one subdirectory per dataset containing\n"
        "metadata.csv, annotated_features.csv, and (when available) README.md.\n"
        "\n"
        "Usage:\n"
        "    python fetch_data.py\n"
        '"""\n'
        "from __future__ import annotations\n"
        "\n"
        "import re\n"
        "from pathlib import Path\n"
        "\n"
        f"CONFIG_PATH = Path(__file__).parent / {config_filename!r}\n"
        "\n"
        f"DATASETS = {datasets_literal}\n"
        "\n"
        "\n"
        f"{helper_source}\n"
        "\n"
        '\nif __name__ == "__main__":\n'
        "    run_fetch(CONFIG_PATH, DATASETS)\n"
    )


def render_requirements_txt() -> str:
    """
    Render the top-level ``requirements.txt`` content for the export kit.

    Pins a version range rather than an exact version -- the materialized app
    data and the SQL in ``select_datasets/queries.py`` depend on the VirtualDB
    view/table schema, which is stable across labretriever patch/minor
    versions within the same major version, matching the floor declared in
    ``pyproject.toml`` (``labretriever = "^1.1.3"``).

    :returns: Contents for ``requirements.txt``.

    """
    return _REQUIREMENTS_TXT


def render_top_level_readme(
    config_filename: str = "brentlab_yeast_collection.yaml",
    script_filename: str = "fetch_data.py",
) -> str:
    """
    Render the top-level README.md for the export kit tarball.

    :param config_filename: Name of the bundled VirtualDB config yaml.
    :param script_filename: Name of the bundled fetch script.
    :returns: Markdown instructions for extracting and running the kit.

    """
    return (
        f"# tfbpshiny dataset export\n"
        f"\n"
        f"This archive contains everything needed to download the datasets you "
        f"selected on the tfbpshiny dataset selection page, run locally on your "
        f"own machine.\n"
        f"\n"
        f"## Contents\n"
        f"\n"
        f"- `{config_filename}` -- labretriever VirtualDB configuration (the same "
        f"config the tfbpshiny app itself uses).\n"
        f"- `{script_filename}` -- script that downloads and writes out each "
        f"selected dataset.\n"
        f"- `requirements.txt` -- Python dependencies required to run "
        f"`{script_filename}`.\n"
        f"\n"
        f"## Usage\n"
        f"\n"
        f"```bash\n"
        f"python -m venv .venv\n"
        f"source .venv/bin/activate  # on Windows: .venv\\Scripts\\activate\n"
        f"pip install -r requirements.txt\n"
        f"python {script_filename}\n"
        f"```\n"
        f"\n"
        f"## Output\n"
        f"\n"
        f"Running `{script_filename}` creates one subdirectory per dataset (named "
        f"after the dataset's display name), each containing `metadata.csv`, "
        f"`annotated_features.csv`, and, when available, a per-dataset "
        f"`README.md` describing the dataset's contents.\n"
        f"\n"
        f"If the script errors, check your network connection and `HF_TOKEN` "
        f"environment variable (required for private HuggingFace repos), then "
        f"re-run it.\n"
    )


def build_export_archive(
    datasets: list[ExportDataset], run_name: str = EXPORT_DIR_NAME
) -> io.BytesIO:
    """
    Assemble the export kit ``.tar.gz`` in memory.

    Bundles a copy of the VirtualDB config yaml, a generated ``fetch_data.py``
    script embedding each dataset's SQL + params, a ``requirements.txt``, and
    a top-level ``README.md`` with run instructions. No SQL is executed and no
    DuckDB connection is touched -- this is pure string templating plus one
    small file read.

    :param datasets: Export specs for all datasets active at export time.
    :param run_name: Directory name the tarball's entries are prefixed with
        -- pass the same value used to build the downloaded filename (see
        :func:`new_export_run_name`) so extracting the archive produces a
        directory matching what the download instructions told the user.
    :returns: ``BytesIO`` buffer positioned at the start, ready for reading.
    :raises FileNotFoundError: If the bundled VirtualDB config yaml cannot be
        located on disk (a packaging error, not a user-facing scenario).

    """
    config_filename = "brentlab_yeast_collection.yaml"
    config_path = Path(__file__).resolve().parents[2] / config_filename
    if not config_path.exists():
        raise FileNotFoundError(
            f"VirtualDB config not found at {config_path} -- "
            "cannot build export archive."
        )
    config_bytes = config_path.read_bytes()

    script_bytes = render_fetch_data_script(datasets, config_filename).encode("utf-8")
    requirements_bytes = render_requirements_txt().encode("utf-8")
    readme_bytes = render_top_level_readme(config_filename).encode("utf-8")

    out = io.BytesIO()
    with tarfile.open(mode="w|gz", fileobj=out) as tar:
        for name, data in (
            (config_filename, config_bytes),
            ("fetch_data.py", script_bytes),
            ("requirements.txt", requirements_bytes),
            ("README.md", readme_bytes),
        ):
            info = tarfile.TarInfo(name=f"{run_name}/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    out.seek(0)
    return out


__all__ = [
    "EXPORT_DIR_NAME",
    "EXPORT_RUN_NAME_PLACEHOLDER",
    "ExportDataset",
    "new_export_run_name",
    "build_readme",
    "fetch_and_write_dataset",
    "run_fetch",
    "render_fetch_data_script",
    "render_requirements_txt",
    "render_top_level_readme",
    "build_export_archive",
    "_safe_dir_name",
]
