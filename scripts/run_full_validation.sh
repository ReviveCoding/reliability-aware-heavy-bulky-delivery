#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-python}"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONHASHSEED=0
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-315532800}"
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export TOKENIZERS_PARALLELISM=false
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

mkdir -p reports artifacts/dist artifacts/repeat outputs

TIMEOUT_BIN=""
if command -v timeout >/dev/null 2>&1; then
  TIMEOUT_BIN="timeout"
elif command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_BIN="gtimeout"
else
  echo "[validation] warning: GNU timeout not found; relying on internal solver timeouts" >&2
fi

run_bounded() {
  local seconds="$1"
  shift
  if [[ -n "$TIMEOUT_BIN" ]]; then
    "$TIMEOUT_BIN" --signal=TERM --kill-after=10 "$seconds" "$@"
  else
    "$@"
  fi
}

run_step() {
  local seconds="$1"
  local label="$2"
  shift 2
  printf '\n[validation] %s\n' "$label"
  run_bounded "$seconds" "$@"
}

run_capture() {
  local seconds="$1"
  local label="$2"
  local output_file="$3"
  shift 3
  printf '\n[validation] %s\n' "$label"
  set +e
  run_bounded "$seconds" "$@" >"$output_file"
  local status=$?
  set -e
  if [[ "$status" -ne 0 ]]; then
    echo "[validation] failed: $label (status=$status)" >&2
    return "$status"
  fi
}

run_capture 60 "capability inventory" reports/capabilities.json \
  "$PYTHON" -m heavy_bulky.cli capabilities
run_step 60 "direct dependency versions" "$PYTHON" scripts/check_direct_dependencies.py
run_step 120 "environment dependency integrity" "$PYTHON" -m pip check
run_step 120 "format check" "$PYTHON" -m ruff format --check src scripts tests
run_step 120 "lint check" "$PYTHON" -m ruff check src scripts tests
run_step 120 "source compilation" "$PYTHON" -m compileall -q src scripts tests
for config in smoke full full_advanced m5_small; do
  run_capture 60 "$config config validation" /dev/null \
    "$PYTHON" -m heavy_bulky.cli validate-config --config "configs/$config.yaml"
done
run_step 300 "automated tests with coverage" \
  "$PYTHON" -m pytest -p pytest_cov --cov=heavy_bulky --cov-report=term-missing \
  --cov-report=json:reports/coverage.json

rm -rf \
  outputs/validation_smoke \
  outputs/validation_smoke_repeat \
  outputs/validation_full \
  outputs/validation_wheel_smoke \
  outputs/validation_sdist_smoke
run_capture 180 "source smoke pipeline" reports/smoke_console.json \
  "$PYTHON" -u -m heavy_bulky.cli full-pipeline \
  --config configs/smoke.yaml --output-dir outputs/validation_smoke
run_capture 180 "repeated source smoke pipeline" reports/smoke_repeat_console.json \
  "$PYTHON" -u -m heavy_bulky.cli full-pipeline \
  --config configs/smoke.yaml --output-dir outputs/validation_smoke_repeat
run_capture 360 "source full pipeline" reports/full_console.json \
  "$PYTHON" -u -m heavy_bulky.cli full-pipeline \
  --config configs/full.yaml --output-dir outputs/validation_full
run_capture 60 "verify source smoke output" /dev/null \
  "$PYTHON" -m heavy_bulky.cli verify-output --output-dir outputs/validation_smoke
run_capture 60 "verify repeated smoke output" /dev/null \
  "$PYTHON" -m heavy_bulky.cli verify-output --output-dir outputs/validation_smoke_repeat
run_capture 120 "verify source full output" /dev/null \
  "$PYTHON" -m heavy_bulky.cli verify-output --output-dir outputs/validation_full
rm -rf outputs/api-runtime-smoke
run_step 240 "real two-worker API concurrency smoke" \
  "$PYTHON" scripts/api_runtime_smoke.py \
  --output-root outputs/api-runtime-smoke-root \
  --report reports/api_runtime_smoke.json --workers 2

rm -rf artifacts/dist artifacts/repeat build src/*.egg-info
mkdir -p artifacts/dist artifacts/repeat
run_step 240 "wheel and sdist build" env SOURCE_DATE_EPOCH="$SOURCE_DATE_EPOCH" \
  "$PYTHON" -m build --wheel --sdist --outdir artifacts/dist
rm -rf build src/*.egg-info
run_step 240 "repeat wheel and sdist build" env SOURCE_DATE_EPOCH="$SOURCE_DATE_EPOCH" \
  "$PYTHON" -m build --wheel --sdist --outdir artifacts/repeat

WHEEL="$(find artifacts/dist -maxdepth 1 -name '*.whl' -print -quit)"
WHEEL_REPEAT="$(find artifacts/repeat -maxdepth 1 -name '*.whl' -print -quit)"
SDIST="$(find artifacts/dist -maxdepth 1 -name '*.tar.gz' -print -quit)"
SDIST_REPEAT="$(find artifacts/repeat -maxdepth 1 -name '*.tar.gz' -print -quit)"
for artifact in "$WHEEL" "$WHEEL_REPEAT" "$SDIST" "$SDIST_REPEAT"; do
  if [[ -z "$artifact" || ! -f "$artifact" ]]; then
    echo "distribution not created: $artifact" >&2
    exit 1
  fi
done

TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT
WHEEL_TARGET="$TMP_ROOT/wheel-site"
SDIST_TARGET="$TMP_ROOT/sdist-site"
run_capture 300 "isolated wheel installation with full runtime extras" /dev/null \
  "$PYTHON" -m pip install --constraint "$ROOT/constraints-verified.txt" \
  --target "$WHEEL_TARGET" "${WHEEL}[full]"
run_capture 420 "isolated sdist installation with full runtime extras" /dev/null \
  "$PYTHON" -m pip install --constraint "$ROOT/constraints-verified.txt" \
  --target "$SDIST_TARGET" "${SDIST}[full]"

RESOURCE_CHECK="import heavy_bulky; from importlib import resources; p=resources.files('heavy_bulky'); assert all(p.joinpath('configs', n).is_file() for n in ['smoke.yaml','full.yaml','full_advanced.yaml','m5_small.yaml']); assert all(p.joinpath('sql', n).is_file() for n in ['01_daily_station_service_demand.sql','02_plan_vs_actual.sql','03_monitoring_daily.sql']); print(heavy_bulky.__version__)"
(
  cd "$TMP_ROOT"
  run_step 60 "isolated wheel import and resources" env PYTHONPATH="$WHEEL_TARGET" \
    "$PYTHON" -c "$RESOURCE_CHECK"
  run_capture 180 "wheel-based smoke pipeline" "$ROOT/reports/wheel_smoke_console.json" \
    env PYTHONPATH="$WHEEL_TARGET" "$PYTHON" -u -m heavy_bulky.cli full-pipeline \
    --config "$ROOT/configs/smoke.yaml" --output-dir "$ROOT/outputs/validation_wheel_smoke"
  run_capture 60 "verify wheel-based smoke output" /dev/null \
    env PYTHONPATH="$WHEEL_TARGET" "$PYTHON" -m heavy_bulky.cli verify-output \
    --output-dir "$ROOT/outputs/validation_wheel_smoke"
  run_step 60 "isolated sdist import and resources" env PYTHONPATH="$SDIST_TARGET" \
    "$PYTHON" -c "$RESOURCE_CHECK"
  run_capture 180 "sdist-based smoke pipeline" "$ROOT/reports/sdist_smoke_console.json" \
    env PYTHONPATH="$SDIST_TARGET" "$PYTHON" -u -m heavy_bulky.cli full-pipeline \
    --config "$ROOT/configs/smoke.yaml" --output-dir "$ROOT/outputs/validation_sdist_smoke"
  run_capture 60 "verify sdist-based smoke output" /dev/null \
    env PYTHONPATH="$SDIST_TARGET" "$PYTHON" -m heavy_bulky.cli verify-output \
    --output-dir "$ROOT/outputs/validation_sdist_smoke"
)

run_step 180 "artifact, determinism, and distribution verification" \
  "$PYTHON" scripts/full_pipeline_validation.py \
  --smoke-output outputs/validation_smoke \
  --repeat-smoke-output outputs/validation_smoke_repeat \
  --full-output outputs/validation_full \
  --wheel "$WHEEL" \
  --wheel-repeat "$WHEEL_REPEAT" \
  --sdist "$SDIST" \
  --sdist-repeat "$SDIST_REPEAT" \
  --wheel-smoke-output outputs/validation_wheel_smoke \
  --sdist-smoke-output outputs/validation_sdist_smoke \
  --api-smoke-report reports/api_runtime_smoke.json
