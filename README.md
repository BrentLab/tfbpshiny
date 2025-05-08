# TFBPShiny

This is a packaged shiny app for the frontend of django.tfbindingandperturbation.com

## Install

This may be installed from github using pip. To install the most up to date version,
install the `dev` branch

```python
git+https://github.com/BrentLab/tfbpshiny@dev
```

However, this will almost never be useful. If you wish to launch the app,
use [docker compose](https://docs.docker.com/compose/).

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
TRAEFIK_DASHBOARD_PASSWORD_HASH=$2y$05$ZiXKOnSW0AgGZykPV5KXte1YRuro7vyHR1Vv7lg2AQJEwjIT/ueEC
```

1. Next, you can build the image:  


```bash
docker compose -f production.yml build
```

1. And launch

```bash
docker copmpose -f production.yml up
```

1. If you are running this for development purposes from your local, you can use a `.env` file in the top
level of the repo and only start the `shinyapp` service. Add `DOCKER_ENV=false` to the `.env` and specify
the shinyapp only in the `docker compose` cmd:  

```bash
docker compose -f production.yml up
```

## Development

To issue pull requests, please: