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

- A shinyapps.io account on the **Standard plan** (minimum 4 GB RAM; xxxlarge
  instance type recommended for 8 GB to match production)
- `rsconnect-python` installed: `pip install rsconnect-python`
- A HuggingFace token if any datasets are private
- labretriever published to PyPI or available as a wheel (see note below)

> **labretriever note.** shinyapps.io installs dependencies from PyPI only.
> Until labretriever is published to PyPI, build a wheel locally and include it
> in the bundle:
>
> ```bash
> cd ~/code/labretriever
> pip wheel . --no-deps -w /tmp/wheels
> cp /tmp/wheels/labretriever-*.whl /path/to/tfbpshiny/wheels/
> ```
>
> Then add `wheels/labretriever-*.whl` to your `requirements.txt` as a relative
> path. Once labretriever is on PyPI this step is not needed.

### 1. Download the HuggingFace data locally

The parquet files must be bundled with the deployment so the app never hits the
network on startup. Run the `initialize` command once, pointing at a directory
inside the project:

```bash
HF_TOKEN=<your_token> python -m tfbpshiny --cache-dir ./hf_cache initialize
```

This downloads all dataset parquet files into `hf_cache/` (~1.2 GB) and
verifies every view is readable. The directory is created relative to the
project root and will be included in the rsconnect upload bundle automatically.

Re-run this command any time the upstream datasets are updated.

### 2. Add hf_cache to .gitignore

The cache directory should not be committed to git:

```bash
echo "hf_cache/" >> .gitignore
```

### 3. Configure the app startup command

shinyapps.io invokes the app via the `app.py` entry point, but tfbpshiny uses
a CLI (`__main__.py`) to set environment variables before the Shiny process
starts. Create an `app.py` shim in the project root that applies the cache
directory before importing the Shiny app object:

```python
# app.py  (shinyapps.io entry point shim)
import os
from pathlib import Path

os.environ["HF_CACHE_DIR"] = str(Path(__file__).parent / "hf_cache")

from tfbpshiny.app import app  # noqa: E402  (must come after env var is set)
```

### 4. Set environment variables in the dashboard

In the shinyapps.io application dashboard under **Settings > Environment**,
add:

| Variable | Value |
|---|---|
| `HF_TOKEN` | your HuggingFace token (if datasets are private) |

Do not add `HF_CACHE_DIR` here — the shim above sets it from a path relative
to the bundle, which is more reliable than a hardcoded absolute path.

### 5. Set the instance type

In the shinyapps.io application dashboard under **Settings > General**, set:

- **Instance type**: `xxxlarge` (8192 MB) — recommended to match production
- **Max instances**: 3-5 depending on your plan

### 6. Deploy

```bash
rsconnect add \
    --account <your-shinyapps-account> \
    --name shinyapps \
    --token <token> \
    --secret <secret>

rsconnect deploy shiny . \
    --account <your-shinyapps-account> \
    --name tfbpshiny \
    --title "TF Binding and Perturbation"
```

rsconnect will bundle everything in the project directory, including `hf_cache/`.
The first deploy uploads ~1.2 GB; subsequent code-only deploys require
re-uploading the cache unless you use the `--exclude` flag with caution (do not
exclude `hf_cache/`).

### Updating the data

When upstream datasets change, re-run step 1 and redeploy:

```bash
HF_TOKEN=<your_token> python -m tfbpshiny --cache-dir ./hf_cache initialize
rsconnect deploy shiny . --account <your-shinyapps-account> --name tfbpshiny
```

### Differences from EC2 deployment

| | EC2 / Docker | shinyapps.io |
|---|---|---|
| Data persistence | Named Docker volume (permanent) |
Bundled at deploy time; resets on redeploy |
| Scaling | Single instance | Up to 5 instances (Standard plan) |
| Ops burden | Docker, Traefik, Terraform | None |
| Cold start | Fast (volume already mounted) | Fast (bundle already present) |
| Data update | `docker compose pull && up --build` | Re-run initialize + redeploy |

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
