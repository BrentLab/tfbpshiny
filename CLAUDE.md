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

Two companion repositories are available as workspace folders and online. Use them
when working with Shiny components or tfbpapi data access — read their source rather
than guessing at APIs.

| Package | Local path | Online source |
|---------|-----------|---------------|
| py-shiny (Shiny for Python source) | `@py-shiny-site (reference)` | https://github.com/posit-dev/py-shiny |
| tfbpapi | `@tfbpapi (reference)` | https://github.com/BrentLab/tfbpapi |
| duckDB (for SQL query reference) | `@duckdb (reference)` | https://duckdb.org/docs/stable/
| plotly | `@plotly (reference)`   | https://plotly.com/python/ |

**tfbpapi documentation**: https://brentlab.github.io/tfbpapi/

## Technology Stack

### Shiny Framework

**IMPORTANT**: This application uses **Shiny Core** (NOT Shiny Express).

- **Official API reference**: https://shiny.posit.co/py/api/core/
- **Shiny for Python docs**: https://shiny.posit.co/py/docs/
- Always verify component signatures against the Shiny Core API — do not infer from
  Express examples or older shinysession patterns
- Version: ^1.4.0 (see pyproject.toml for exact version)

### tfbpapi Library

The application uses `tfbpapi` for data access and manipulation. It is installed from
the `dev` branch via Poetry. When in doubt about available methods or data structures,
read the source in `@tfbpapi (reference)` or check https://brentlab.github.io/tfbpapi/.

### Other Key Dependencies

- **Python**: ^3.11
- **Plotly**: ^6.0.1 (for visualizations)
- **shinywidgets**: ^0.5.2
- **python-dotenv**: ^1.1.0 (environment configuration)
- **faicons**: ^0.2.2 (icons)

## Application Architecture

### Module-Based Structure

```
tfbpshiny/
├── app.py              # Main application shell and orchestration
├── app.css             # Global styles
├── modules/            # Feature modules
│   ├── home/           # The home page module (splash screen)
│   ├── binding/        # TF binding data module
│   ├── perturbation/   # Perturbation data module
│   ├── comparison/     # Comparison analysis module
│   └── select_datasets/# Dataset selection module
└── utils/              # Shared utilities
```

### Module Pattern

Each module follows a consistent structure:
- `ui.py` — UI component definitions (sidebar and workspace)
- `server/sidebar.py` — Sidebar server logic
- `server/workspace.py` — Workspace server logic
- `page_test.py` - This is a standalone Shiny app for testing the module in
  isolation during development. It should not be imported or referenced in
  the main app. It should set up mock data to pass as input to the module's
  server functions and render the UI components. As the testing framework
  is implemented and developed, this may become optional or be removed.
  However, currently it is required.
- `queries.py` (optional) — If needed, SQL query templates used in the module against
  `vdb`. **Note**: queries.py is excluded from flake8 linting due to the presence of
  long SQL query strings that may exceed typical line length limits. This allows for
  better readability of SQL queries without triggering linting errors.

### Layout System

The app uses a two-region layout:
1. **Sidebar region** — Dynamic content based on active module
2. **Workspace region** — Main content area for visualizations and data

`app.py` orchestrates overall application flow and state. Individual modules own their
UI and server logic. Navigation uses a top navbar with action buttons.

### Data Access

`VirtualDB` (`vdb`) is initialized once in `app.py` from `brentlab_yeast_collection.yaml`
and passed to modules as needed. Supports both local development and Docker deployment.

## Common Patterns

### Adding a New Module

1. Create module directory under `tfbpshiny/modules/`
2. Implement `ui.py` with `{module}_sidebar_ui()` and `{module}_workspace_ui()`
3. Implement `server/sidebar.py` with `{module}_sidebar_server()`
4. Implement `server/workspace.py` with `{module}_workspace_server()`
5. In `app.py`: add imports, navbar button, cases in `sidebar_region()` and
   `workspace_region()`, reactive effect for navigation, and module server calls

### Working with VirtualDB

Use the `vdb` instance to access data sources. Refer to the tfbpapi docs or
`@tfbpapi (reference)` source for available methods and data structures.

## Development Commands

```bash
# Install dependencies
poetry install

# Run the application (development)
poetry run python -m tfbpshiny --log-level DEBUG shiny \
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
poetry run playwright install
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
├── unit/           # Unit tests for server logic
│   ├── test_binding.py
│   ├── test_perturbation.py
│   └── test_select_datasets.py
└── e2e/            # End-to-end tests with Playwright
    ├── test_navigation.py
    ├── test_data_selection.py
    └── test_modal_interactions.py
```

### Unit Testing

Test server functions and reactive logic in isolation using `shiny.pytest` fixtures.
Do not test UI components in unit tests — test the server logic only.

```python
from shiny.pytest import create_session

def test_module_server():
    with create_session() as session:
        # mock inputs, assert outputs/reactive state
        pass
```

Key patterns: mock reactive inputs, verify outputs and reactive calculations, mock
external dependencies (VirtualDB, API calls) rather than hitting real data sources.

### End-to-End Testing

E2E tests use Playwright to verify full application flow as a user would experience
it. Use sparingly — cover critical workflows (navigation, module switching, modal
interactions, data selection) rather than exhaustive UI states.

```python
from playwright.sync_api import Page, expect
from shiny.pytest import create_app_fixture

app = create_app_fixture("path/to/app.py")

def test_navigation(page: Page, app):
    page.goto(app.url)
    page.click("#selection")
    expect(page.locator(".sidebar")).to_be_visible()
```

### Testing Best Practices

- Each test must be independent — no shared mutable state between tests
- Use fixtures for common setup (VirtualDB mocks, sample data)
- Mock all external dependencies in unit tests
- E2E tests should mirror real user workflows, not implementation details
- Include edge cases: empty data, error states, boundary conditions

## Code Style

- **Formatter**: Black (line-length: 88)
- **Import sorting**: isort (black profile)
- **Type checking**: mypy — use type annotations where possible (Python 3.11+)
- **Testing**: pytest with `shiny.pytest` (unit) and Playwright (E2E) — see Testing section below
- **Docstrings**: Sphinx style. Document parameters and return values; do not repeat
  types (those go in type hints). Inline comments above the line, not beside it.
- **Pre-commit hooks**: run `pre-commit install` once after cloning

## Environment Configuration

A `.env` file in the root directory can override the VirtualDB configuration or set
a HuggingFace token for private repo access. See `python-dotenv` docs for format.

## Logging

- Logger name: `"shiny"`
- Configured via `configure_logger()` from the `configure_logger` module
- Controlled via environment variables:
  - `TFBPSHINY_LOG_LEVEL` (default: 10 = DEBUG)
  - `TFBPSHINY_LOG_HANDLER` (default: "console")

## Docker Deployment

Production uses Docker Compose (`production.yml`). Environment files in
`.envs/.production/`. Traefik handles reverse proxy routing.

## Branch Strategy

- `main` — stable, production-ready
- `dev` — active development
- Feature branches from `dev` with descriptive names; keep up to date by rebasing

To contribute: open an issue, fork the repo, branch from `dev`, open a PR to `dev`
when complete.

## Important Notes / Common Mistakes

1. **Always use Shiny Core syntax** — not Express. If unsure, check
   https://shiny.posit.co/py/api/core/ or `@py-shiny-site (reference)`.
2. **Do not guess at tfbpapi APIs** — read the source in `@tfbpapi (reference)` or
   the docs at https://brentlab.github.io/tfbpapi/.
3. **Module isolation** — keep modules self-contained with clear interfaces.
4. **Reactive patterns** — follow Shiny's reactive programming model; avoid
   side effects outside reactive contexts.
5. **vdb is a singleton** — initialized once in `app.py`, passed to modules as an
   argument; do not re-instantiate it inside modules.
6. **Mock vdb in tests** — never hit real data sources in unit tests; create a mock
   VirtualDB fixture instead.
7. **E2E tests should be high-level** — test user workflows, not implementation details
  or extensively test internal state irrelevant to the specific user workflow being
  tested.
