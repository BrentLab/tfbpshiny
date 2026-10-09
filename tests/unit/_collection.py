"""
An offline stand-in for ``VirtualDB`` over the packaged collection config.

Exposes only the accessors the registry builders use (``get_datasets``, ``get_tags``,
``get_dataset_description``, ``db_name_map``, ``get_region_sets``), backed by
labretriever's own ``MetadataConfig`` so tag merging and ``db_name`` resolution are
labretriever's, not a re-implementation. Unlike ``VirtualDB`` it never contacts
HuggingFace.

"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from labretriever.models import MetadataConfig

import tfbpshiny

COLLECTION_YAML = Path(tfbpshiny.__file__).parent / "brentlab_yeast_collection.yaml"


class CollectionVDB:
    """
    The registry-facing slice of ``VirtualDB``, for the packaged config.

    :param tag_overrides: ``db_name -> tags`` merged over a dataset's own tags, for
        tests that need an inconsistent config.

    """

    def __init__(self, tag_overrides: dict[str, dict[str, str]] | None = None) -> None:
        self.config = MetadataConfig.from_yaml(COLLECTION_YAML)
        self._overrides = tag_overrides or {}
        # Same resolution as VirtualDB._build_db_name_map.
        self.db_name_map: dict[str, tuple[str, str]] = {
            ds.db_name or cfg: (repo_id, cfg)
            for repo_id, repo in self.config.repositories.items()
            for cfg, ds in (repo.dataset or {}).items()
        }

    def get_datasets(self) -> list[str]:
        return sorted(self.db_name_map)

    def get_tags(self, db_name: str) -> dict[str, str]:
        repo_id, cfg = self.db_name_map[db_name]
        return {
            **self.config.get_tags(repo_id, cfg),
            **self._overrides.get(db_name, {}),
        }

    def get_dataset_description(self, db_name: str) -> str | None:
        # The collection config's description only; VirtualDB falls back to the
        # DataCard, which needs HuggingFace.
        repo_id, cfg = self.db_name_map[db_name]
        return self.config.repositories[repo_id].dataset[cfg].description

    def get_region_sets(self, db_name: str) -> dict[str, Any]:
        # The collection declares its region sets in a genome-resources repository
        # (VirtualDB's "layer 3"), which applies to every dataset.
        out: dict[str, Any] = {}
        for repo in self.config.repositories.values():
            if repo.genome_resources is not None and repo.dataset is None:
                out.update(repo.genome_resources.region_sets)
        return out
