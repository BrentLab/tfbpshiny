import logging

from shiny import ui
from shiny.types import MISSING, MISSING_TYPE
from shiny.ui._accordion import AccordionPanel

logger = logging.getLogger("shiny")


def create_accordion_panel(
    title: str,
    *content: ui.TagChild,
    value: str | None | MISSING_TYPE = MISSING,
    icon: ui.TagChild | None = None,
    **kwargs,
) -> AccordionPanel:
    """
    Create a single accordion panel (an item to be placed within a ui.accordion
    container).

    :param title: The title of the accordion panel.
    :param content: The content of the accordion panel. e.g. a ui.input_checkbox_group.
    :param value: The value of the accordion panel. Default is MISSING.
    :param icon: The icon of the accordion panel. Default is None.
    :return: An accordion panel.
    :raises ValueError: If the title is not a string, or if the content is not a list or
        tuple, or if the value is not a string, or if the icon is not a ui.TagChild.

    """

    if not isinstance(title, str):
        logger.error(f"title must be a string: {title}")
        raise ValueError("title must be a string")

    if not isinstance(content, (list, tuple)):
        logger.error(f"content must be a list or tuple: {content}")
        raise ValueError("content must be a list or tuple")

    for item in content:
        if not isinstance(item, ui.Tag):
            logger.error(f"content must be a list of ui.Tag: {item}")
            raise ValueError("content must be a list of ui.Tag")

    if value is not MISSING and not isinstance(value, str):
        logger.error(f"value must be a string: {value}")
        raise ValueError("value must be a string")

    if icon is not None and not isinstance(icon, ui.Tag):
        logger.error(f"icon must be a ui.Tag: {icon}")
        raise ValueError("icon must be a ui.Tag")

    return ui.accordion_panel(title, *content, value=value, icon=icon, **kwargs)
