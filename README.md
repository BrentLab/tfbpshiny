# TFBPShiny

A Shiny web application for exploring transcription factor binding and perturbation
data from the [Brent Lab yeast collection](https://huggingface.co/collections/BrentLab/yeastresources).

---

## Quick start (pip install)

Install from GitHub into a virtual environment:

```bash
python -m venv tfbpshiny-env
source tfbpshiny-env/bin/activate  # Windows: tfbpshiny-env\Scripts\activate
pip install git+https://github.com/BrentLab/tfbpshiny@dev
```

Run the app:

```bash
python -m tfbpshiny shiny
```

Options:

```bash
python -m tfbpshiny --log-level INFO shiny --port 8010 --host 127.0.0.1
```

---

## Production deployment

### Prerequisites

- An AWS account with permissions to create EC2 instances, IAM roles,
  and security groups
- [Terraform](https://developer.hashicorp.com/terraform/install) ≥ 1.0
- An EC2 key pair already created in `us-east-2` (or your target region)
- DNS A records for `tfbindingandperturbation.com`,
  `www.tfbindingandperturbation.com`,
  and `shinytraefik.tfbindingandperturbation.com` pointed at the
  instance's public IP

### 1. Provision the EC2 instance

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — set key_name and adjust instance_type / root_volume_gb
# if needed
terraform init
terraform apply
```

Note the `public_ip` output and update your DNS records to point at it.

### 2. Prepare the environment file

The app requires a single `.env` file that is **not** stored in the repository.
Create it locally and copy it to the instance:

#### .env

```bash
DOCKER_ENV=true
HF_TOKEN=<your_huggingface_token>       # optional; only for private HF datasets
VIRTUALDB_CONFIG=/path/to/config.yaml   # optional; defaults to bundled config
TRAEFIK_DASHBOARD_PASSWORD_HASH=myusername:$$2y$$05$$...  # see below
```

To generate the bcrypt hash for the Traefik dashboard:

```bash
docker run --rm httpd:alpine htpasswd -nbB myusername mypassword
```

This prints something like:

```
myusername:$2y$05$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ123456
```

Copy the full output into `.env`, but **escape every `$` as `$$`** so Docker
Compose does not interpret them as variable references:

```bash
TRAEFIK_DASHBOARD_PASSWORD_HASH=myusername:$$2y$$05$$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ123456
```

Copy the env file to the instance:

```bash
scp .env ec2-user@<public_ip>:/opt/tfbpshiny/
```

### 3. Build and start the stack

```bash
ssh ec2-user@<public_ip>
cd /opt/tfbpshiny
docker compose -f production.yml up -d --build
```

**First deploy only** — fix `/hf-cache` volume ownership so the non-root `appuser`
can write HuggingFace downloads to the named volume:

```bash
docker compose -f production.yml run --rm --user root shinyapp chown appuser /hf-cache
docker compose -f production.yml up -d
```

Traefik will automatically obtain a Let's Encrypt TLS certificate on first start.

### HuggingFace cache

The shinyapp container sets `HF_HOME=/hf-cache` and mounts a named Docker volume
there. HuggingFace model data is downloaded once and persists across container
rebuilds — no re-download on `docker compose up --build`. The volume ownership fix
above is only needed once; the volume retains correct permissions across rebuilds.

### Logs

Application and Traefik logs are sent to AWS CloudWatch Logs under the log group
`/tfbpshiny/production` in `us-east-2`.

---

## shinyapps.io deployment

This section describes how to deploy the app to
[shinyapps.io](https://www.shinyapps.io) as an alternative to the EC2/Docker
stack above. The two deployments are independent and can run in parallel.

### Prerequisites

- `rsconnect-python` installed: `pip install rsconnect-python`
- A HuggingFace token if any datasets are private

### 1. Download the HuggingFace data locally

The parquet files must be bundled with the deployment so the app never hits the
network on startup. Run the `initialize` command once, pointing at a directory
inside the project:

```bash
HF_TOKEN=<your_token> python -m tfbpshiny --cache-dir ./hf_cache initialize
```

**NOTE**: do call this hf_cache as it is already in the `.gitignore`

This downloads all dataset parquet files into `hf_cache/` (~1.2 GB) and
verifies every view is readable. The directory is created relative to the
project root and will be included in the rsconnect upload bundle automatically.

Re-run this command any time the upstream datasets are updated.

### 2. Entry point

`shinyapps_entry.py` in the project root is the shinyapps.io entry point. It
sets `HF_CACHE_DIR` to the bundled `hf_cache/` directory before importing the
Shiny app object, so no CLI flag is needed at runtime. No changes are required
— the file is already in the repository.

### 3. Set environment variables in the dashboard

In the shinyapps.io application dashboard under **Settings > Environment**,
add:

| Variable | Value |
|---|---|
| `HF_TOKEN` | your HuggingFace token (if datasets are private) |

Do not add `HF_CACHE_DIR` here — `shinyapps_entry.py` sets it from a path
relative to the bundle, which is more reliable than a hardcoded absolute path.

### 4. Deploy

**note**: Go to your shinyapps.io account, drop down the user menu, and go
to `Tokens`. If you click "show", and the python tab, it gives you this cmd with
the `name`,  `account`, `token` and `secret` filled in. Run `rsconnect add`
once to store credentials under a nickname; subsequent deploys use `--name`.

Generate a `requirements.txt` from the Poetry lockfile before deploying (rsconnect
requires it; it is gitignored because it is a generated artifact):

```bash
poetry export --without-hashes --without dev -f requirements.txt -o requirements.txt
```

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
    --exclude "terraform" \
    --exclude "compose" \
    --exclude "tests" \
    --exclude "docs" \
    --exclude "tmp" \
    --exclude "data" \
    --exclude ".github" \
    --exclude ".vscode" \
    --exclude ".mypy_cache" \
    --exclude ".pytest_cache" \
    --exclude ".claude" \
    --exclude ".venv" \
    --exclude "mkdocs.yml" \
    --exclude "mkdocs_requirements.txt" \
    --exclude "production.yml" \
    --exclude "*.log"
```

rsconnect does not read `.gitignore`; it bundles everything it finds unless told
otherwise. The `--exclude` flags above strip deployment-irrelevant directories.
`hf_cache/` is intentionally not excluded — it is the bundled dataset cache and
must travel with the app. The first deploy uploads ~1.2 GB; set
`CONNECT_REQUEST_TIMEOUT` (seconds) high enough to cover the upload — 3600 (one
hour) is safe.

### Updating the data

When upstream datasets change, re-run step 1 and redeploy:

```bash
HF_TOKEN=<your_token> python -m tfbpshiny --cache-dir ./hf_cache initialize
CONNECT_REQUEST_TIMEOUT=3600 rsconnect deploy shiny . \
    --name <nickname> \
    --entrypoint shinyapps_entry:app \
    --exclude "terraform" \
    --exclude "compose" \
    --exclude "tests" \
    --exclude "docs" \
    --exclude "tmp" \
    --exclude "data" \
    --exclude ".github" \
    --exclude ".vscode" \
    --exclude ".mypy_cache" \
    --exclude ".pytest_cache" \
    --exclude ".claude" \
    --exclude ".venv" \
    --exclude "mkdocs.yml" \
    --exclude "mkdocs_requirements.txt" \
    --exclude "production.yml" \
    --exclude "*.log"
```

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
poetry run python -m tfbpshiny --log-level DEBUG shiny \
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
