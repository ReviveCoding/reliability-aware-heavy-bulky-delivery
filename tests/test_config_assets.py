from __future__ import annotations

import copy
from importlib import resources
from pathlib import Path

import pytest
from pydantic import ValidationError

from heavy_bulky import __version__
from heavy_bulky.config import load_config, validate_config

ROOT = Path(__file__).resolve().parents[1]


def test_root_configs_validate():
    for name in ["smoke.yaml", "full.yaml", "full_advanced.yaml", "m5_small.yaml"]:
        cfg = load_config(ROOT / "configs" / name)
        assert cfg["seed"] > 0
        assert cfg["forecast"]["quantiles"] == [0.1, 0.5, 0.9]


def test_unknown_nested_config_is_rejected(smoke_config):
    bad = dict(smoke_config)
    bad["forecast"] = {**bad["forecast"], "typo_field": 1}
    with pytest.raises(ValidationError):
        validate_config(bad)


def test_environment_paths_expand(smoke_config, monkeypatch):
    monkeypatch.setenv("HB_TMP", "/tmp/hb-config-test")
    raw = {**smoke_config, "output_dir": "$HB_TMP/results"}
    assert validate_config(raw)["output_dir"] == "/tmp/hb-config-test/results"


def test_packaged_config_and_sql_resources_exist():
    package = resources.files("heavy_bulky")
    assert package.joinpath("configs/smoke.yaml").is_file()
    assert package.joinpath("configs/full.yaml").is_file()
    assert package.joinpath("sql/01_daily_station_service_demand.sql").is_file()


def test_version_consistency():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{__version__}"' in pyproject
    assert __version__ == "0.4.3"


def test_release_automation_assets_are_current_and_cross_platform():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "actions/checkout@v6" in workflow
    assert "actions/setup-python@v6" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "windows-latest" in workflow
    assert "timeout-minutes:" in workflow
    assert "if-no-files-found: error" in workflow
    bash_runner = (ROOT / "scripts/run_full_validation.sh").read_text(encoding="utf-8")
    powershell_runner = (ROOT / "scripts/run_full_validation.ps1").read_text(encoding="utf-8")
    assert "validation_smoke_repeat" in bash_runner
    assert "--sdist-smoke-output" in bash_runner
    assert "validation_smoke_repeat" in powershell_runner
    assert "--sdist-smoke-output" in powershell_runner
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD" in bash_runner
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD" in powershell_runner


def test_container_and_public_data_make_targets_are_declared():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "USER app" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "download-amazon-routes:" in makefile
    assert "prepare-amazon-route-marts:" in makefile
    assert '--user "$$(id -u):$$(id -g)"' in makefile


def test_root_and_packaged_sql_are_identical():
    root = Path(__file__).resolve().parents[1]
    package = resources.files("heavy_bulky")
    for sql_path in sorted((root / "sql").glob("*.sql")):
        packaged = package.joinpath("sql", sql_path.name)
        assert packaged.is_file()
        assert sql_path.read_text(encoding="utf-8") == packaged.read_text(encoding="utf-8")


def test_hard_timeout_covers_station_decomposition(smoke_config):
    invalid = copy.deepcopy(smoke_config)
    invalid["stations"] = ["A", "B", "C", "D"]
    invalid["optimization"]["time_limit_seconds"] = 2
    invalid["optimization"]["hard_timeout_seconds"] = 8
    with pytest.raises(ValueError, match="station-decomposed"):
        validate_config(invalid)


def test_root_and_packaged_configs_are_identical():
    package = resources.files("heavy_bulky")
    for config_path in sorted((ROOT / "configs").glob("*.yaml")):
        packaged = package.joinpath("configs", config_path.name)
        assert packaged.is_file()
        assert config_path.read_text(encoding="utf-8") == packaged.read_text(encoding="utf-8")


def test_build_backend_is_pinned_for_sdist_validation():
    constraints = (ROOT / "constraints-verified.txt").read_text(encoding="utf-8")
    dev_requirements = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "setuptools==82.0.1" in constraints
    assert "setuptools" in dev_requirements.splitlines()


def test_validation_module_is_importable():
    from scripts.full_pipeline_validation import artifact_integrity

    assert callable(artifact_integrity)


def test_real_api_runtime_smoke_asset_is_declared():
    script = ROOT / "scripts/api_runtime_smoke.py"
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    shell_runner = (ROOT / "scripts/run_full_validation.sh").read_text(encoding="utf-8")
    powershell_runner = (ROOT / "scripts/run_full_validation.ps1").read_text(encoding="utf-8")
    assert script.is_file()
    assert "api_runtime_smoke.json" in workflow
    assert "api_runtime_smoke.py" in shell_runner
    assert "api_runtime_smoke.py" in powershell_runner


def test_distribution_smoke_installs_full_runtime_extras():
    bash_runner = (ROOT / "scripts/run_full_validation.sh").read_text(encoding="utf-8")
    powershell_runner = (ROOT / "scripts/run_full_validation.ps1").read_text(encoding="utf-8")
    assert "${WHEEL}[full]" in bash_runner
    assert "${SDIST}[full]" in bash_runner
    assert "--no-deps --target '$WHEEL_TARGET' '$WHEEL'" not in bash_runner
    assert "--no-deps --no-build-isolation --target '$SDIST_TARGET' '$SDIST'" not in bash_runner
    assert '$Wheel.FullName + "[full]"' in powershell_runner
    assert '$Sdist.FullName + "[full]"' in powershell_runner
