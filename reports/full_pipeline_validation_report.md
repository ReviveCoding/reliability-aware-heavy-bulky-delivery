# Full Pipeline Validation Report

**Overall:** PASS

## Checks

- **artifact_integrity:qfinal_smoke3**: PASS
  - `{"missing": [], "output": "outputs/qfinal_smoke3", "problems": []}`
- **artifact_integrity:qfinal_full**: PASS
  - `{"missing": [], "output": "outputs/qfinal_full", "problems": []}`
- **wheel_integrity**: PASS
  - `{"file_count": 37, "missing": [], "sha256": "1d6d9a7d7c6ad2a3b44df176883ab99bec80fed0830153201d6b304d6a38c0f5", "wheel": "artifacts/dist/heavy_bulky_delivery_reliability-0.4.3-py3-none-any.whl"}`
- **artifact_integrity:package_first_wheel_smoke**: PASS
  - `{"missing": [], "output": "outputs/package_first_wheel_smoke", "problems": []}`
- **artifact_integrity:qfinal_smoke2**: PASS
  - `{"missing": [], "output": "outputs/qfinal_smoke2", "problems": []}`
- **decision_fingerprint_reproducibility**: PASS
  - `{"first": "dabb0d321813c34c46964d3b7df8f57b72ae35ed440b7d04b043b56423ebbe60", "second": "dabb0d321813c34c46964d3b7df8f57b72ae35ed440b7d04b043b56423ebbe60"}`
- **wheel_bitwise_reproducibility**: PASS
  - `{"first_sha256": "1d6d9a7d7c6ad2a3b44df176883ab99bec80fed0830153201d6b304d6a38c0f5", "second_sha256": "1d6d9a7d7c6ad2a3b44df176883ab99bec80fed0830153201d6b304d6a38c0f5"}`
- **sdist_integrity**: PASS
  - `{"file_count": 58, "missing": [], "sdist": "artifacts/dist/heavy_bulky_delivery_reliability-0.4.3.tar.gz", "sha256": "81eac60e47d1d493beffeb25d26f177d2076ea1788fb599ba180bbe6f04d7076"}`
- **sdist_content_reproducibility**: PASS
  - `{"content_file_count": 52, "differing_files": [], "first_sha256": "81eac60e47d1d493beffeb25d26f177d2076ea1788fb599ba180bbe6f04d7076", "second_sha256": "797cbbb7b1662812161d84bbf538d66a13d822f7d927860ecde3935b3f16c851"}`
- **artifact_integrity:package_first_sdist_smoke**: PASS
  - `{"missing": [], "output": "outputs/package_first_sdist_smoke", "problems": []}`
- **api_runtime_smoke**: PASS
  - `{"elapsed_seconds": 15.043898, "latest_elapsed_ms": 20.753, "mismatches": {}, "report": "reports/qfinal_api_runtime_smoke.json", "workers": 2}`
