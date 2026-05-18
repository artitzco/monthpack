"""Helpers for writing starter ``source.config.json`` files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from typing import Mapping


def write_dataframe_config(path: str | Path) -> Path:
    """Write a starter config for a pandas DataFrame workflow."""
    payload: dict[str, Any] = {
        "name": "dataframe_name",
        "input": "|input",
        "output": "|output",
        "format": "dataframe",
        "persistence": False,
        "static": False,
        "min_period": None,
        "collection": "concat",
        "concat_axis": 0,
        "period_label": "period",
        "period_as_index": False,
        "metadata": [
            {
                "inpath": "**/{period}_*.csv",
                "reader": "csv",
                "outpath": "{period.year}/{period}_{name}.bin",
            }
        ],
    }
    return _write_config(path, payload)


def write_series_config(path: str | Path) -> Path:
    """Write a starter config for a pandas Series workflow."""
    payload: dict[str, Any] = {
        "name": "series_name",
        "input": "|input",
        "output": "|output",
        "format": "series",
        "persistence": False,
        "static": False,
        "min_period": None,
        "collection": "concat",
        "period_label": "period",
        "period_as_index": False,
        "metadata": [
            {
                "inpath": "**/{period}_*.csv",
                "reader": "csv",
                "outpath": "{period.year}/{period}_{name}.bin",
            }
        ],
    }
    return _write_config(path, payload)


def write_pickle_config(path: str | Path) -> Path:
    """Write a starter config for a pickle workflow."""
    payload: dict[str, Any] = {
        "name": "pickle_name",
        "input": "|input",
        "output": "|output",
        "format": "pickle",
        "persistence": False,
        "static": False,
        "min_period": None,
        "collection": "list",
        "metadata": [
            {
                "inpath": "**/{period}_*.csv",
                "reader": "csv",
                "outpath": "{period.year}/{period}_{name}.pkl",
            }
        ],
    }
    return _write_config(path, payload)


def _write_config(path: str | Path, payload: Mapping[str, Any]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=4),
        encoding="utf-8",
    )
    return destination
