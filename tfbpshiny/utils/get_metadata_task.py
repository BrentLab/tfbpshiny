from shiny import reactive


def get_metadata_task(api, label, logger):
    @reactive.extended_task()
    async def get_metadata():
        logger.info(f"Retrieving {label} metadata")
        res = await api.read()
        logger.debug(f"Done getting {label} data")
        return res.get("metadata")

    return get_metadata
