"""Helpers for writing sample ``source.config.json`` files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_sample_config(
    path: str | Path,
) -> Path:
    """Write a starter config with DataFrame, Series, and pickle storages."""
    payload: dict[str, Any] = {
        "input": {
            "relative": True,
            "directory": "input",
        },
        "output": {
            "relative": True,
            "directory": "output",
        },
        "storage": [
            {
                "name": "dataframe",
                "writer": "pandas",
                "pandas_type": "dataframe",
                "persistence": False,
                "collection": "concat",
                "concat_axis": 0,
                "period_label": "period",
                "metadata": [
                    {
                        "outpath": "{period.year}/{period}_{name}.bin",
                    }
                ],
            },
            {
                "name": "series",
                "writer": "pandas",
                "pandas_type": "series",
                "persistence": False,
                "collection": "concat",
                "period_label": "period",
                "metadata": [
                    {
                        "outpath": "{period.year}/{period}_{name}.bin",
                    }
                ],
            },
            {
                "name": "pickle",
                "writer": "pickle",
                "persistence": False,
                "collection": "list",
                "metadata": [
                    {
                        "outpath": "{period.year}/{period}_{name}.pkl",
                    }
                ],
            },
        ],
        "metadata": [
        ],
    }

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=4),
        encoding="utf-8",
    )
    return destination
