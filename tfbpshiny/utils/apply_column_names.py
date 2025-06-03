import pandas as pd


def apply_column_names(
    df: pd.DataFrame,
    metadata_dict: dict,
    promotersetsig_name: str = "Promoter Set Signature",
) -> pd.DataFrame:
    """
    Apply friendly column names from metadata to dataframe columns.

    :param df: The dataframe to rename columns for
    :param metadata_dict: Dictionary mapping column keys to (display_name, description)
        tuples
    :param promotersetsig_name: The name to use for the promotersetsig column
    :return: A copy of the dataframe with renamed columns

    """
    df_copy = df.copy()
    column_mapping = {}

    # Add promotersetsig mapping (rename from original to friendly name)
    if "promotersetsig" in df_copy.columns:
        column_mapping["promotersetsig"] = promotersetsig_name

    # Add mappings from metadata
    for col in df_copy.columns:
        if col in metadata_dict:
            display_name, _ = metadata_dict[col]
            column_mapping[col] = display_name

    # Rename columns using the mapping
    df_renamed = df_copy.rename(columns=column_mapping)
    return df_renamed
