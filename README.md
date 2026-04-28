# monthpack

`monthpack` is a Python library for organizing period-based data sources, such as bank statements, income statements, and similar records.

Starting with `0.2.0`, `monthpack` uses a **single implicit storage configuration** per `source.config.json`.

## Current Layout

```text
monthpack/
  data/
  src/
    monthpack/
  pyproject.toml
  README.md
```

## Quick Example

```python
from monthpack import Source

source = Source.from_path("data/source/source.config.json")
metadata = source.resolve_metastate(202401)

print(metadata.period)
print(metadata.year)
print(metadata.month)
print(metadata.inpath)
print(metadata["reader"])

data = source.read((202401, 202406), skip_error=True)
```

## Processor Registration

`Source` now accepts singular processors:

```python
source = Source.from_path(
    "data/source/source.config.json",
    admin_user=True,
    preprocessor=preprocess_main,
    postprocessor=postprocess_main,
)
```

Or after initialization:

```python
source.set_preprocessor(preprocess_main)
source.set_postprocessor(postprocess_main)
```

`postprocessor_kwargs` are passed to the postprocessor during `read(...)` and `read_one(...)`.

## Config Writers

The package provides independent helpers for creating starter configs:

```python
from monthpack import write_dataframe_config
from monthpack import write_pickle_config
from monthpack import write_series_config

write_dataframe_config("data/sample/source_dataframe.config.json")
write_series_config("data/sample/source_series.config.json")
write_pickle_config("data/sample/source_pickle.config.json")
```

## source.config.json Schema (v0.2.0)

A config is now flat (no `storage` container):

```json
{
    "name": "main",
    "input": "|input",
    "output": "|output",
    "writer": "pandas",
    "pandas_type": "dataframe",
    "collection": "concat",
    "concat_axis": 0,
    "period_label": "period",
    "persistence": true,
    "metadata": [
        {
            "inpath": "**/{period}_*.csv",
            "reader": "csv",
            "outpath": "{period.year}/{period}_{name}.bin"
        },
        {
            "period": 202507,
            "inpath": "**/{period}_*.xlsx",
            "reader": "excel"
        }
    ]
}
```

Field overview:

- `name`: optional, used for template interpolation (`{name}`).
- `writer`: supports `pandas` and `pickle`.
- `pandas_type`: required when `writer = "pandas"`; use `dataframe` or `series`.
- `collection`: one of `list`, `dict`, or `concat`.
- `concat_axis`: axis for `concat` collection.
- `period_label`: optional label for period annotation in pandas collections.
- `persistence`: when `true`, periodic metadata rules behave as persistence anchors.
- `metadata`: unified global metadata rules (base, periodic, and temporary).
- `input`/`output`: optional paths.

Metadata rule behavior:

- entries without `period` are base values
- entries with `period` apply from that period onward
- entries with `temporary: true` apply only for the exact period

## Read Behavior

- `source.read(period, ...)` reads one period.
- `source.read(None, ...)` reads the atemporal/base case.
- `source.read([period1, period2, ...], ...)` respects list order.
- `source.read((start, end), ...)` expands an inclusive monthly range.
- `source.read_one(period, ...)` is the single-period helper used internally.

`skip_error=True` returns `None` for missing-read cases such as a missing processed file or persistence anchor. With `skip_error=False`, those cases raise `FileNotFoundError`.

## User Mode

```python
source.set_user()
data = source.read(202401)
```

In user mode:

- `read(...)` only returns already processed data.
- missing processed files are not regenerated from raw inputs.
- `save(...)` is not available.

## Metadata Module

`monthpack` includes an independent metadata resolver module:

```python
from monthpack.metadata import Metadata

metadata = Metadata.from_entries(
    [
        {"reader": "csv", "path": "raw"},
        {"period": 202501, "reader": "excel"},
        {"period": 202502, "temporary": True, "reader": "parquet"},
    ]
)

base = metadata.resolve(None)
current = metadata.resolve(202502)

print(base.reader)
print(current.reader)
print(current.year)
print(current.month)
```

## Period Module

`monthpack` also includes an independent `Period` class for monthly values represented as `YYYYMM`.
