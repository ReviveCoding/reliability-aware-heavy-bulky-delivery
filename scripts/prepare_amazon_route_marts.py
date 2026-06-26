from __future__ import annotations

import argparse
from pathlib import Path

from heavy_bulky.amazon_routes import build_public_route_marts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert Amazon Last Mile route/package JSON files into CSV marts."
    )
    parser.add_argument("--route-json", required=True)
    parser.add_argument("--package-json", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    routes, stops, packages = build_public_route_marts(args.route_json, args.package_json)
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    routes.to_csv(output / "routes.csv", index=False)
    stops.to_csv(output / "stops.csv", index=False)
    packages.to_csv(output / "packages.csv", index=False)
    print(f"wrote routes={len(routes)}, stops={len(stops)}, packages={len(packages)} to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
