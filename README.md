# TFBPShiny

A Shiny web application for exploring transcription factor binding and perturbation
data from the [Brent Lab yeast collection](https://huggingface.co/collections/BrentLab/yeastresources).

## Table of contents

- [Resource Requirements](#resource-requirements)
- [Quick start](#quick-start)
  - [Install](#install)
  - [Build the database, then run the app](#build-the-database-then-run-the-app)
- [Contributing](#contributing)
  - [Setup](#setup)
  - [Plotly JS bundle](#plotly-js-bundle)
  - [Environment variables](#environment-variables)
  - [Running the app](#running-the-app)
  - [Running tests](#running-tests)
  - [Code quality](#code-quality)
  - [Branching](#branching)
- [Further documentation](#further-documentation)

---

## Resource Requirements

This app requires the following minimum resources to run:

- 4GB storage on disk
- 8GB RAM (10GB or more is recommended for better performance)

## Quick start

If you wish to keep the app separated from your local environment, you should first
create a virtual environment. You can do this with `venv`. `cd` to the directory
where you want the virtual environment to be created, and run:

```bash
python -m venv tfbpshiny_env
source tfbpshiny_env/bin/activate
```

### Install

```bash
python -m pip install tfbpshiny
```

### Build the database, then run the app

The app reads a single pre-built DuckDB file. Build it once (this pulls every dataset
from HuggingFace and runs the cross-dataset analyses; about twenty minutes), then
launch. The collection config ships inside the installed package:

```bash
CONFIG=$(python -c "import pathlib, tfbpshiny; print(pathlib.Path(tfbpshiny.__file__).parent / 'brentlab_yeast_collection.yaml')")
python -m tfbpshiny materialize --config "$CONFIG" --output brentlab_yeast.duckdb
python -m tfbpshiny launch --db-path brentlab_yeast.duckdb
```

Re-run `materialize` whenever the upstream datasets change. See
[docs/development.md](docs/development.md) for what the build produces.

To install the latest development version from GitHub, use:

```bash
python -m pip install git+https://github.com/BrentLab/tfbpshiny@dev
```

For shinyapps.io / Posit Connect deployment instructions, see
[docs/development.md](docs/development.md).

---

## Contributing

### Setup

```bash
git clone https://github.com/BrentLab/tfbpshiny.git
cd tfbpshiny
poetry install
pre-commit install
# First-time Playwright setup (required for E2E tests)
poetry run playwright install chromium
```

### Plotly JS bundle

The app loads Plotly from a local bundle (`tfbpshiny/www/plotly-3.5.0.min.js`)
rather than a CDN to avoid race conditions when multiple outputs initialize
simultaneously. This file is gitignored due to its size (~4.8 MB). After
cloning, download it once:

```bash
curl -fsSL https://cdn.plot.ly/plotly-3.5.0.min.js \
    -o tfbpshiny/www/plotly-3.5.0.min.js
```

If the `plotly` Python package is upgraded, check the new JS version it expects:

```bash
python -c "
import re, plotly.graph_objects as go
from plotly.io import to_html
m = re.search(r'plotly-([\d.]+)\.min\.js', to_html(go.Figure(), include_plotlyjs='cdn'))
print(m.group(0))
"
```

Then download the matching version and update the `src` in `tfbpshiny/app.py`.

### Environment variables

`HF_TOKEN` is read by `materialize` (or pass `--token`) and is only needed for
private HuggingFace datasets. `HF_HOME` controls where the downloads are cached. The
app itself reads `TFBPSHINY_DB_PATH`, which `launch --db-path` sets for you.

### Running the app

```bash
poetry run python -m tfbpshiny materialize \
    --config tfbpshiny/brentlab_yeast_collection.yaml \
    --output tfbpshiny/brentlab_yeast.duckdb   # once; the launch default path
poetry run python -m tfbpshiny --log-level DEBUG launch \
    --port 8010 --host 127.0.0.1 --debug
```

### Running tests

```bash
poetry run pytest tests/unit/      # unit tests
poetry run pytest tests/e2e/       # end-to-end
poetry run pytest                   # all tests
```

### Code quality

```bash
pre-commit run --all-files
```

### Branching

1. Switch to `dev`: `git switch dev`
1. Branch from `dev` — **not** `main`: `git switch -c my-feature`
1. Keep branches small and focused to make review easier
1. Rebase onto `dev` periodically: `git rebase dev`
1. When ready, open a pull request targeting the BrentLab `dev`
  branch — **not** `main`

---

## Further documentation

- [docs/development.md](docs/development.md): architecture, the build, and deployment
- [docs/materialized_db_schema.md](docs/materialized_db_schema.md): every table in the
  database
- [docs/sql_operations.md](docs/sql_operations.md): the SQL the app runs
- Page guides: [Dataset selection](docs/select_datasets_workflow.md),
  [Binding](docs/binding_workflow.md), [Perturbation](docs/perturbation_workflow.md),
  [Comparisons](docs/comparison_workflow.md)
- [CHANGELOG.md](CHANGELOG.md)
