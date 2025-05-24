from typing import TypedDict


class AccordionItemConfig(TypedDict):
    panel_title: str
    checkbox_id: str
    checkbox_label: str
    choices: dict[str, str]
    selected: list[str]
