# Developer Notes

## Architecture Overview

TFBPShiny is a Shiny for Python (Core, not Express) application that serves as a
browser-based explorer for transcription factor binding and perturbation data from
the Brent Lab yeast collection. The source data are Parquet files on HuggingFace; the
app itself never reads them. Instead a one-off command line step, `tfbpshiny
materialize`, pulls every dataset through `labretriever.VirtualDB`, runs every
cross-dataset analysis the app can show, and writes the results to a single DuckDB
file, `brentlab_yeast.duckdb`. The app opens that file read-only and every page is a
set of SQL reads against it.

The application has six pages — Home, Dataset selection, Binding, Perturbation,
Binding/Perturbation Comparisons, and Figures — each a self-contained Shiny module
with its own `ui.py` and `server/` package.

```
HuggingFace parquet  --VirtualDB-->  tfbpshiny materialize  -->  brentlab_yeast.duckdb
                                                                        |
                                                 tfbpshiny launch  <----+  (read-only)
```

---

## Data Layer

### The materialized database

`tfbpshiny/materialize/` builds the database. The entry point is
`coordinator.materialize(output_path, vdb, args)`, which runs five logged phases:

1. **Coordinating layer** — `promoter_sets`, `binding_methods`, `dataset_registry`,
   `comparative_dataset_registry`, `dataset_column_metadata`, `schema_version`. The
   registry tables come from the collection config's tags and `tfbpshiny/datasets.py`
   (see below), the column metadata from VirtualDB. The registry's `is_primary` /
   `is_active_default` columns say which datasets the selection tab shows and which
   start switched on.
2. **Metadata layer** — one `{db_name}_meta` table per dataset (one row per sample,
   copied verbatim from the VirtualDB `_meta` view), `regulator_display_names`, and
   `sample_regulator` (`(db_name, sample_id) -> regulator_locus_tag`).
3. **HF-sourced comparison** — the `dto` table, copied from the comparative dataset's
   `dto_expanded` view and joined to `sample_regulator` to recover the regulator.
4. **Computed comparison tables** — `topn_results` (per binding sample × perturbation
   sample × top-N cutoff × responsiveness threshold pair; also the authors'-criteria
   rows at `top_n = 0` for the authors' peak calls, Harbison and Calling Cards),
   `topn_agreement`,
   `topn_target_sets`, and `correlations`. Each is filled pair by pair through
   VirtualDB in regulator batches.
5. **Method × promoter-set model** — `method_promoter_model_topn`,
   `method_promoter_model_target_universe`, `method_promoter_model_coefs`,
   `method_promoter_model_fit_summary`: the pooled OLS comparing peak calling with
   promoter enrichment across promoter definitions.

Every table, its columns and the SQL that generates it are described in
[materialized_db_schema.md](materialized_db_schema.md). The read-side SQL the app runs
against those tables is catalogued in [sql_operations.md](sql_operations.md).

Build it with:

```bash
poetry run python -m tfbpshiny materialize \
    --config tfbpshiny/brentlab_yeast_collection.yaml \
    --output brentlab_yeast.duckdb
```

A full build takes roughly fifteen to twenty minutes; `--skip-topn`,
`--skip-correlations` and `--skip-method-promoter-model` trim it while iterating on a
single phase. `materialize` writes to `brentlab_yeast.duckdb` in the current directory,
which is where `shinyapps_entry.py` looks; `tfbpshiny launch` defaults to
`tfbpshiny/brentlab_yeast.duckdb`, so pass `--db-path brentlab_yeast.duckdb` when
running locally. Computed floats are rounded
(`--float-decimals`, default ~1e-9) so two builds of the same data can be diffed;
`scripts/snapshot_db.py` / `scripts/diff_snapshots.py` fingerprint every table for
exactly that purpose.

The database file is gitignored (`brentlab_yeast*.duckdb`); it is a build artifact,
not source.

### What VirtualDB is, and where it is used

`VirtualDB` (from the `labretriever` package) is a DuckDB-backed in-memory database
that exposes the HuggingFace Parquet datasets as named SQL views: `<db_name>` for the
target-level data and `<db_name>_meta` for one row per sample with the derived columns
the collection YAML's property mappings define. The configuration is
`tfbpshiny/brentlab_yeast_collection.yaml`, which pins a HuggingFace revision per
repository so a build is reproducible.

VirtualDB is used **only** by `tfbpshiny materialize` and by the analysis notebooks
under `tmp/`. Its initialization is slow — one `snapshot_download()` per dataset
config, each contacting HuggingFace even on a warm cache — which is the reason the
app does not initialize it at runtime. `HF_HOME` controls where the downloads land;
`HF_TOKEN` (or `--token`) is needed only for private repositories.

### Dataset identity and presentation: the collection config

`tfbpshiny/brentlab_yeast_collection.yaml` is the one place a dataset's identity and
presentation are declared, as labretriever `tags` (repository-level tags apply to every
dataset in the repository; dataset-level tags override them):

| Tag | Meaning |
|---|---|
| `data_type` | `binding` or `perturbation`; datasets without one (the comparative `dto`) are not in the registry |
| `display_name`, `base_label` | full label, and the label shared by every variant of one experiment |
| `primary` | `db_name` of the primary this dataset is a variant of (a primary names itself or nothing) |
| `promoter_set`, `binding_method` | binding only; keys of `PROMOTER_SETS` / `BINDING_METHODS` in `tfbpshiny/datasets.py` |
| `assay`, `active_default`, `color`, `peak_calling_note` | assay name; on in a new session; series colour and peak-caller tooltip (primaries) |

The promoter sets and binding methods those tags refer to are app vocabulary, in
`tfbpshiny/datasets.py` (`PROMOTER_SETS`, `BINDING_METHODS`: display name, colour,
publication). A promoter set names the labretriever `genome_resources.region_sets`
entry it corresponds to, and takes its description from there.

Only `materialize` reads any of this, through labretriever (`vdb.get_tags`,
`vdb.db_name_map`, `vdb.get_region_sets`); `coordinating/sql.py::registry_rows` checks
the tags are coherent and writes the `dataset_registry`, `promoter_sets` and
`binding_methods` tables, labels, colours, links and notes included. The app reads only
those tables. Adding or relabelling a dataset is a YAML edit plus a rebuild.

### Dataset-level configuration in code

Per-dataset facts the app needs that are not in the database live in
`tfbpshiny/utils/vdb_init.py`:

- `DEFAULT_DATASET_FILTERS` — the sample filters applied on first load. They are
  keyed by the primary dataset the selection tab shows; the promoter-set and
  peak-calling variants of a primary inherit its filter via
  `utils.corr_query.expand_filters_to_variants`. The filters are chosen so that every
  dataset has exactly one sample per regulator.
- `DEFAULT_RESPONSIVENESS_PRESETS` — the `Relaxed` / `Stringent` (effect, p-value)
  threshold pairs per perturbation dataset. `materialize` stores a `topn_results`
  row for each pair a preset resolves to, so the app's preset selector is a filter,
  not a recomputation.
- `HIDDEN_FILTER_FIELDS` (keyed by primary dataset; variants inherit, see
  `hidden_filter_fields`), `FIELD_TYPE_OVERRIDES` — which metadata columns the filter
  UI hides, and how it types the ones it shows. To keep a column out of a dataset's
  filter modal, add it to that dataset's entry in `HIDDEN_FILTER_FIELDS`
  (`utils/vdb_init.py`), or to `"*"` to hide it everywhere. The database keeps the
  column; only the filter UI skips it. Two kinds of column are hidden on purpose:
  identifiers (`regulator_locus_tag`, `regulator_symbol`) and the raw source columns
  behind a standardized alias (`condition`, `env_condition`, `timepoint`), because
  the collection config already exposes the standardized column
  (`Experimental condition`) and showing both would offer the same filter twice.
- `load_app_datasets(conn)` — reads `dataset_column_metadata` into the
  condition/upstream column lists the selection tab builds its filter cards from.

---

## App Startup and Reactivity

### Startup

`tfbpshiny/app.py` is small. At import time it declares the six module UIs once and
assembles `ui.page_navbar`. `app_server` then, per browser session:

1. opens `duckdb.connect(TFBPSHINY_DB_PATH, read_only=True)` (the path is set by
   `python -m tfbpshiny launch --db-path`, defaulting to
   `tfbpshiny/brentlab_yeast.duckdb`);
2. runs `utils.schema_check.check_schema_version`, which compares the database's
   `schema_version` stamp with `tfbpshiny.datasets.SCHEMA_VERSION`; on a mismatch a
   banner is shown above every page;
3. calls `load_app_datasets(conn)`;
4. registers the home-card navigation effects and every module server, directly and
   unconditionally — there is no deferred registration and no loading state, because
   opening a DuckDB file is instantaneous.

Opening a new connection per session (rather than sharing one) is what makes the
read-only file safe under concurrent users.

### Shared reactive state

`select_datasets_server` returns three reactives that every other module consumes:
`active_binding_datasets`, `active_perturbation_datasets` (lists of `db_name`) and
`dataset_filters` (the committed per-dataset filter dict). `app.py` wraps the last in
`analysis_filters`, a `reactive.calc` that applies `expand_filters_to_variants` so the
analysis modules can look a filter up by whatever dataset variant they resolved.
Modules receive `analysis_filters` under the parameter name `dataset_filters`; it is a
drop-in because they only ever call it.

### Navigation

Pages are `ui.nav_panel`s of one `page_navbar` (`id="main_nav"`), so Shiny owns the
active tab; the home page's card links call `ui.update_navset("main_nav", ...)`. A
module's outputs are only computed while its panel is visible, which is Shiny's
default for hidden outputs, so there is no explicit gating of expensive calcs.

### Where the work happens

Every analysis the app shows was computed at materialize time; the server code
restricts rows to the filtered samples, aggregates (medians, fractions, set
intersections) and draws. Reads filter the computed tables on their plain `db_name` /
`sample_id` columns; the registry is read only to resolve a primary's variants and to
look up labels and colours. Nothing on the read side touches target-level data.

---

## Known Challenges

### DuckDB multi-threading and correlation edge cases

For the correlation calculations, DuckDB can produce undefined results when stddev
is 0 (zero-variance columns). This produces `NaN` correlations that need to be handled
gracefully downstream. See:

- https://github.com/duckdb/duckdb/issues/13763
- https://duckdb.org/docs/current/operations_manual/non-deterministic_behavior#floating-point-aggregate-operations-with-multi-threading

Do not set DuckDB threads to 1 unless it becomes a correctness requirement — the
performance cost is significant.

### Plotly rendering

Plots are rendered as static HTML blobs via `plotly.io.to_html` + `ui.HTML` with
`@render.ui`, rather than using `render_widget` / `output_widget` from shinywidgets.

The shinywidgets approach maintains a persistent comm channel between the Python server
and browser. When the user navigates away from a module the DOM is destroyed, tearing
down the comm. On return, shinywidgets fails to reattach with `t.views is undefined` /
`[anywidget] Runtime not found` client errors.

The `to_html` approach produces a self-contained HTML+JS blob that is fully re-rendered
by the browser on each `@render.ui` update, with no persistent state. Plotly figures
remain fully interactive client-side (hover, zoom, pan) but server-side plot event
callbacks are not possible. For large datasets or frequent updates this will be less
efficient.

If server-side callbacks become necessary, or rendering becomes prohibitively slow,
options include: a different plotting library, a custom Shiny widget wrapping raw
Plotly JS, or D3-based custom components.

---

## Posit Connect Cloud Deployment

The app is deployed to [Posit Connect Cloud](https://connect.posit.cloud) from VS Code
with the Posit Publisher extension. Publisher uploads the files named in
`.posit/publish/tfbpshiny-LARU.toml` directly from the working tree; Connect Cloud
does not pull from GitHub for this deployment.

### Prerequisites

- The [Posit Publisher](https://marketplace.visualstudio.com/items?itemName=posit.publisher)
  extension (pre-installed in Positron)
- A Connect Cloud account with access to the account the deployment targets
- A HuggingFace token if any datasets are private

### 1. Add a credential

In the Posit Publisher panel, open **Credentials**, click **+** and choose **Posit
Connect Cloud**. Log in through the browser, confirm the authorization code matches
the one shown in the IDE, authorize, and name the credential. This is done once per
machine.

### 2. Build the database locally

The app never touches the network, so the materialized database must travel with the
upload. Build it at the repository root (the path `shinyapps_entry.py` points at):

```bash
HF_TOKEN=<your_token> poetry run python -m tfbpshiny materialize \
    --config tfbpshiny/brentlab_yeast_collection.yaml \
    --output brentlab_yeast.duckdb
```

Re-run this any time the upstream datasets or the materialize code change. The
database is roughly 200 MB; Connect Cloud's bundle limit is 1 GiB on free plans and
5 GiB on all others.

### 3. Keep `requirements.txt` current

Connect Cloud installs dependencies from `requirements.txt` at the repository root.
It is generated from `poetry.lock`:

```bash
poetry export --without-hashes --without dev -f requirements.txt -o requirements.txt
```

The `poetry-export-requirements` pre-commit hook runs this whenever `poetry.lock` or
`pyproject.toml` is committed. When the export changes the file, the commit fails
once; stage the updated `requirements.txt` and commit again. The file is tracked, so
it is also what Publisher uploads.

### 4. The configuration file

`.posit/publish/tfbpshiny-LARU.toml` holds the deployment settings:

```toml
type = "python-shiny"
entrypoint = "shinyapps_entry.py"
title = "TF Binding and Perturbation"
files = [
    "/shinyapps_entry.py",
    "/requirements.txt",
    "/brentlab_yeast.duckdb",
    "/tfbpshiny",
]
product_type = "connect_cloud"

[python]
version = "3.12"
```

- `entrypoint` is a file, not a `module:object` reference. `shinyapps_entry.py` sets
  `TFBPSHINY_DB_PATH` to the bundled `brentlab_yeast.duckdb` and exposes the Shiny
  `app` object, so no environment variables or CLI flags are needed at runtime.
- `files` is an allowlist: only the listed paths are uploaded, so nothing needs to be
  excluded. The database is named by its exact path because the repository root
  holds other `brentlab_yeast*.duckdb` backups that must not be uploaded.
- `[python] version` matches `python` in `pyproject.toml`. Connect Cloud defaults to
  3.11, which the app does not support.

`.posit/publish/deployments/` records which Connect Cloud content item the
configuration publishes to. Both directories are committed; without the deployment
record, Publisher cannot update the existing content item.

### 5. Deploy

Open the Posit Publisher panel, select the `tfbpshiny-LARU` configuration and
credential, and under **Project Files** confirm that `brentlab_yeast.duckdb`,
`requirements.txt` and `tfbpshiny/` (including the gitignored
`tfbpshiny/www/plotly-*.min.js`) are included and that `__pycache__` and `*.log`
files are not. Then click **Deploy Your Project**. The panel shows **View Content**
on success and **View Publishing Log** on failure.

The app reads no secrets and makes no network requests at runtime, so the **Secrets**
section stays empty.

### Updating the data

When upstream datasets change, re-run step 2 and deploy again from the Publisher
panel. Any previous revision can be downloaded as a `.zip` from the content's history
page on Connect Cloud.

---

## Documentation Site

The pages in `docs/` are built into a static site by [Quarto](https://quarto.org),
configured in `docs/_quarto.yml`. The sidebar lists each page explicitly, so a new
page must be added there to appear in the navigation.

Quarto is a standalone program, not a Python dependency, so `poetry install` does not
provide it. Install it from [quarto.org/docs/download](https://quarto.org/docs/download/)
(on Debian or Ubuntu, `sudo dpkg -i quarto-*.deb` with the downloaded `.deb`). The
[Quarto VS Code extension](https://marketplace.visualstudio.com/items?itemName=quarto.quarto)
adds a preview command to the editor but still needs the Quarto program installed.

```bash
quarto preview docs    # build, serve locally and rebuild on save
quarto render docs     # write the static site to docs/_site/
```

`.github/workflows/docs.yml` renders the site and publishes it to the `gh-pages`
branch on every push to `main` that changes `docs/`. `docs/_site/` and the `.quarto`
cache directories are gitignored.
