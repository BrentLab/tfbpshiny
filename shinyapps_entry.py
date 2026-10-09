"""
Entry point for Posit Connect Cloud deployment.

Points ``TFBPSHINY_DB_PATH`` at the bundled ``brentlab_yeast.duckdb`` before importing
the Shiny app object, so the deployed app reads the materialized database that
travelled with the upload bundle.

Named as the ``entrypoint`` in ``.posit/publish/tfbpshiny-LARU.toml``; see
``docs/development.md``.

"""

import os
from pathlib import Path

os.environ["TFBPSHINY_DB_PATH"] = str(Path(__file__).parent / "brentlab_yeast.duckdb")
os.environ["TFBPSHINY_LOG_LEVEL"] = str(10)  # logging.DEBUG

from tfbpshiny.app import app  # noqa: E402,F401
