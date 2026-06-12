# TFBPShiny

A Shiny web application for exploring transcription factor binding and perturbation
data from the [Brent Lab yeast collection](https://huggingface.co/collections/BrentLab/yeastresources).

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

### Run the app:

This will download the necessary datasets from huggingface into a cache directory
that is created in your current working directory. By default, it is called
`./tfbpshiny_hf_cache`. When you run the app again, if you launch it from the same
location it will verify that the cache is up to date, and use it, without
re-downloading. You can also specify a custom cache directory with `--cache-dir`.

```bash
python -m tfbpshiny launch
```

To install the latest development version from GitHub, use:

```bash
python -m pip install git+https://github.com/BrentLab/tfbpshiny@dev
```

For production deployment (EC2/Docker) and shinyapps.io deployment instructions,
see [docs/development.md](docs/development.md).

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

Create a `.env` file in the repo root to override defaults:

```bash
# Optional — only needed for private HuggingFace datasets
HF_TOKEN=<your_huggingface_token>

# Optional — override the VirtualDB config path
VIRTUALDB_CONFIG=/path/to/custom_config.yaml
```

### Running the app

```bash
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
