"""
The app's view of ``brentlab_yeast_collection.yaml``: the one place dataset identity and
presentation are declared.

Per-dataset facts are labretriever ``tags`` (repository-level tags apply to every
dataset of the repository; dataset-level tags override them, exactly as
``VirtualDB.get_tags`` merges them):

==================  ===========================================================
``data_type``       ``binding`` or ``perturbation`` (datasets without one, such as
                    the comparative ``dto``, are not part of the registry)
``assay``           assay name, e.g. ``ChIPexo``
``display_name``    full label, e.g. ``2021 ChIP-exo (Rossi, Mindel)``
``base_label``      label shared by every variant of one experiment
``primary``         ``db_name`` of the primary dataset this one is a variant of; a
                    dataset naming itself (or nothing) is a primary
``promoter_set``    binding only: a key of ``tfbpshiny.promoter_sets``
``binding_method``  binding only: a key of ``tfbpshiny.binding_methods``
``active_default``  ``"true"`` to switch the dataset on in a new session
``color``           primaries only: series colour, shared by every variant
``peak_calling_note``  primaries only: how the assay's peak calls were made
==================  ===========================================================

The promoter-set and binding-method vocabularies live in the YAML's top-level
``tfbpshiny`` section, which labretriever ignores. A promoter set may name a
``region_set`` of the genome-resources repository instead of restating its
description.

Two consumers: ``tfbpshiny materialize`` writes the ``dataset_registry``,
``promoter_sets`` and ``binding_methods`` tables from this, and the app reads the
presentation-only facts (colours, descriptions, notes) here at runtime. Labels the app
needs inside SQL come from those tables, which were written from this file.

"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from tfbpshiny.datasets import METHOD_LEVELS, PROMOTER_SET_LEVELS

#: The collection config shipped with the package.
DEFAULT_CONFIG_PATH = Path(__file__).parent / "brentlab_yeast_collection.yaml"

_DATA_TYPES = ("binding", "perturbation")
_TRUE, _FALSE = "true", "false"


@dataclass(frozen=True)
class VocabEntry:
    """
    One promoter set or binding method.

    :param id: Identifier stored in the registry, e.g. ``"500bp"``.
    :param display_name: Label shown in the UI.
    :param description: Longer explanation (tooltips), may be empty.
    :param color: Series colour where the entry is a plot axis, or ``None``.
    :param reference: URL of the publication defining the entry, or ``None``.

    """

    id: str
    display_name: str
    description: str
    color: str | None
    reference: str | None = None


@dataclass(frozen=True)
class DatasetEntry:
    """
    One binding or perturbation dataset, as declared by its merged tags.

    :param db_name: VirtualDB view name.
    :param hf_repo: HuggingFace repository.
    :param hf_config: HuggingFace config within the repository.
    :param primary_db_name: The primary this dataset is a variant of, or ``None`` for
        a primary.

    """

    db_name: str
    hf_repo: str
    hf_config: str
    data_type: str
    assay: str
    display_name: str
    base_label: str
    primary_db_name: str | None
    is_active_default: bool
    promoter_set_id: str | None
    binding_method_id: str | None
    color: str | None
    peak_calling_note: str | None

    @property
    def is_primary(self) -> bool:
        return self.primary_db_name is None


@dataclass(frozen=True)
class AppConfig:
    """
    The validated contents, in config-file order.

    :param datasets: ``db_name -> DatasetEntry`` for every binding/perturbation
        dataset.
    :param promoter_sets: ``promoter_set_id -> VocabEntry``.
    :param binding_methods: ``binding_method_id -> VocabEntry``.

    """

    datasets: dict[str, DatasetEntry]
    promoter_sets: dict[str, VocabEntry]
    binding_methods: dict[str, VocabEntry]

    def colors_by_base_label(self, data_type: str) -> dict[str, str]:
        """``base_label -> colour`` for the primaries of one data type that set one."""
        return {
            d.base_label: d.color
            for d in self.datasets.values()
            if d.data_type == data_type and d.is_primary and d.color
        }


def _vocab(section: dict | None, region_sets: dict, what: str) -> dict[str, VocabEntry]:
    out: dict[str, VocabEntry] = {}
    for key, spec in (section or {}).items():
        spec = spec or {}
        if "display_name" not in spec:
            raise ValueError(f"tfbpshiny.{what}.{key}: display_name is required")
        description = spec.get("description")
        if description is None and spec.get("region_set"):
            rs = spec["region_set"]
            if rs not in region_sets:
                raise ValueError(
                    f"tfbpshiny.{what}.{key}: region_set {rs!r} is not declared in"
                    " any repository's genome_resources.region_sets"
                )
            description = region_sets[rs].get("description")
        out[str(key)] = VocabEntry(
            id=str(key),
            display_name=str(spec["display_name"]),
            description=" ".join(str(description or "").split()),
            color=spec.get("color"),
            reference=spec.get("reference"),
        )
    return out


def _parse(raw: dict) -> AppConfig:
    region_sets: dict = {}
    for repo in raw.get("repositories", {}).values():
        region_sets.update(
            ((repo or {}).get("genome_resources") or {}).get("region_sets") or {}
        )
    app = raw.get("tfbpshiny") or {}
    promoter_sets = _vocab(app.get("promoter_sets"), region_sets, "promoter_sets")
    methods = _vocab(app.get("binding_methods"), region_sets, "binding_methods")
    for level in PROMOTER_SET_LEVELS:
        if level not in promoter_sets:
            raise ValueError(f"tfbpshiny.promoter_sets is missing {level!r}")
    for level in METHOD_LEVELS:
        if level not in methods:
            raise ValueError(f"tfbpshiny.binding_methods is missing {level!r}")

    datasets: dict[str, DatasetEntry] = {}
    for repo_id, repo in raw["repositories"].items():
        repo = repo or {}
        for cfg_name, ds in (repo.get("dataset") or {}).items():
            tags = {**(repo.get("tags") or {}), **((ds or {}).get("tags") or {})}
            data_type = tags.get("data_type")
            if data_type not in _DATA_TYPES:
                continue
            db = str((ds or {}).get("db_name") or cfg_name)
            where = f"{repo_id}/{cfg_name} ({db})"
            missing = [
                k for k in ("assay", "display_name", "base_label") if not tags.get(k)
            ]
            if missing:
                raise ValueError(f"{where}: missing tag(s) {missing}")
            primary = tags.get("primary")
            ps, method = tags.get("promoter_set"), tags.get("binding_method")
            if data_type == "binding":
                if ps not in promoter_sets:
                    raise ValueError(f"{where}: unknown promoter_set {ps!r}")
                if method not in methods:
                    raise ValueError(f"{where}: unknown binding_method {method!r}")
            elif ps or method:
                raise ValueError(f"{where}: perturbation data has no promoter set")
            active = str(tags.get("active_default", _FALSE)).lower()
            if active not in (_TRUE, _FALSE):
                raise ValueError(f"{where}: active_default must be true or false")
            if db in datasets:
                raise ValueError(f"{where}: db_name {db!r} declared twice")
            datasets[db] = DatasetEntry(
                db_name=db,
                hf_repo=str(repo_id),
                hf_config=str(cfg_name),
                data_type=data_type,
                assay=str(tags["assay"]),
                display_name=str(tags["display_name"]),
                base_label=str(tags["base_label"]),
                primary_db_name=None if primary in (None, "", db) else str(primary),
                is_active_default=active == _TRUE,
                promoter_set_id=ps,
                binding_method_id=method,
                color=tags.get("color"),
                peak_calling_note=tags.get("peak_calling_note"),
            )

    for d in datasets.values():
        p = d.primary_db_name
        if p is None:
            continue
        if p not in datasets or not datasets[p].is_primary:
            raise ValueError(f"{d.db_name}: primary {p!r} is not a primary dataset")
        if datasets[p].data_type != d.data_type or datasets[p].base_label != (
            d.base_label
        ):
            raise ValueError(
                f"{d.db_name}: a variant must share its primary's data_type and"
                " base_label"
            )
    return AppConfig(datasets, promoter_sets, methods)


@lru_cache(maxsize=4)
def load_app_config(path: str | Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    """
    Read and validate a collection config.

    :param path: The collection YAML; defaults to the one shipped with the package.
    :returns: The parsed config.
    :raises ValueError: When a tag is missing, refers to an undeclared promoter set,
        method or primary, or a variant disagrees with its primary.

    """
    with open(path) as fh:
        return _parse(yaml.safe_load(fh))


__all__ = [
    "AppConfig",
    "DEFAULT_CONFIG_PATH",
    "DatasetEntry",
    "VocabEntry",
    "load_app_config",
]
