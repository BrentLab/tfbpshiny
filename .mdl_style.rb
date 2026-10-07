# markdownlint (mdl) style for this repository.
#
# CHANGELOG.md follows Keep a Changelog, where the same "### Added" / "### Changed" /
# "### Fixed" heading legitimately repeats under every release. MD024 would flag every
# repeat; allowing duplicates under different parent headings keeps the rule for real
# duplicates (two identical headings in the same section).
all
rule 'MD024', :allow_different_nesting => true
