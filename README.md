# TFBPShiny

This is a packaged shiny app for the frontend of django.tfbindingandperturbation.com

## Install

This may be installed from github using pip. To install the most up to date version,
install the `dev` branch

```python
git+https://github.com/BrentLab/tfbpshiny@dev
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

    ```raw
    DOCKER_ENV=true
    BASE_URL='https://django.tfbindingandperturbation.com'
    TOKEN='your token here'
    BINDING_URL='https://django.tfbindingandperturbation.com/api/binding'
    BINDINGCONCATENATED_URL='https://django.tfbindingandperturbation.com/api/bindingconcatenated/'
    BINDINGMANUALQC_URL='https://django.tfbindingandperturbation.com/api/bindingmanualqc'
    CALLINGCARDSBACKGROUND_URL='https://django.tfbindingandperturbation.com/api/callingcardsbackground'
    DATASOURCE_URL='https://django.tfbindingandperturbation.com/api/datasource'
    DTO_URL='https://django.tfbindingandperturbation.com/api/dto'
    EXPRESSION_URL='https://django.tfbindingandperturbation.com/api/expression'
    EXPRESSIONMANUALQC_URL='https://django.tfbindingandperturbation.com/api/expressionmanualqc'
    FILEFORMAT_URL='https://django.tfbindingandperturbation.com/api/fileformat'
    GENOMICFEATURE_URL='https://django.tfbindingandperturbation.com/api/genomicfeature'
    PROMOTERSET_URL='https://django.tfbindingandperturbation.com/api/promoterset'
    PROMOTERSETSIG_URL='https://django.tfbindingandperturbation.com/api/promotersetsig'
    RANKRESPONSE_URL='https://django.tfbindingandperturbation.com/api/rankresponse'
    REGULATOR_URL='https://django.tfbindingandperturbation.com/api/regulator'
    UNIVARIATEMODELS_URL='https://django.tfbindingandperturbation.com/api/univariatemodels'
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

Git clone the app as usual, cd into it and poetry install. Add a .env
file that is the same as the `.shiny` file above, minus the `DOCKER_ENV`
variable. Then you can do:

```bash
poetry run python -m tfbpshiny --log-level INFO shiny \
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
