"""
Entry point for shinyapps.io deployment.

Sets ``HF_CACHE_DIR`` to the bundled ``hf_cache/`` directory before importing
the Shiny app object, so that VirtualDB reads parquet files from the bundle
rather than attempting a HuggingFace network download.

Usage::

    rsconnect deploy shiny . --entrypoint shinyapps_entry:app ...

"""

import os
from pathlib import Path

os.environ["HF_CACHE_DIR"] = str(Path(__file__).parent / "hf_cache")
os.environ["TFBPSHINY_LOG_LEVEL"] = str(10)  # logging.DEBUG

from tfbpshiny.app import app  # noqa: E402,F401
