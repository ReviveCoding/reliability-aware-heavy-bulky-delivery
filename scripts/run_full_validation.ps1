param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$env:PYTHONHASHSEED = "0"
$env:SOURCE_DATE_EPOCH = "315532800"
$env:OMP_NUM_THREADS = "1"
$env:OPENBLAS_NUM_THREADS = "1"
$env:MKL_NUM_THREADS = "1"
$env:NUMEXPR_NUM_THREADS = "1"
$env:TOKENIZERS_PARALLELISM = "false"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
$SourcePythonPath = Join-Path $Root "src"
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$SourcePythonPath$([IO.Path]::PathSeparator)$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = $SourcePythonPath
}
New-Item -ItemType Directory -Force -Path reports, artifacts/dist, artifacts/repeat, outputs | Out-Null

function Invoke-PythonStep {
    param(
        [string]$Label,
        [string[]]$Arguments,
        [string]$CapturePath = ""
    )
    Write-Host "`n[validation] $Label"
    if ($CapturePath) {
        & $Python @Arguments | Tee-Object -FilePath $CapturePath
    } else {
        & $Python @Arguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Validation step failed: $Label (exit=$LASTEXITCODE)"
    }
}

Invoke-PythonStep "capability inventory" @("-m", "heavy_bulky.cli", "capabilities") "reports/capabilities.json"
Invoke-PythonStep "direct dependency versions" @("scripts/check_direct_dependencies.py")
Invoke-PythonStep "environment dependency integrity" @("-m", "pip", "check")
Invoke-PythonStep "format check" @("-m", "ruff", "format", "--check", "src", "scripts", "tests")
Invoke-PythonStep "lint check" @("-m", "ruff", "check", "src", "scripts", "tests")
Invoke-PythonStep "source compilation" @("-m", "compileall", "-q", "src", "scripts", "tests")
foreach ($Config in @("smoke", "full", "full_advanced", "m5_small")) {
    Invoke-PythonStep "$Config config validation" @("-m", "heavy_bulky.cli", "validate-config", "--config", "configs/$Config.yaml")
}
Invoke-PythonStep "automated tests with coverage" @("-m", "pytest", "-p", "pytest_cov", "--cov=heavy_bulky", "--cov-report=term-missing", "--cov-report=json:reports/coverage.json")

Remove-Item -Recurse -Force -ErrorAction SilentlyContinue `
    outputs/validation_smoke, `
    outputs/validation_smoke_repeat, `
    outputs/validation_full, `
    outputs/validation_wheel_smoke, `
    outputs/validation_sdist_smoke
Invoke-PythonStep "source smoke pipeline" @("-u", "-m", "heavy_bulky.cli", "full-pipeline", "--config", "configs/smoke.yaml", "--output-dir", "outputs/validation_smoke") "reports/smoke_console.json"
Invoke-PythonStep "repeated source smoke pipeline" @("-u", "-m", "heavy_bulky.cli", "full-pipeline", "--config", "configs/smoke.yaml", "--output-dir", "outputs/validation_smoke_repeat") "reports/smoke_repeat_console.json"
Invoke-PythonStep "source full pipeline" @("-u", "-m", "heavy_bulky.cli", "full-pipeline", "--config", "configs/full.yaml", "--output-dir", "outputs/validation_full") "reports/full_console.json"
Invoke-PythonStep "verify source smoke output" @("-m", "heavy_bulky.cli", "verify-output", "--output-dir", "outputs/validation_smoke")
Invoke-PythonStep "verify repeated smoke output" @("-m", "heavy_bulky.cli", "verify-output", "--output-dir", "outputs/validation_smoke_repeat")
Invoke-PythonStep "verify source full output" @("-m", "heavy_bulky.cli", "verify-output", "--output-dir", "outputs/validation_full")
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue outputs/api-runtime-smoke-root
Invoke-PythonStep "real two-worker API concurrency smoke" @("scripts/api_runtime_smoke.py", "--output-root", "outputs/api-runtime-smoke-root", "--report", "reports/api_runtime_smoke.json", "--workers", "2")

Remove-Item -Recurse -Force -ErrorAction SilentlyContinue artifacts/dist, artifacts/repeat, build, src/*.egg-info
New-Item -ItemType Directory -Force -Path artifacts/dist, artifacts/repeat | Out-Null
Invoke-PythonStep "wheel and sdist build" @("-m", "build", "--wheel", "--sdist", "--outdir", "artifacts/dist")
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, src/*.egg-info
Invoke-PythonStep "repeat wheel and sdist build" @("-m", "build", "--wheel", "--sdist", "--outdir", "artifacts/repeat")

$Wheel = Get-ChildItem artifacts/dist/*.whl | Select-Object -First 1
$WheelRepeat = Get-ChildItem artifacts/repeat/*.whl | Select-Object -First 1
$Sdist = Get-ChildItem artifacts/dist/*.tar.gz | Select-Object -First 1
$SdistRepeat = Get-ChildItem artifacts/repeat/*.tar.gz | Select-Object -First 1
if (-not $Wheel -or -not $WheelRepeat -or -not $Sdist -or -not $SdistRepeat) {
    throw "One or more distribution artifacts were not created"
}

$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("heavy-bulky-" + [guid]::NewGuid())
$WheelTarget = Join-Path $TempRoot "wheel-site"
$SdistTarget = Join-Path $TempRoot "sdist-site"
New-Item -ItemType Directory -Force -Path $WheelTarget, $SdistTarget | Out-Null
$SourceEnvironmentPath = $env:PYTHONPATH
try {
    Invoke-PythonStep "isolated wheel installation with full runtime extras" @("-m", "pip", "install", "--constraint", (Join-Path $Root "constraints-verified.txt"), "--target", $WheelTarget, ($Wheel.FullName + "[full]"))
    Invoke-PythonStep "isolated sdist installation with full runtime extras" @("-m", "pip", "install", "--constraint", (Join-Path $Root "constraints-verified.txt"), "--target", $SdistTarget, ($Sdist.FullName + "[full]"))
    $ResourceCheck = "import heavy_bulky; from importlib import resources; p=resources.files('heavy_bulky'); assert all(p.joinpath('configs', n).is_file() for n in ['smoke.yaml','full.yaml','full_advanced.yaml','m5_small.yaml']); assert all(p.joinpath('sql', n).is_file() for n in ['01_daily_station_service_demand.sql','02_plan_vs_actual.sql','03_monitoring_daily.sql']); print(heavy_bulky.__version__)"

    $env:PYTHONPATH = $WheelTarget
    Invoke-PythonStep "isolated wheel import and resources" @("-c", $ResourceCheck)
    Invoke-PythonStep "wheel-based smoke pipeline" @("-u", "-m", "heavy_bulky.cli", "full-pipeline", "--config", (Join-Path $Root "configs/smoke.yaml"), "--output-dir", (Join-Path $Root "outputs/validation_wheel_smoke")) "reports/wheel_smoke_console.json"
    Invoke-PythonStep "verify wheel-based smoke output" @("-m", "heavy_bulky.cli", "verify-output", "--output-dir", (Join-Path $Root "outputs/validation_wheel_smoke"))

    $env:PYTHONPATH = $SdistTarget
    Invoke-PythonStep "isolated sdist import and resources" @("-c", $ResourceCheck)
    Invoke-PythonStep "sdist-based smoke pipeline" @("-u", "-m", "heavy_bulky.cli", "full-pipeline", "--config", (Join-Path $Root "configs/smoke.yaml"), "--output-dir", (Join-Path $Root "outputs/validation_sdist_smoke")) "reports/sdist_smoke_console.json"
    Invoke-PythonStep "verify sdist-based smoke output" @("-m", "heavy_bulky.cli", "verify-output", "--output-dir", (Join-Path $Root "outputs/validation_sdist_smoke"))
} finally {
    $env:PYTHONPATH = $SourceEnvironmentPath
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $TempRoot
}

Invoke-PythonStep "artifact, determinism, and distribution verification" @(
    "scripts/full_pipeline_validation.py",
    "--smoke-output", "outputs/validation_smoke",
    "--repeat-smoke-output", "outputs/validation_smoke_repeat",
    "--full-output", "outputs/validation_full",
    "--wheel", $Wheel.FullName,
    "--wheel-repeat", $WheelRepeat.FullName,
    "--sdist", $Sdist.FullName,
    "--sdist-repeat", $SdistRepeat.FullName,
    "--wheel-smoke-output", "outputs/validation_wheel_smoke",
    "--sdist-smoke-output", "outputs/validation_sdist_smoke",
    "--api-smoke-report", "reports/api_runtime_smoke.json"
)
