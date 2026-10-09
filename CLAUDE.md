# TFBPShiny - Claude Development Guide

This document provides context for AI assistants working on the TFBPShiny project.

## Project Overview

TFBPShiny is a Shiny web application for exploring transcription factor binding and
perturbation data from the Brent Lab yeast collection. The application provides a
dashboard interface to visualize and analyze genomics data.

- **Main repository**: https://github.com/BrentLab/tfbpshiny
- **Data collection**: https://huggingface.co/collections/BrentLab/yeastresources
- **Production URL**: https://tfbindingandperturbation.com

## Reference Repositories

These reference repositories are available as workspace folders and online. Use them
when working with Shiny components, labretriever data access, SQL or plots — read their source rather
than guessing at APIs.

| Package | Local path | Online source |
|---------|-----------|---------------|
| py-shiny (Shiny for Python source) | `@py-shiny-site (reference)` | https://github.com/posit-dev/py-shiny |
| labretriever | `@labretriever (reference)` | https://github.com/cmatKhan/labretriever |
| duckDB (for SQL query reference) | `@duckdb (reference)` | https://duckdb.org/docs/stable/
| plotly | `@plotly (reference)`   | https://plotly.com/python/ |

## Technology Stack

### Shiny Framework

**IMPORTANT**: This application uses **Shiny Core** (NOT Shiny Express).

- **Official API reference**: https://shiny.posit.co/py/api/core/
- **Shiny for Python docs**: https://shiny.posit.co/py/docs/
- Always verify component signatures against the Shiny Core API — do not infer from
  Express examples or older shinysession patterns
- Version: ^1.4.0 (see pyproject.toml for exact version)

### labretriever Library

The application uses `labretriever` for data access and manipulation. It is installed from
the github branch via Poetry. When in doubt about available methods or data structures,
read the source in `@labretriever (reference)` or check https://brentlab.github.io/labretriever/.

### Other Key Dependencies

- **Python**: ^3.12
- **DuckDB**: the app's only data source at runtime
- **Plotly**: ^6.0.1 (interactive plots, rendered to HTML with `plotly.io.to_html`)
- **matplotlib**: static figures on the Figures page
- **faicons**: ^0.2.2 (icons)
- Plots do not use shinywidgets; see "Plotly rendering" in `docs/development.md`

## Application Architecture

### Module-Based Structure

```
tfbpshiny/
├── app.py              # Main application shell and orchestration
├── app.css             # Global styles and CSS custom properties
├── components.py       # Reusable styled UI component library (see below)
├── datasets.py         # Dataset vocabulary and constants shared by build and app
├── brentlab_yeast_collection.yaml  # labretriever collection config
├── www/                # Static assets (images; the Plotly JS bundle, gitignored)
├── modules/            # Feature modules
│   ├── home/           # The home page module (splash screen)
│   ├── binding/        # TF binding data module
│   ├── perturbation/   # Perturbation data module
│   ├── comparison/     # Comparison analysis module
│   ├── figures/        # Publication figures module
│   └── select_datasets/# Dataset selection module
├── materialize/        # Offline build of the DuckDB file (`tfbpshiny materialize`)
└── utils/              # Shared utilities
```

### Module Pattern

Each module follows a consistent structure:
- `ui.py` — `{module}_ui()`: a `ui.layout_sidebar` with the module's controls in
  the sidebar and its plots/tables in the main area
- `server/workspace.py` — `{module}_workspace_server()`, a `@module.server`
  function taking `conn`, `logger` and the shared reactives it needs
  (`select_datasets` additionally splits out `server/sidebar.py` and
  `server/dataset_row.py`, combined by `select_datasets_server`)
- Larger servers (`comparison`, `figures`) keep `workspace.py` thin: it builds a
  per-session context (`server/context.py`), registers shared reactives
  (`server/shared.py`) and then calls one `register_*` function per tab or figure
  (`server/fig6.py`, `server/compare_methods.py`, ...). Shiny registers a
  `@render.ui` / `@reactive.calc` against the current session wherever it is
  created, so those helpers need no decorator of their own. Output ids are fixed
  by `ui.py`; never rename one without changing both.
- `queries.py` (optional) — SQL the module runs against the read-only materialized
  DuckDB connection (`conn`). Builders return `(sql, params)`; `fetch_*` functions
  execute and return DataFrames. **Note**: queries.py is excluded from flake8 linting
  due to the presence of long SQL query strings that may exceed typical line length
  limits. The live builders are catalogued in `docs/sql_operations.md`.

### Styled Component Library (`components.py`)

`tfbpshiny/components.py` is the **single source of truth** for all reusable,
styled Shiny UI elements.  Every function maps to one or more CSS classes defined in
`app.css` and documents that mapping in its docstring.

**When to use it:**
- Any time you build a tooltip, sidebar label or text, workspace heading, empty state,
  dataset row, filter card, matrix (table, cell, header, row label), scroll row or
  export control, use the corresponding function from `components.py` rather than
  inlining the class string.
- When adding a new CSS class that will be used in more than one place, add a matching
  factory function to `components.py` at the same time.

**When to update it:**
- A CSS class in `app.css` is renamed → update the matching component function.
- A component's HTML structure changes (e.g. a new wrapper div) → update the function.
- A new globally reusable UI pattern appears in two or more module `ui.py` files →
  extract it into `components.py`.

**Rules:**
- No business logic or reactive code belongs here — only pure `ui.Tag` factories.
- Module `ui.py` and `server/*.py` files import from `components` (not from each
  other).
- `app.py` imports `github_badge` from `components`.
- Do **not** inline `{"class": "empty-state"}`, `{"class": "sidebar-text"}`, etc.
  anywhere else in the app — use `empty_state(...)`, `sidebar_text(...)` and the other
  factories. `grep -rn '"empty-state"' tfbpshiny/modules` should return nothing.

**Notable exception:** `select_datasets/ui.py` builds filter-option cards directly
because it injects a conditional "Apply to all datasets" toggle into the card header,
which the generic `filter_option_card()` component does not support.  The function
contains a comment explaining this.

### Layout System

`app.py` declares one `ui.page_navbar` with a `ui.nav_panel` per module, so Shiny owns
tab navigation. Inside its panel each module lays out its own sidebar (controls) and
workspace (plots, tables). `app.py` orchestrates shared state; modules own their UI and
server logic.

### Data Access

The app reads a single pre-built DuckDB file, `brentlab_yeast.duckdb`, produced
offline by `tfbpshiny materialize` from `brentlab_yeast_collection.yaml` via
`labretriever.VirtualDB`. `app_server` opens it read-only once per session and passes
the connection (`conn`) to every module server. `VirtualDB` is used only in
`tfbpshiny/materialize/` and the notebooks under `tmp/`; nothing on the read side
touches HuggingFace. See `docs/development.md` and `docs/materialized_db_schema.md`.

Dataset identity and presentation (labels, primary/variant structure, promoter set,
binding method, default-active, colours, notes) are declared once, as labretriever
`tags` in `brentlab_yeast_collection.yaml`; the promoter-set and binding-method
vocabularies are `PROMOTER_SETS` / `BINDING_METHODS` in `tfbpshiny/datasets.py`.
`materialize` reads the tags through `VirtualDB` (never parse the YAML in tfbpshiny)
and writes them into the registry tables; the app reads only those tables. Never
hardcode a dataset label, colour or db_name-to-label map in module code. Measurement
columns, levels and the dataset groups the figures use also live in `datasets.py`.

## Common Patterns

### Adding a New Module

1. Create module directory under `tfbpshiny/modules/`
2. Implement `ui.py` with `{module}_ui()`
3. Implement `server/workspace.py` with `{module}_workspace_server()` and re-export
   it from `server/__init__.py`
4. If the page needs data the database does not hold, add the table to
   `tfbpshiny/materialize/` first (see `docs/materialized_db_schema.md`)
5. In `app.py`: import the UI and server, add a `ui.nav_panel` to `page_navbar` (and
   to its `fillable` list), and call the module server from `app_server` with `conn`,
   `logger` and whichever shared reactives it needs

### Hiding a column from the filter UI

The filter modal lists every metadata column in `dataset_column_metadata` except those
in `HIDDEN_FILTER_FIELDS` in `tfbpshiny/utils/vdb_init.py` (keyed by primary dataset,
`"*"` for all; variants inherit). Raw source columns behind a standardized alias
(`condition` behind `Experimental condition`) are hidden there on purpose. How a
shown column is typed is set by `FIELD_TYPE_OVERRIDES` in the same file. The
materialized database is not changed by either.

### Working with the database

Module servers receive `conn`, a read-only `duckdb.DuckDBPyConnection`. Put SQL in
the module's `queries.py`; restrict rows to filtered samples with the helpers in
`utils/corr_query.py` (`get_filtered_sample_ids`, `expand_filters_to_variants`). If a
page needs a result that is not in the database, add it to `tfbpshiny/materialize/`
and rebuild rather than computing it at request time. When working on the materialize
side, refer to the labretriever docs or `@labretriever (reference)` source for
VirtualDB's methods.

## Development Commands

```bash
# Install dependencies
poetry install

# Build the database (once, ~20 min; pulls data from HuggingFace). The launch
# command's default --db-path is tfbpshiny/brentlab_yeast.duckdb
poetry run python -m tfbpshiny materialize \
    --config tfbpshiny/brentlab_yeast_collection.yaml \
    --output tfbpshiny/brentlab_yeast.duckdb

# Run the application (development)
poetry run python -m tfbpshiny --log-level DEBUG launch \
    --port 8010 --host 127.0.0.1 --debug

# Code quality
poetry run black .
poetry run isort .
poetry run mypy .

# Testing
poetry run pytest tests/unit/          # unit tests only
poetry run pytest tests/e2e/           # end-to-end tests only
poetry run pytest                       # all tests

# Install Playwright browsers (first time only, required for E2E)
poetry run playwright install chromium
```

After making changes, verify by running the app and checking for import errors or
reactive warnings in the console output. Run unit tests after any change to server
logic; run E2E tests when changing navigation, module wiring, or UI interactions.

## Testing

This project uses pytest for both unit and end-to-end testing. Follow Shiny's
official testing guidelines.

- **Unit testing docs**: https://shiny.posit.co/py/docs/unit-testing.html
- **E2E testing docs**: https://shiny.posit.co/py/docs/end-to-end-testing.html

### Test Organization

```
tests/
├── unit/                         # Pure-function unit tests (no reactive context)
│   ├── _collection.py            # VirtualDB stand-in over the real collection config
│   ├── _topn_oracle.py           # reference top-N SQL the staged builder is checked against
│   └── test_*.py                 # one file per module or materialize stage
└── e2e/                          # Playwright end-to-end tests (need brentlab_yeast.duckdb)
    ├── test_navigation.py        # Navigation smoke tests
    ├── test_outputs_render.py    # Every output on every page renders; optional text snapshot
    └── .snapshots/outputs.json   # Rendered text per output, for TFBPSHINY_E2E_SNAPSHOT=compare
```

`test_outputs_render.py` renders every page against the real database. Run it with
`TFBPSHINY_E2E_SNAPSHOT=compare` to check a change leaves every output's text
unchanged, or `=write` to re-record after an intended change.

### Unit Testing

Shiny for Python has no API for testing reactive server logic in isolation — there is
no `create_session` equivalent. Unit tests are limited to **pure Python functions**
that have been extracted from server code (e.g. query builders, ID generators,
data-transformation helpers). Test those with plain pytest; do not attempt to test
reactive effects or renders in unit tests.

Key patterns: test pure helper functions directly; for SQL builders, run the generated
SQL against a small in-memory DuckDB fixture built in the test rather than against
`brentlab_yeast.duckdb`.

### End-to-End Testing

E2E tests use Playwright to verify full application flow as a user would experience
it. Use sparingly — cover critical workflows (navigation, module switching, modal
interactions, data selection) rather than exhaustive UI states.

```python
from playwright.sync_api import Page, expect
from shiny.pytest import create_app_fixture

app = create_app_fixture("../../tfbpshiny/app.py")

def test_navigate_to_selection(page: Page, app):
    page.goto(app.url)
    page.locator('a.nav-link[data-value="Dataset selection"]').click()
    expect(page.locator(".selection-sidebar")).to_be_visible()
```

### Testing Best Practices

- Each test must be independent — no shared mutable state between tests
- Use fixtures for common setup (in-memory DuckDB tables, sample data)
- Mock all external dependencies in unit tests
- E2E tests should mirror real user workflows, not implementation details
- Include edge cases: empty data, error states, boundary conditions

## Code Style

- **Formatter**: Black (line-length: 88)
- **Import sorting**: isort (black profile)
- **Type checking**: mypy — use type annotations where possible (Python 3.11+)
- **Testing**: plain pytest (unit) and Playwright with `shiny.pytest` (E2E) — see
  Testing above
- **Docstrings**: Sphinx style. Document parameters and return values; do not repeat
  types (those go in type hints). Inline comments above the line, not beside it.
  For `@reactive.calc` and `@reactive.event` functions, document what triggers
  re-computation using a `:trigger:` field:

  ```python
  @reactive.calc
  def _pairs() -> list[tuple[str, str]]:
      """
      All unique pairs of active binding datasets.

      :trigger: ``active_binding_datasets`` — re-runs whenever the selected
          datasets change.
      :returns: List of ``(db_a, db_b)`` tuples, length = n choose 2.
      """
  ```

  Use `:trigger:` for `@reactive.calc` (what reactive inputs/values it depends on)
  and for `@reactive.effect @reactive.event(...)` (what event fires it).
- **Pre-commit hooks**: run `pre-commit install` once after cloning
- **Comments and documentation describe the current state only.** Do not write how
  a file, function or approach changed, what it replaced, or what an earlier version
  did ("no longer", "previously", "now uses", "legacy", "kept for backward
  compatibility"). Say what the code does and why. History belongs in `CHANGELOG.md`,
  which every change that alters behaviour, the database or the docs should update.

## Environment Configuration

- `tfbpshiny materialize` reads `HF_TOKEN` (or `--token`) for private HuggingFace
  repos and honours `HF_HOME` for the download cache; the collection YAML is passed
  with `--config`.
- `tfbpshiny launch --db-path` sets `TFBPSHINY_DB_PATH`, `TFBPSHINY_LOG_LEVEL` and
  `TFBPSHINY_LOG_HANDLER`, which `app.py` reads. The app needs nothing else.

## Logging

- Logger name: `"shiny"`
- Configured via `configure_logger()` in `__main__.py` before `run_app` is called.
- Controlled via CLI flags on the root parser (available to all subcommands):
  - `--log-level` (choices: DEBUG, INFO, WARNING, ERROR, CRITICAL; default: INFO)
  - `--log-handler` (choices: console, file; default: console)

## Branch Strategy

- `main` — the only long-lived branch
- Feature branches from `main` with descriptive names; keep up to date by rebasing

To contribute: open an issue, fork the repo, branch from `main`, open a PR to `main`
when complete.

## Important Notes / Common Mistakes

1. **Always use Shiny Core syntax** — not Express. If unsure, check
   https://shiny.posit.co/py/api/core/ or `@py-shiny-site (reference)`.
2. **Do not guess at labretriever APIs** — read the source in `@labretriever (reference)` or
   the docs at https://brentlab.github.io/labretriever/.
3. **Module isolation** — keep modules self-contained with clear interfaces.
4. **Reactive patterns** — follow Shiny's reactive programming model; avoid
   side effects outside reactive contexts.
5. **`conn` is opened once per session in `app.py`** and passed to modules as an
   argument; do not open the database file inside modules.
6. **No real data in unit tests** — never open `brentlab_yeast.duckdb` or hit
   HuggingFace from a unit test; build a small in-memory DuckDB fixture instead.
7. **E2E tests should be high-level** — test user workflows, not implementation details
  or extensively test internal state irrelevant to the specific user workflow being
  tested.
