from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import __version__
from .assets import package_config_path
from .integrity import validate_published_run
from .pipeline import run_pipeline

OUTPUT_ROOT = Path(os.environ.get("HEAVY_BULKY_OUTPUT_ROOT", Path.cwd())).resolve()
ALLOWED_CONFIGS = {"smoke": package_config_path("smoke"), "full": package_config_path("full")}

app = FastAPI(title="Heavy-Bulky Delivery Reliability API", version=__version__)


class PipelineRequest(BaseModel):
    mode: Literal["smoke", "full"] = "smoke"




def _validate_windows_output_path_budget(
    destination,
    *,
    is_windows: bool | None = None,
) -> None:
    """Reject API output roots that cannot safely host staged atomic writes."""

    windows = os.name == "nt" if is_windows is None else is_windows

    if not windows:
        return

    projected_atomic_path = (
        destination
        / (".smoke.staging-" + ("x" * 32))
        / "planning"
        / (
            ".label_informed_proxy_plan_meta.json."
            + ("x" * 24)
            + ".tmp"
        )
    )

    projected_length = len(str(projected_atomic_path))
    conservative_limit = 240

    if projected_length > conservative_limit:
        raise HTTPException(
            status_code=422,
            detail=(
                "API output root is too deep for reliable Windows staged "
                "atomic writes. Use a shorter HEAVY_BULKY_OUTPUT_ROOT. "
                f"Projected path length={projected_length}; "
                f"conservative limit={conservative_limit}."
            ),
        )

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "heavy-bulky-delivery-reliability", "version": __version__}


@app.get("/ready")
def ready() -> dict[str, str]:
    missing = [name for name, path in ALLOWED_CONFIGS.items() if not path.exists()]
    if missing:
        raise HTTPException(status_code=503, detail=f"missing packaged configs: {missing}")
    try:
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=OUTPUT_ROOT, prefix=".readiness-", suffix=".tmp"
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(b"ready\n")
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).unlink(missing_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"output root is not writable: {exc}") from exc
    return {
        "status": "ready",
        "service": "heavy-bulky-delivery-reliability",
        "version": __version__,
    }


@app.post("/run")
def run(request: PipelineRequest) -> dict:
    config_path = ALLOWED_CONFIGS[request.mode]
    if not config_path.exists():
        raise HTTPException(status_code=500, detail="configured pipeline file is missing")
    destination = OUTPUT_ROOT / "outputs" / request.mode
    try:
        _validate_windows_output_path_budget(destination)
        return run_pipeline(str(config_path), output_dir_override=destination)
    except RuntimeError as exc:
        if "already publishing" in str(exc):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise


@app.get("/latest/{mode}")
def latest(mode: Literal["smoke", "full"]) -> dict:
    output = OUTPUT_ROOT / "outputs" / mode
    if not output.exists():
        raise HTTPException(status_code=404, detail="run not found")
    problems = validate_published_run(output)
    if problems:
        raise HTTPException(
            status_code=503, detail={"message": "run integrity failure", "problems": problems}
        )
    try:
        return json.loads((output / "metrics/summary.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=503, detail=f"summary is unreadable: {type(exc).__name__}"
        ) from exc
