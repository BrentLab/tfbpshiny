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
   `comparative_dataset_registry`, `dataset_column_metadata`. Static registry tables
   generated from Python constants plus the VirtualDB column metadata. The registry's
   `is_primary` / `is_active_default` columns say which datasets the selection tab
   shows and which start switched on.
2. **Metadata layer** — one `{db_name}_meta` table per dataset (one row per sample,
   copied verbatim from the VirtualDB `_meta` view), `regulator_display_names`, and
   `sample_regulator` (`(db_name, sample_id) -> regulator_locus_tag`).
3. **HF-sourced comparison** — the `dto` table, copied from the comparative dataset's
   `dto_expanded` view and joined to `sample_regulator` to recover the regulator.
4. **Computed comparison tables** — `topn_results` (per binding sample × perturbation
   sample × top-N cutoff × responsiveness threshold pair; also the authors'-criteria
   rows at `top_n = 0` for the peak-calling datasets and Harbison), `topn_agreement`,
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
single phase. The default output path is the one `tfbpshiny launch` looks for, so a
rebuild is picked up on the next app start. Computed floats are rounded
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
- `HIDDEN_FILTER_FIELDS`, `FIELD_TYPE_OVERRIDES` — which metadata columns the filter
  UI hides, and how it types the ones it shows.
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
2. runs `utils.schema_check.warn_if_stale_topn_schema`, which logs a warning if the
   file was built by an older materializer;
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
intersections) and draws. The one place a page does non-trivial SQL is
`figures/queries.py`, where several figures join `topn_results` against the registry
to resolve dataset variants. Nothing on the read side touches target-level data.

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

## shinyapps.io Deployment

The app is deployed to [shinyapps.io](https://www.shinyapps.io) (moving to Posit
Connect, which uses the same `rsconnect` workflow).

### Prerequisites

- `rsconnect-python` installed: `pip install rsconnect-python`
- A HuggingFace token if any datasets are private

### 1. Build the database locally

The app never touches the network, so the materialized database must travel with the
bundle. Build it at the repository root (the path `shinyapps_entry.py` points at):

```bash
HF_TOKEN=<your_token> poetry run python -m tfbpshiny materialize \
    --config tfbpshiny/brentlab_yeast_collection.yaml \
    --output brentlab_yeast.duckdb
```

Re-run this any time the upstream datasets or the materialize code change. The file
is gitignored, but rsconnect does not read `.gitignore`, so it is included in the
upload bundle automatically.

### 2. Entry point

`shinyapps_entry.py` in the project root is the shinyapps.io entry point. It sets
`TFBPSHINY_DB_PATH` to the bundled `brentlab_yeast.duckdb` before importing the Shiny
app object, so no CLI flag is needed at runtime. No changes are required — the file is
already in the repository.

### 3. Set environment variables in the dashboard

Nothing is required: the app reads no secrets and makes no network requests at
runtime.

### 4. Deploy

Go to your shinyapps.io account, drop down the user menu, and go to **Tokens**. Click
"show" on the Python tab — it gives the `rsconnect add` command with `name`, `account`,
`token`, and `secret` pre-filled. Run it once to store credentials under a nickname;
subsequent deploys use `--name`.

Generate a `requirements.txt` from the Poetry lockfile before deploying (rsconnect
requires it; it is gitignored because it is a generated artifact):

```bash
poetry export --without-hashes --without dev -f requirements.txt -o requirements.txt
```

Regenerate this file after any change to dependencies in `pyproject.toml`.

Make sure the database is up to date, then deploy:

```bash
rsconnect add \
    --account <your-shinyapps-account> \
    --name <nickname> \
    --token <token> \
    --secret <secret>

CONNECT_REQUEST_TIMEOUT=3600 rsconnect deploy shiny . \
    --name <nickname> \
    --entrypoint shinyapps_entry:app \
    --title "TF Binding and Perturbation" \
    --exclude "tests" \
    --exclude "docs" \
    --exclude "tmp" \
    --exclude "data" \
    --exclude "scripts" \
    --exclude ".github" \
    --exclude ".vscode" \
    --exclude ".mypy_cache" \
    --exclude ".pytest_cache" \
    --exclude ".claude" \
    --exclude ".venv" \
    --exclude "mkdocs.yml" \
    --exclude "mkdocs_requirements.txt" \
    --exclude "*.log"
```

rsconnect does not read `.gitignore`; it bundles everything it finds unless told
otherwise. The `--exclude` flags above strip deployment-irrelevant directories.
`brentlab_yeast.duckdb` is intentionally not excluded — it is the data and must travel
with the app. Set `CONNECT_REQUEST_TIMEOUT` (seconds) high enough to cover the upload;
3600 (one hour) is safe.

### Updating the data

When upstream datasets change, re-run step 1 and redeploy with the same
`rsconnect deploy` command as step 4.
