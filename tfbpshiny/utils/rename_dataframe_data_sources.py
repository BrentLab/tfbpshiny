import pandas as pd

from .source_name_lookup import get_source_name_dict


def rename_dataframe_data_sources(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rename the data sources in the DataFrame.

    :param df: A dataframe that has the columns "binding_source" and/or
        "expression_source" that need to be renamed.
    :return: A copy of the dataframe with the data sources renamed.

    """
    df_copy = df.copy()
    # Map binding sources to display names
    if "binding_source" in df_copy.columns:
        source_name_dict = get_source_name_dict("binding")
        df_copy["binding_source"] = df_copy["binding_source"].map(
            lambda x: source_name_dict.get(x, x)
        )

    # Map expression sources to display names
    if "expression_source" in df_copy.columns:
        source_name_dict = get_source_name_dict("perturbation_response")
        df_copy["expression_source"] = df_copy["expression_source"].map(
            lambda x: source_name_dict.get(x, x)
        )

    return df_copy
