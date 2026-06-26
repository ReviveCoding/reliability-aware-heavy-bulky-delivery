from __future__ import annotations

import hashlib
import tarfile
import zipfile
from collections.abc import Iterable
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def wheel_contents(wheel: Path) -> set[str]:
    with zipfile.ZipFile(wheel) as archive:
        return set(archive.namelist())


def sdist_content_manifest(sdist: Path) -> dict[str, str]:
    """Return content hashes independent of gzip and tar member timestamps."""
    manifest: dict[str, str] = {}
    with tarfile.open(sdist, "r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            parts = Path(member.name).parts
            relative = Path(*parts[1:]).as_posix() if len(parts) > 1 else parts[0]
            manifest[relative] = hashlib.sha256(extracted.read()).hexdigest()
    return dict(sorted(manifest.items()))


def distribution_resources(names: Iterable[str]) -> list[str]:
    required = {
        "heavy_bulky/configs/smoke.yaml",
        "heavy_bulky/configs/full.yaml",
        "heavy_bulky/configs/full_advanced.yaml",
        "heavy_bulky/configs/m5_small.yaml",
        "heavy_bulky/sql/01_daily_station_service_demand.sql",
        "heavy_bulky/sql/02_plan_vs_actual.sql",
        "heavy_bulky/sql/03_monitoring_daily.sql",
        "heavy_bulky/solver_worker.py",
        "heavy_bulky/integrity.py",
    }
    available = set(names)
    return sorted(required - available)
