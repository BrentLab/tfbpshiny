from logging import Logger

from shiny import reactive
from tfbpapi.AbstractAPI import AbstractAPI


def get_metadata_task(
    api: AbstractAPI, label: str, logger: Logger
) -> reactive.ExtendedTask:
    """
    This creates a reactive extended task that retrieves metadata from the database
    using the API .read() method.

    :param api: A child of AbstractAPI that has a .read() method
    :param label: A string that describes the API
    :param logger: A logger object
    :return: A reactive extended task that retrieves metadata from the database

    """

    @reactive.extended_task()
    async def get_metadata():
        logger.info(f"Retrieving {label} metadata")
        res = await api.read()
        logger.debug(f"Done getting {label} data")
        return res.get("metadata")

    return get_metadata
