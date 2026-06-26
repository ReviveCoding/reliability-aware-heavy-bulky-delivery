# Local and GitHub Runnability

## Locally executed and passed

- clean Python 3.13.5 environment with exact direct versions
- dependency integrity, formatting, lint, and compilation
- 66 tests with 74.47% coverage
- source smoke twice and source full
- real two-worker Uvicorn API concurrency smoke
- wheel and sdist repeated builds
- isolated wheel and sdist installation and end-to-end smoke
- CLI verification for source, wheel, and sdist outputs
- artifact integrity and decision-fingerprint reproducibility
- M5-pattern small run
- CPU PyTorch advanced-service challenger
- Python 3.11 Linux/Windows direct-wheel availability

## GitHub paths defined

- Ubuntu Python 3.11 and 3.13 quality matrix
- Windows Python 3.11 test and smoke job
- Ubuntu end-to-end source/distribution/API validation job
- Docker build and non-root container smoke job
- required artifact upload with failure on missing files

## Not executed in this environment

- remote GitHub-hosted workflow
- Docker image/container execution because no Docker daemon was available
- CUDA execution
- Chronos-2 download and inference
- full Amazon Last Mile public-route calibration

The repository is locally validated and GitHub-ready, while infrastructure-specific paths remain explicitly unclaimed until executed.
