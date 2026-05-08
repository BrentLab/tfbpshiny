# Developer Notes

## Architecture Overview

TFBPShiny is a Shiny for Python (Core, not Express) application that serves as a
browser-based explorer for transcription factor binding and perturbation data from
the Brent Lab yeast collection. Data is stored as Parquet files on HuggingFace and
accessed through a DuckDB-backed abstraction layer called VirtualDB (from the
`labretriever` package).

The application is structured around five pages — Home, Dataset Selection, Binding,
Perturbation, and Comparison — each implemented as a self-contained Shiny module with
its own UI, sidebar server, and workspace server.

---

## Data Layer: labretriever and VirtualDB

### What VirtualDB is

`VirtualDB` (from the `labretriever` package) is a DuckDB-backed in-memory database
that exposes multiple Parquet datasets as named SQL views. The application initializes
one VirtualDB instance at startup and passes it to every module that needs data access.
All SQL queries run against this single shared DuckDB connection.

The configuration lives in `brentlab_yeast_collection.yaml` at the repository root.
It declares eleven dataset configs across nine HuggingFace repositories:

| db_name               | Data type    | Repository                         |
|-----------------------|--------------|------------------------------------|
| callingcards          | binding      | BrentLab/callingcards              |
| harbison              | binding      | BrentLab/harbison_2004             |
| rossi                 | binding      | BrentLab/rossi_2021                |
| chec_m2025            | binding      | BrentLab/mahendrawada_2025         |
| hu_reimand            | perturbation | BrentLab/hu_2007_reimand_2010      |
| degron                | perturbation | BrentLab/mahendrawada_2025         |
| hughes_overexpression | perturbation | BrentLab/hughes_2006               |
| hughes_knockout       | perturbation | BrentLab/hughes_2006               |
| kemmeren              | perturbation | BrentLab/kemmeren_2014             |
| hackett               | perturbation | BrentLab/hackett_2020              |
| dto                   | comparative  | BrentLab/yeast_comparative_analysis|

Each dataset is accessible as a SQL view named `<db_name>` (raw data) and
`<db_name>_meta` (one row per sample, with derived columns from property mappings
defined in the YAML).

### What VirtualDB.__init__ does and why it is slow

`VirtualDB.__init__` performs four sequential phases:

1. **`_load_datacards()`** — Fetches the HuggingFace DataCard (README.md) for each
   of the nine repositories via `DatasetCard.load`, which internally calls
   `hf_hub_download`. On a warm restart the README.md files are already in the
   HuggingFace Hub local cache (`$HF_HOME/hub`), so no full download occurs. Whether
   `hf_hub_download` still makes a HEAD request to check the ETag before serving from
   cache is not currently verified — setting `HF_HUB_OFFLINE=1` or passing
   `local_files_only=True` would suppress any network check entirely.

2. **`_update_cache()`** — Calls `snapshot_download()` from `huggingface_hub` once
   per dataset config (eleven calls). Even when all Parquet files are already cached
   locally, `snapshot_download()` contacts HuggingFace to check for revision updates.
   On a warm restart with no data changes this is eleven unnecessary network roundtrips.

3. **`_register_all_views()`** — Creates DuckDB views for every dataset. The
   `CREATE VIEW` statements are lazy (no Parquet scan at creation), but `DESCRIBE`
   calls inside `_register_meta_view()` force schema inference, which reads the
   first row group of each Parquet file from disk.

4. **`_build_column_metadata()`** — Builds a Python dict of per-column metadata from
   the DataCards. No network or SQL; this is fast.

### Post-VirtualDB initialization in the app

`initialize_data()` in `tfbpshiny/utils/vdb_init.py` calls `VirtualDB(config)` and
then does three additional setup steps:

- **`ensure_hackett_analysis_set()`** — Runs a multi-CTE SQL query to build a filtered
  table of Hackett samples using a tiered priority scheme (ZEV-P > GEV-P > GEV-M),
  then rewrites the `hackett` and `hackett_meta` views to include only those samples.
  Three SQL statements total.

- **`_build_regulator_display_names()`** — Unions `SELECT DISTINCT
  regulator_locus_tag, regulator_symbol` across all datasets that have a
  `regulator_locus_tag` column (roughly ten datasets), then creates a
  `regulator_display_names` lookup table with formatted `"SYMBOL (LOCUS_TAG)"`
  display strings.

- **Column metadata classification** — Pure Python loop over `vdb.get_column_metadata()`
  results, partitioning columns into `condition_cols` and `upstream_cols` for each
  dataset. Fast.

`initialize_data()` returns a `(VirtualDB, AppDatasets)` tuple. `AppDatasets` is a
dataclass holding `condition_cols` and `upstream_cols` — the pre-computed column
classifications that inform the filter UI in the Dataset Selection module.

---

## Reactivity Strategy

### Startup: background thread + reactive signal

VirtualDB initialization blocks for several seconds (network + disk). To avoid a
blank screen while this happens, `app.py` runs `initialize_data()` in a daemon thread
and delivers the result back to the Shiny reactive graph once it completes:

```python
# In app_server():
_init_result: reactive.Value[tuple[VirtualDB, AppDatasets] | None] = reactive.value(None)
_loop = asyncio.get_event_loop()

def _run_init() -> None:
    result = initialize_data(virtualdb_config, hf_token)

    async def _deliver() -> None:
        async with reactive_lock():
            _init_result.set(result)
            await reactive_flush()

    _loop.call_soon_threadsafe(asyncio.create_task, _deliver())

threading.Thread(target=_run_init, daemon=True).start()
```

The `_deliver` coroutine acquires Shiny's reactive lock before calling `.set()` and
flushes inside the lock — matching the pattern used by Shiny's own `ExtendedTask`
internally. This is necessary because `reactive.Value.set()` only invalidates
dependents; it does not wake the session's event loop. The explicit flush inside the
lock is what causes Shiny to push the updated UI to the browser.

While `_init_result` is `None`, the home page renders immediately and any other module
shows "Loading data, please wait...". The navbar is fully functional throughout.

### Module server registration: lazy, once

All module servers (select_datasets, binding, perturbation, comparison) are registered
inside a single `@reactive.effect` that depends on `_init_result`:

```python
@reactive.effect
def _register_modules() -> None:
    result = _init_result()
    if result is None:
        return
    vdb, app_datasets = result
    # ... call all module server functions here
```

This effect fires exactly once — when `_init_result` transitions from `None` to the
actual data. Module servers are never called with a `None` vdb.

### Navigation: active_module reactive value

A single `reactive.Value[str]` called `active_module` tracks which page is currently
displayed. It starts as `"home"` and is updated by nav button click effects:

```python
@reactive.effect
@reactive.event(input.binding, ignore_init=True)
def _nav_binding() -> None:
    active_module.set("binding")
```

The `sidebar_region` and `workspace_region` render functions read `active_module()` and
return the appropriate UI for the current page, or a loading message if `_init_result`
is still `None`.

### Lazy calc execution: req() guards

Shiny's `@reactive.calc` is eager — it re-runs whenever any of its reactive
dependencies change, regardless of whether any render function is currently reading it.
Without guards, registering all module servers on startup would trigger all expensive
computations (correlation matrices, cross-dataset counts) immediately, even for modules
the user has never visited.

Each expensive workspace calc guards itself with `req()`:

```python
# In binding/server/workspace.py
@debounce(0.3)
@reactive.calc
def _all_corr_data() -> dict[tuple[str, str], pd.DataFrame]:
    if active_module is not None:
        req(active_module() == "binding")
    # ... expensive DuckDB correlation queries
```

The same pattern applies in `perturbation/server/workspace.py` (`req(active_module() == "perturbation")`),
`comparison/server/workspace.py` (`req(active_module() == "comparison")`), and
`select_datasets/server/workspace.py` (`req(active_module() == "selection")`).

`req()` raises `SilentException` when the condition is `False`, aborting the calc
silently and marking it for re-evaluation the next time it is called. When the user
navigates to a module, `active_module` changes, which invalidates the guarded calc and
causes it to run — this time passing the check and doing the actual work.

The `if active_module is not None` wrapper preserves compatibility with `page_test.py`
standalone test pages, which call module servers directly without passing `active_module`.

`active_module` is passed as an optional keyword argument to each workspace server
function. The sidebar server functions do not need it because their computations are
cheaper (dropdown population, toggle state) and are already gated by the filter modal
being open.

### Data flow summary

```
Browser connects
    |
    +-- home_ui() renders immediately (static HTML)
    |
    +-- background thread: initialize_data()
            |
            +-- VirtualDB(config)          [~5-30s depending on cache/network]
            +-- ensure_hackett_analysis_set()
            +-- _build_regulator_display_names()
            |
            +-- _deliver() fires reactive flush
                    |
                    +-- _register_modules() fires
                    |       |
                    |       +-- select_datasets_sidebar_server()
                    |       +-- select_datasets_workspace_server()
                    |       +-- binding_sidebar_server()
                    |       +-- binding_workspace_server()
                    |       +-- perturbation_sidebar_server()
                    |       +-- perturbation_workspace_server()
                    |       +-- comparison_sidebar_server()
                    |       +-- comparison_workspace_server()
                    |
                    +-- sidebar_region re-renders (shows nav controls)
                    +-- workspace_region re-renders (shows home page or current module)

User clicks "Binding"
    |
    +-- active_module.set("binding")
    +-- sidebar_region re-renders (binding sidebar UI)
    +-- workspace_region re-renders (binding workspace UI)
    +-- _all_corr_data() req() check passes -> DuckDB correlation queries run
```

---

## Known Challenges

### VirtualDB init speed

The dominant cost at startup is the eleven `snapshot_download()` calls in
`_update_cache()`. On a warm restart (all Parquet files already cached in the Docker
volume) these still contact HuggingFace to check for revision updates. There is no
`local_files_only=True` flag currently threaded through to `snapshot_download()`.
Adding one to labretriever would allow the production container to skip network
checks entirely after the first cold start.

The DataCard fetches in `_load_datacards()` go through `hf_hub_download`, which uses
the HuggingFace Hub local cache, so the README.md files are not re-downloaded on warm
restarts. Whether a HEAD request is made to check for updates is unverified. Each
`DatasetCard.load` call logs its elapsed time at DEBUG level; a time under ~0.1s
indicates a local cache hit, while a time over ~0.5s indicates a network fetch.
To enable this, start the app with `--log-level DEBUG`.

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

## Production Deployment

The production stack is defined in `production.yml` (Docker Compose). Two services:

- **shinyapp** — Runs the Shiny app on port 8000 inside the container. Mounts a named
  Docker volume `hf_cache` at `/hf-cache` with `HF_HOME=/hf-cache`, so HuggingFace
  Parquet downloads persist across container rebuilds. Environment variables `HF_TOKEN`
  and `DOCKER_ENV` are passed in from `.envs/.production/`.

- **traefik** — Reverse proxy handling HTTPS termination and Let's Encrypt certificate
  renewal for `tfbindingandperturbation.com`.

Both services use the AWS CloudWatch log driver. The EC2 instance and related
infrastructure (security group, IAM role, user_data.sh bootstrap) are managed by
Terraform in `terraform/`.
