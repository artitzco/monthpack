"""Helpers for writing sample ``source.config.json`` files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_sample_config(
    path: str | Path,
    *,
    source: str = "sample_source",
) -> Path:
    """Write a starter config with DataFrame, Series, and pickle storages."""
    payload: dict[str, Any] = {
        "source": source,
        "metadata": [
            {
                "inpath": "**/{period}_*.csv",
                "reader": "csv",
            }
        ],
        "storage": [
            {
                "name": "dataframe",
                "writer": "pandas",
                "pandas_type": "dataframe",
                "collection": "concat",
                "concat_axis": 0,
                "period_label": "period",
                "metadata": [
                    {
                        "outpath": "{period.year}/{period}_{source}_dataframe.feather",
                    }
                ],
            },
            {
                "name": "series",
                "writer": "pandas",
                "pandas_type": "series",
                "collection": "concat",
                "period_label": "period",
                "metadata": [
                    {
                        "outpath": "{period.year}/{period}_{source}_series.feather",
                    }
                ],
            },
            {
                "name": "pickle",
                "writer": "pickle",
                "collection": "list",
                "metadata": [
                    {
                        "outpath": "{period.year}/{period}_{source}_pickle.pkl",
                    }
                ],
            },
        ],
        "input": {
            "relative": True,
            "input_dir": "input",
        },
        "output": {
            "relative": True,
            "output_dir": "output",
        },
    }

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=4),
        encoding="utf-8",
    )
    return destination
