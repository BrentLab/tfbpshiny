import pandas as pd

from tfbpshiny.utils.apply_column_names import apply_column_names


class TestApplyColumnNames:
    """Test cases for the apply_column_names utility function."""

    def test_basic_column_renaming(self):
        """Test basic column renaming from metadata."""
        # Create test dataframe
        df = pd.DataFrame(
            {
                "binding_source": ["source1", "source2"],
                "dto_fdr": [0.01, 0.05],
                "rank_25": [0.8, 0.6],
            }
        )

        # Create test metadata
        metadata = {
            "binding_source": ("Binding Source", "Source of binding data"),
            "dto_fdr": ("DTO FDR", "False discovery rate"),
            "rank_25": ("Rank at 25", "Responsive fraction"),
        }

        # Apply column names
        result = apply_column_names(df, metadata)

        # Verify column names are renamed
        expected_columns = ["Binding Source", "DTO FDR", "Rank at 25"]
        assert list(result.columns) == expected_columns

        # Verify data is preserved
        assert len(result) == 2
        assert result["Binding Source"].tolist() == ["source1", "source2"]

    def test_promotersetsig_renaming_default(self):
        """Test that promotersetsig is renamed with default name."""
        # Create test dataframe with promotersetsig
        df = pd.DataFrame(
            {
                "promotersetsig": ["sig1", "sig2"],
                "binding_source": ["source1", "source2"],
            }
        )

        metadata = {"binding_source": ("Binding Source", "Source of binding data")}

        result = apply_column_names(df, metadata)

        # Verify promotersetsig is renamed to default
        assert "id" in result.columns
        assert "promotersetsig" not in result.columns
        assert result["id"].tolist() == ["sig1", "sig2"]

    def test_promotersetsig_renaming_custom(self):
        """Test that promotersetsig is renamed with custom name."""
        df = pd.DataFrame(
            {
                "promotersetsig": ["sig1", "sig2"],
                "binding_source": ["source1", "source2"],
            }
        )

        metadata = {"binding_source": ("Binding Source", "Source of binding data")}

        custom_name = "Custom Signature"
        result = apply_column_names(df, metadata, promotersetsig_name=custom_name)

        # Verify promotersetsig is renamed to custom name
        assert custom_name in result.columns
        assert "promotersetsig" not in result.columns
        assert result[custom_name].tolist() == ["sig1", "sig2"]

    def test_no_promotersetsig_column(self):
        """Test behavior when promotersetsig column is not present."""
        df = pd.DataFrame(
            {"binding_source": ["source1", "source2"], "dto_fdr": [0.01, 0.05]}
        )

        metadata = {
            "binding_source": ("Binding Source", "Source of binding data"),
            "dto_fdr": ("DTO FDR", "False discovery rate"),
        }

        result = apply_column_names(df, metadata)

        # Verify no promotersetsig-related columns are added
        assert "id" not in result.columns
        assert "promotersetsig" not in result.columns
        assert list(result.columns) == ["Binding Source", "DTO FDR"]

    def test_partial_metadata_coverage(self):
        """Test when metadata doesn't cover all columns."""
        df = pd.DataFrame(
            {
                "promotersetsig": ["sig1", "sig2"],
                "binding_source": ["source1", "source2"],
                "unknown_column": ["val1", "val2"],
                "dto_fdr": [0.01, 0.05],
            }
        )

        # Metadata only covers some columns
        metadata = {
            "binding_source": ("Binding Source", "Source of binding data"),
            "dto_fdr": ("DTO FDR", "False discovery rate"),
            # Note: unknown_column is not in metadata
        }

        result = apply_column_names(df, metadata)

        # Verify mixed renaming
        expected_columns = ["id", "Binding Source", "unknown_column", "DTO FDR"]
        assert list(result.columns) == expected_columns

        # Verify unknown_column remains unchanged
        assert result["unknown_column"].tolist() == ["val1", "val2"]

    def test_empty_dataframe(self):
        """Test behavior with empty dataframe."""
        df = pd.DataFrame()
        metadata = {"binding_source": ("Binding Source", "Source of binding data")}

        result = apply_column_names(df, metadata)

        # Should return empty dataframe
        assert len(result) == 0
        assert len(result.columns) == 0

    def test_empty_metadata(self):
        """Test behavior with empty metadata dictionary."""
        df = pd.DataFrame(
            {
                "promotersetsig": ["sig1", "sig2"],
                "binding_source": ["source1", "source2"],
            }
        )

        metadata: dict = {}
        result = apply_column_names(df, metadata)

        # Only promotersetsig should be renamed
        expected_columns = ["id", "binding_source"]
        assert list(result.columns) == expected_columns

    def test_dataframe_copy_not_modified(self):
        """Test that original dataframe is not modified."""
        df = pd.DataFrame(
            {
                "promotersetsig": ["sig1", "sig2"],
                "binding_source": ["source1", "source2"],
            }
        )

        metadata = {"binding_source": ("Binding Source", "Source of binding data")}

        original_columns = df.columns.tolist()
        result = apply_column_names(df, metadata)

        # Verify original dataframe is unchanged
        assert df.columns.tolist() == original_columns
        assert "promotersetsig" in df.columns
        assert "id" not in df.columns

        # Verify result is different
        assert result.columns.tolist() != original_columns

    def test_duplicate_display_names(self):
        """Test behavior when metadata has duplicate display names."""
        df = pd.DataFrame({"col1": [1, 2], "col2": [3, 4]})

        # Both columns map to same display name (edge case)
        metadata = {
            "col1": ("Same Name", "Description 1"),
            "col2": ("Same Name", "Description 2"),
        }

        # This should work but result in duplicate column names
        result = apply_column_names(df, metadata)

        # pandas.rename handles duplicates by keeping both
        assert "Same Name" in result.columns

    def test_complex_metadata_structure(self):
        """Test with complex metadata similar to real usage."""
        df = pd.DataFrame(
            {
                "promotersetsig": ["sig1", "sig2"],
                "univariate_rsquared": [0.85, 0.92],
                "dto_fdr": [0.001, 0.005],
                "rank_25": [0.8, 0.6],
                "binding_source": ["ChIP", "DamID"],
            }
        )

        # Real metadata structure from the codebase
        metadata = {
            "univariate_rsquared": ("R²", "R² of model perturbed ~ binding."),
            "dto_fdr": ("DTO FDR", "False discovery rate from DTO."),
            "rank_25": ("Rank at 25", "Responsive fraction in top 25 bound genes."),
            "binding_source": ("Binding Source", "Source of the binding data."),
        }

        result = apply_column_names(df, metadata)

        expected_columns = ["id", "R²", "DTO FDR", "Rank at 25", "Binding Source"]
        assert list(result.columns) == expected_columns

        # Verify data integrity
        assert len(result) == 2
        assert result["R²"].tolist() == [0.85, 0.92]

    def test_none_values_in_dataframe(self):
        """Test behavior with None/NaN values in dataframe."""
        df = pd.DataFrame(
            {
                "promotersetsig": ["sig1", None],
                "binding_source": ["source1", "source2"],
                "dto_fdr": [0.01, None],
            }
        )

        metadata = {
            "binding_source": ("Binding Source", "Source of binding data"),
            "dto_fdr": ("DTO FDR", "False discovery rate"),
        }

        result = apply_column_names(df, metadata)

        # Verify None values are preserved
        assert pd.isna(result["id"].iloc[1])
        assert pd.isna(result["DTO FDR"].iloc[1])
        assert result["Binding Source"].tolist() == ["source1", "source2"]

    def test_various_promotersetsig_names(self):
        """Test various custom promotersetsig names."""
        test_names = ["Custom Name", "ID", "Signature_Column", "123_test"]

        for promotersetsig_name in test_names:
            df = pd.DataFrame({"promotersetsig": ["sig1", "sig2"]})

            result = apply_column_names(df, {}, promotersetsig_name=promotersetsig_name)

            assert promotersetsig_name in result.columns
            assert "promotersetsig" not in result.columns
            assert result[promotersetsig_name].tolist() == ["sig1", "sig2"]
