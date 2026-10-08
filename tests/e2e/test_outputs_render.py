"""
E2E: every ``output_ui`` on every page renders something against a real database.

The navigation tests assert only on static UI. This one needs the materialized
database: it opens each page, waits for every ``output_ui`` the page declares to carry
content, and checks nothing rendered a Shiny error.

It doubles as a before/after oracle for server refactors. With
``TFBPSHINY_E2E_SNAPSHOT=write`` it saves each output's text to
``tests/e2e/.snapshots/outputs.json``; with ``TFBPSHINY_E2E_SNAPSHOT=compare`` it
asserts the text is identical to that file. Without the variable it only checks
that outputs rendered, so it is deterministic in CI.

The database is ``brentlab_yeast.duckdb`` at the repository root unless
``TFBPSHINY_DB_PATH`` is set; the test is skipped when neither exists.

"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect
from shiny.pytest import create_app_fixture

_REPO = Path(__file__).resolve().parents[2]
_DB = Path(os.environ.get("TFBPSHINY_DB_PATH", _REPO / "brentlab_yeast.duckdb"))
# The app subprocess inherits the environment, so point it at the database here.
os.environ.setdefault("TFBPSHINY_DB_PATH", str(_DB))

_SNAPSHOT = Path(__file__).parent / ".snapshots" / "outputs.json"
_MODE = os.environ.get("TFBPSHINY_E2E_SNAPSHOT", "")

app = create_app_fixture("../../tfbpshiny/app.py", timeout_secs=60)

#: Navbar tab -> (module id, output_ui ids declared in that module's ui.py).
PAGES: dict[str, tuple[str, tuple[str, ...]]] = {
    "Dataset selection": (
        "select_datasets",
        ("sidebar_content", "matrix_content", "regulator_dataset_table_content"),
    ),
    "Binding": (
        "binding",
        (
            "analysis_status",
            "regulator_selector_box",
            "corr_matrix_container",
            "pair_box_container",
        ),
    ),
    "Perturbation": (
        "perturbation",
        (
            "analysis_status",
            "regulator_selector_box",
            "corr_matrix_container",
            "pair_box_container",
        ),
    ),
    "Binding/Perturbation Comparisons": (
        "comparison",
        (
            "analysis_status",
            "metric_controls",
            "tab_specific_controls",
            "cd_matrix_container",
            "cd_distribution_container",
        ),
    ),
    "Figures": (
        "figures",
        (
            "tf_selector",
            "figure_status",
            "fig_rank_response",
            "fig_topn_boxes",
            "fig_authors_bound",
            "fig_dto_bars",
            "fig_dto_venn",
            "agreement_dataset_picker",
            "fig_agreement_binding",
            "fig_agreement_perturbation",
            "fig_promoter_boxes",
            "fig_dto_significance_grid",
            "fig_method_boxes",
            "fig_shared_targets_binding",
            "fig_shared_targets_perturbation",
        ),
    ),
}

pytestmark = pytest.mark.skipif(
    not _DB.exists(), reason=f"no materialized database at {_DB}"
)


def _normalise(text: str) -> str:
    """Collapse whitespace and strip plotly's per-render element ids."""
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "ID", text
    )


@pytest.mark.parametrize("tab", list(PAGES))
def test_every_output_renders(page: Page, app, tab: str) -> None:
    module, outputs = PAGES[tab]
    page.goto(app.url)
    page.locator(f'a.nav-link[data-value="{tab}"]').click()

    rendered: dict[str, str] = {}
    for out in outputs:
        locator = page.locator(f"#{module}-{out}")
        # Figures compute from the database on first view; allow them time.
        expect(locator).not_to_be_empty(timeout=120_000)
        expect(locator.locator(".shiny-output-error")).to_have_count(0)
        rendered[out] = _normalise(locator.inner_text())

    if _MODE == "write":
        _SNAPSHOT.parent.mkdir(exist_ok=True)
        existing = json.loads(_SNAPSHOT.read_text()) if _SNAPSHOT.exists() else {}
        existing[tab] = rendered
        _SNAPSHOT.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n")
    elif _MODE == "compare":
        baseline = json.loads(_SNAPSHOT.read_text())[tab]
        assert rendered == baseline
