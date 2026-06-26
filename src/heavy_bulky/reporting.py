from __future__ import annotations

from pathlib import Path

import pandas as pd


def markdown_report(path: str | Path, title: str, sections: list[tuple[str, str]]) -> None:
    parts = [f"# {title}\n"]
    for header, body in sections:
        parts.append(f"## {header}\n\n{body}\n")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(parts), encoding="utf-8")


def df_md(df: pd.DataFrame, max_rows: int = 20) -> str:
    return df.head(max_rows).to_markdown(index=False)
