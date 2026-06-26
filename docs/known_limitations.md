# Known Limitations

## Not release blockers for the current candidate

1. **Remote GitHub-hosted Actions not executed here.** The workflow is present and locally mirrored, but E4 evidence requires pushing the exact candidate to GitHub and observing hosted runners.
2. **Docker daemon not available in this sandbox.** Dockerfile and CI job are present, but image build and container smoke are not claimed as executed.
3. **CUDA path not executed in this re-audit.** The optional neural challenger was previously CPU-validated and remains HOLD. CUDA should be treated as unverified until run on the target RTX environment.
4. **Chronos-2 path remains optional and unverified.** The adapter exists, but model download/inference is not part of the frozen validation evidence.
5. **Amazon Last Mile public route calibration is optional.** The project supports public route-data preparation, but the full public-route calibration was not executed in this re-audit.
6. **Synthetic/proxy evidence only.** M5 is used as a public temporal-pattern source; it is not observed heavy-bulky demand. Default service requirements, crew skills, and actual outcomes are semi-synthetic.
7. **Performance timings are environment-specific.** Re-audit timings were produced on the current Linux sandbox with Python 3.13.5.

## Intentionally not implemented

- New advanced models or GPU training, because the current evidence shows core reliability/operational paths are already stronger than adding unpromoted complexity.
- Production AMXL claims, real-dollar savings, or planner adoption claims.
- Formal privacy, safety, or compliance certification.

## Next qualification gates

- Run the exact candidate on GitHub-hosted Ubuntu and Windows runners.
- Run Docker build and container smoke with a real Docker daemon.
- Run optional CUDA challenger on the user's RTX environment if GPU evidence is needed.
- Run Chronos-2 only if forecasting research value justifies model download and environment expansion.
- Push to GitHub and record exact commit SHA and Actions URLs.


## Base-only package install

The base package can import and expose CLI metadata, but the benchmark's production-style full pipeline requires the `full` extra for LightGBM, OR-Tools, DuckDB, FastAPI, and Uvicorn. Use `.[full]`, `.[full,dev]`, `wheel-file.whl[full]`, or `sdist.tar.gz[full]` for qualification and E2E runs. Base-only E2E behavior is not a release claim.
