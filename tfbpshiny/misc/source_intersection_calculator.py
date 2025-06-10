from logging import Logger
from typing import Literal

import pandas as pd
from shiny import reactive

from ..utils.source_name_lookup import get_source_name_dict


def calculate_regulators_by_source(
    metadata: pd.DataFrame,
    selected_internal_names: list[str],
    datatype: Literal["binding", "perturbation_response"],
    logger: Logger,
) -> dict[str, set[str]]:
    """
    Calculate regulators grouped by source name for the selected sources.

    :param metadata: DataFrame containing metadata with 'source_name' and
        'regulator_symbol' columns.
    :param selected_internal_names: List of selected internal source names (from UI)
    :param datatype: Either "binding" or "perturbation_response"
    :param logger: Logger instance
    :return: Dictionary mapping display source names to sets of regulator symbols

    """
    if not selected_internal_names:
        return {}

    source_name_dict = get_source_name_dict(datatype)

    df_filtered = metadata[metadata["source_name"].isin(selected_internal_names)]

    if df_filtered.empty:
        logger.warning(
            f"No data available for internal sources: {selected_internal_names}"
        )
        return {}

    # Group by source_name and get lists of regulators
    grouped = (
        df_filtered.groupby("source_name")["regulator_symbol"].apply(list).to_dict()
    )

    # Convert to display names and sets
    result = {}
    for internal_name, regulator_list in grouped.items():
        display_name = source_name_dict.get(internal_name, internal_name)
        regulator_set = set(regulator_list)
        result[display_name] = regulator_set

    return result


def create_intersection_summary(
    regulators_dict: dict[str, set[str]],
    selected_internal_names: list[str],
    datatype: Literal["binding", "perturbation_response"],
    logger: Logger,
) -> dict:
    """
    Create intersection summary for the given sources.

    :param regulators_dict: Dictionary mapping display source names to regulator sets
    :param selected_internal_names: List of selected internal source names (from UI)
    :param datatype: Either "binding" or "perturbation_response"
    :param logger: Logger instance
    :return: Dictionary containing summary information

    """
    if not selected_internal_names:
        return {"type": "empty"}

    source_name_dict = get_source_name_dict(datatype)
    selected_display_names = [
        source_name_dict.get(name, name) for name in selected_internal_names
    ]

    if len(selected_display_names) > 3:
        selected_display_names = selected_display_names[:3]

    if len(selected_display_names) == 1:
        source = selected_display_names[0]
        count = len(regulators_dict.get(source, set()))
        return {"type": "single", "source": source, "count": count}

    elif len(selected_display_names) == 2:
        source1, source2 = selected_display_names
        set1 = regulators_dict.get(source1, set())
        set2 = regulators_dict.get(source2, set())
        intersection = set1 & set2

        return {
            "type": "double",
            "sources": [source1, source2],
            "counts": [len(set1), len(set2)],
            "intersection": len(intersection),
        }

    elif len(selected_display_names) == 3:
        source1, source2, source3 = selected_display_names
        set1 = regulators_dict.get(source1, set())
        set2 = regulators_dict.get(source2, set())
        set3 = regulators_dict.get(source3, set())

        # Calculate pairwise intersections
        int_12 = set1 & set2
        int_13 = set1 & set3
        int_23 = set2 & set3
        int_123 = set1 & set2 & set3

        return {
            "type": "triple",
            "sources": [source1, source2, source3],
            "counts": [len(set1), len(set2), len(set3)],
            "pairwise_intersections": [len(int_12), len(int_13), len(int_23)],
            "triple_intersection": len(int_123),
        }

    return {"type": "empty"}


class SourceIntersectionCalculator:
    """A class to handle source intersection calculations for both binding and
    perturbation response data."""

    def __init__(
        self,
        datatype: Literal["binding", "perturbation_response"],
        logger: Logger,
    ):
        """
        Initialize the calculator.

        :param datatype: Either "binding" or "perturbation_response"
        :param logger: Logger instance

        """
        self.datatype = datatype
        self.logger = logger

    def get_filtered_metadata(
        self, metadata_task: reactive.ExtendedTask, selected_internal_names: list[str]
    ) -> pd.DataFrame:
        """
        Get metadata filtered by selected sources.

        :param metadata_task: Reactive extended task containing metadata
        :param selected_internal_names: List of selected internal source names (from UI)
        :return: Filtered DataFrame

        """
        metadata = metadata_task.result()
        if not selected_internal_names:
            return pd.DataFrame()

        return metadata[metadata["source_name"].isin(selected_internal_names)]

    def calculate_regulators_by_source(
        self, metadata_task: reactive.ExtendedTask, selected_internal_names: list[str]
    ) -> dict[str, set[str]]:
        """
        Calculate regulators grouped by source.

        :param metadata_task: Reactive extended task containing metadata
        :param selected_internal_names: List of selected internal source names (from UI)
        :return: Dictionary mapping display names to regulator sets

        """
        metadata = metadata_task.result()
        return calculate_regulators_by_source(
            metadata, selected_internal_names, self.datatype, self.logger
        )

    def create_summary(
        self, metadata_task: reactive.ExtendedTask, selected_internal_names: list[str]
    ) -> dict:
        """
        Create a complete intersection summary.

        :param metadata_task: Reactive extended task containing metadata
        :param selected_internal_names: List of selected internal source names (from UI)
        :return: Summary dictionary

        """
        regulators_dict = self.calculate_regulators_by_source(
            metadata_task, selected_internal_names
        )
        return create_intersection_summary(
            regulators_dict, selected_internal_names, self.datatype, self.logger
        )
