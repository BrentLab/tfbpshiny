# TFBPShiny

This is a packaged shiny app for the frontend of django.tfbindingandperturbation.com

## Install

This may be installed from github using pip. It is recommended that you do this in
a virtual environment.

```bash
python -m venv tfbpshiny-env
source tfbpshiny-env/bin/activate  # On Windows: tfbpshiny-env\Scripts\activate
python -m pip install git+https://github.com/BrentLab/tfbpshiny@dev
```

Then, you can run the app using the `tfbpshiny` command line interface.

```bash
python -m tfbpshiny shiny
```

You can set the port and host using the `--port` and `--host` flags,
respectively. For example:

```bash
python -m tfbpshiny --log-level INFO shiny \
    --port 8010 --host 127.0.0.1
```

### Docker compose (production profile)

This is how to use [docker compose](https://docs.docker.com/compose/) to build the
production version of the app and run it in the containers:

1. First, clone the repo

1. Next, `cd` into the repo and add a `.envs/` directory. The `.envs` directory
  should have the following structure:

    `.envs/.production/{.shiny,.traefik}`

    Where `.shiny` and `.traefik` are text files. They should have the following
    variables at minimum:

    **.shiny**

    The huggingface hub token would only be useful if you have private datasets that
    you want to access from the app. If you only need to access public datasets,
    you can leave it out.

    ```raw
    DOCKER_ENV=true
    HUGGINGFACE_HUB_TOKEN=<your huggingface token>
    ```

    **.traefik**

    ```raw
    TRAEFIK_DASHBOARD_PASSWORD_HASH=<hashed password>
    ```

1. Next, you can build the image:

    ```bash
    docker compose -f production.yml build
    ```

1. And launch

    ```bash
    docker copmpose -f production.yml up
    ```

### Local development using poetry

Git clone the app as usual, cd into it and poetry install. If you need to provide
a huggingface token for local development, you can create a `.env` file in the
root of the repo with the following content:

```raw
HUGGINGFACE_HUB_TOKEN=<your huggingface token>
```

Then, you can run the app using the `poetry run` command:

```bash
# You don't need to set the `port` or `host` unless you need to use something other
# than port 8000 and localhost. `--debug` puts shiny in hot reload mode, which is
# useful for development
poetry run python -m tfbpshiny --log-level DEBUG shiny \
    --port 8010 --host 127.0.0.1 --debug
```

with any valid port that will work for you.

## Development

To issue pull requests, please:

1. fork to your own github repo

1. git clone the repo to your local or open a codespace from your fork

1. Make sure that you have [poetry](https://python-poetry.org/) and
  [pre-commit](https://pre-commit.com/) installed.
  `poetry install` and `pre-commit install`.

1. `git switch` to the `dev` branch. All feature branches must be
  branched from `dev` (*NOT* `main`)

1. Create a branch from `dev` (`git switch -c new_branch`) and start coding!
  Please keep feature branches as small as possible in order to
  make code review eaiser

1. Periodically `git rebase` back onto `dev` to make sure your feature
  branch stays up to date with the `dev` to make pull requests easier to merge.

1. When ready, commit, make sure that all `pre-commit` checks pass and issue a pull
  request to the BrentLab `dev` branch (*NOT* `main`!)
