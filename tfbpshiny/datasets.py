"""
Per-dataset facts shared by the materializer and the app.

Pure constants, no imports from the rest of the package, so both ``materialize/`` and
``modules/`` can depend on it without a cycle. Everything here used to be declared in
two to four places under a "modules stay self-contained" convention; a value that the
build writes and the app reads back has to be the same object on both sides, so it is
declared once.

What stays elsewhere: app policy such as ``DEFAULT_DATASET_FILTERS`` and the preset
threshold tables (``utils/vdb_init.py``), and per-figure dataset orderings
(``modules/figures/queries.py``), which are presentation choices rather than facts about
the data.

"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Measurement columns
# ---------------------------------------------------------------------------

#: Binding dataset -> (score column, p-value column). An empty string means the
#: dataset has no such column. Used for the correlation table; the top-N ranking
#: columns live in ``materialize/comparison/topn.py::BINDING_TOPN_CONFIGS`` because they
#: carry per-dataset ranking rules (direction, blacklist, dedup) as well.
BINDING_DATASET_COLUMNS: dict[str, tuple[str, str]] = {
    "callingcards_kang": ("callingcards_enrichment", "poisson_pval"),
    "callingcards_mindel": ("callingcards_enrichment", "poisson_pval"),
    "callingcards_500bp": ("callingcards_enrichment", "poisson_pval"),
    "callingcards_intergenic": ("callingcards_enrichment", "poisson_pval"),
    "harbison": ("effect", "pvalue"),
    "rossi": ("enrichment", "poisson_pval"),
    "rossi_mindel": ("enrichment", "poisson_pval"),
    "rossi_500bp": ("enrichment", "poisson_pval"),
    "rossi_intergenic": ("enrichment", "poisson_pval"),
    "chec_m2025": ("enrichment", "poisson_pval"),
    "chec_m2025_mindel": ("enrichment", "poisson_pval"),
    "chec_m2025_500bp": ("enrichment", "poisson_pval"),
    "chec_m2025_intergenic": ("enrichment", "poisson_pval"),
}

#: Perturbation dataset -> (effect column, p-value column) that define *responsive*.
#: An empty string means the dataset publishes no p-value, so only the effect
#: threshold applies. These are the columns ``topn_results`` was scored on and the
#: ones the responsiveness-preset labels name.
#:
#: degron uses ``padj`` (DESeq2 adjusted p-value). hackett keeps
#: ``log2_shrunken_timecourses``: that is the column the authors call a response, even
#: though it is 95% exactly zero (see :data:`PERTURBATION_CORRELATION_COLUMNS`).
PERTURBATION_DATASET_COLUMNS: dict[str, tuple[str, str]] = {
    "degron": ("log2FoldChange", "padj"),
    "hughes_overexpression": ("mean_norm_log2fc", ""),
    "hughes_knockout": ("mean_norm_log2fc", ""),
    "kemmeren": ("Madj", "pval"),
    "hackett": ("log2_shrunken_timecourses", ""),
    "hu_reimand": ("effect", "pval"),
}

#: Perturbation columns used where a *ranking* or a *correlation* is wanted rather than
#: a responsiveness call: the ``correlations`` table and the agreement / target-set
#: rankings. Identical to :data:`PERTURBATION_DATASET_COLUMNS` except for hackett,
#: which ranks on ``log2_cleaned_ratio`` because correlating or ranking on a column
#: that is 95% exactly zero is close to meaningless.
PERTURBATION_CORRELATION_COLUMNS: dict[str, tuple[str, str]] = {
    **PERTURBATION_DATASET_COLUMNS,
    "hackett": ("log2_cleaned_ratio", ""),
}

# ---------------------------------------------------------------------------
# Promoter sets and binding methods
# ---------------------------------------------------------------------------

#: Promoter sets that define a fixed, re-quantifiable upstream window, in display
#: order. ``'peaks'`` (the original authors' peak calls, no fixed window) and
#: ``'array'`` (Harbison's microarray probes) exist in the ``promoter_sets`` table but
#: are deliberately not levels: they cannot be compared across methods.
PROMOTER_SET_LEVELS: tuple[str, ...] = ("kang", "mindel", "500bp", "intergenic")

#: The two binding methods, in display order, matching
#: ``binding_methods.binding_method_id``.
METHOD_LEVELS: tuple[str, ...] = ("promoter_enrichment", "peak_calling")

# ---------------------------------------------------------------------------
# Top-N analysis
# ---------------------------------------------------------------------------

#: Sentinel ``top_n`` meaning "every bound target, no rank cutoff". Rows at this value
#: hold the authors' own binding call (peak datasets) or the named p-value threshold
#: (Harbison, Calling Cards) used by the authors'-threshold figure.
TOP_N_ALL = 0

#: Rank cutoffs materialized into ``topn_results``. The UI selectors offer exactly
#: these, so the build and the app cannot drift apart.
TOP_N_CHOICES: tuple[int, ...] = (10, 25, 50, 75, 100)

#: Cutoff pre-selected in the UI. Must be a member of :data:`TOP_N_CHOICES`.
DEFAULT_TOP_N = 25

assert DEFAULT_TOP_N in TOP_N_CHOICES

#: Names of the responsiveness presets, in the order the UI lists them. The threshold
#: tables themselves are ``utils.vdb_init.DEFAULT_RESPONSIVENESS_PRESETS``; the build
#: materializes a ``topn_results`` row for every pair a preset resolves to.
PRESET_NAMES: tuple[str, ...] = ("Relaxed", "Stringent")

#: Preset pre-selected in the Comparison module. Must be a member of
#: :data:`PRESET_NAMES`.
DEFAULT_PRESET = "Relaxed"

assert DEFAULT_PRESET in PRESET_NAMES

# ---------------------------------------------------------------------------
# Agreement and DTO
# ---------------------------------------------------------------------------

#: Yeast gene universe for the random-overlap expectation of two top-N sets,
#: ``(N / GENE_UNIVERSE) * N``. Applied at query time, so it can be revisited without
#: a rebuild.
GENE_UNIVERSE = 6000

#: Empirical DTO p-value below which a regulator counts as DTO-significant.
DTO_PVALUE_THRESHOLD = 0.01

__all__ = [
    "BINDING_DATASET_COLUMNS",
    "PERTURBATION_DATASET_COLUMNS",
    "PERTURBATION_CORRELATION_COLUMNS",
    "PROMOTER_SET_LEVELS",
    "METHOD_LEVELS",
    "TOP_N_ALL",
    "TOP_N_CHOICES",
    "DEFAULT_TOP_N",
    "PRESET_NAMES",
    "DEFAULT_PRESET",
    "GENE_UNIVERSE",
    "DTO_PVALUE_THRESHOLD",
]
