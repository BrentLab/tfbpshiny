# Changelog

All notable changes to this project will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-06-12

### Added

- Initial public release of TFBPShiny.
- Dashboard interface for exploring transcription factor binding and perturbation
  data from the Brent Lab yeast collection.
- Dataset Selection module with filter controls for binding and perturbation datasets.
- Binding module with correlation and scatter visualizations.
- Perturbation module with correlation and scatter visualizations.
- Comparison module with three subtabs: Compare Datasets (binding vs. perturbation
  matrix), Compare Promoter Definitions (enrichment scores across four promoter sets:
  Kang, Mindel, 500bp, Intergenic), and Compare Analysis Methods (promoter enrichment
  vs. original peaks for ChIP-exo and ChEC-seq datasets).
- `python -m tfbpshiny launch` CLI entry point: downloads the HuggingFace dataset
  cache on first run and serves the app on subsequent runs from the same directory.
  Supports `--cache-dir`, `--skip-initialize`, `--no-materialize`, `--port`, `--host`,
  and `--debug` flags.
- Projected in-memory materialization of dataset views at startup for improved query
  performance; disabled via `--no-materialize` or `TFBPSHINY_MATERIALIZE=0`.
- Docker Compose production stack with Traefik reverse proxy and AWS CloudWatch
  logging.
- shinyapps.io deployment support via `shinyapps_entry.py`.
- Terraform configuration for EC2 provisioning.
