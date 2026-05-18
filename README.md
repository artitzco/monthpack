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

`reserved_kwargs` (as well as dynamic `**kwargs` acting as overrides) are passed to the postprocessor during `read(...)` and `read_one(...)`.

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
    "format": "dataframe",
    "collection": "concat",
    "concat_axis": 0,
    "period_label": "period",
    "persistence": true,
    "static": false,
    "min_period": 202401,
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
- `format`: one of `dataframe`, `series`, or `pickle`.
- `collection`: one of `list`, `dict`, or `concat`.
- `concat_axis`: axis for `concat` collection.
- `period_label`: optional label for period annotation in pandas collections.
- `period_as_index`: optional (`false` by default). When `true` and `period_label` is set, period labeling replaces the existing index in pandas outputs instead of adding a column (DataFrame) or an outer MultiIndex level (Series).
- `persistence`: when `true`, missing input data for a requested period is resolved by probing earlier periods with the registered preprocessor until it returns a non-null value.
- `static`: when `true`, the source is treated as atemporal. Calling `read` with a specific period will raise a `ValueError`.
- `min_period`: lower bound for persistent backward probing. It defaults to `null`; persistent sources should set an explicit integer `YYYYMM` value.
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

`skip_error=True` returns `None` for missing-read cases such as a missing processed file. With `skip_error=False`, those cases raise `FileNotFoundError`. Missing persistent input returns `None` after a single admin-mode warning when `verbose=True`.

With `persistence=true`, each requested period is saved independently. If `source.read(202503)` is requested and the preprocessor returns `None` for 202503 and 202502 but returns data for 202501, that data is saved to the 202503 output path. Later reads of 202503 use the processed 202503 file unless `reload=True` is passed.

## User Mode

```python
source.set_user()
data = source.read(202401)
```

In user mode:

- `read(...)` only returns already processed data.
- missing processed files are not regenerated from raw inputs.

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

`monthpack` also includes an independent `Period` class for monthly values represented as `YYYYMM`:

```python
from monthpack import Period

period = Period(202401)
print(period.year)   # 2024
print(period.month)  # 1
print(str(period))   # "202401"
```

## Fluent Reader Interface (SourceReader)

`SourceReader` provides a subscriptable and callable interface designed to make reading data sources expressive and readable. 

You can create a `SourceReader` from a source, pre-configuring default keyword arguments for the postprocessor:

```python
# Create a reader with pre-configured postprocessor kwargs
reader = source.as_reader(filtro="activo", umbral=10)

# 1. Callable access (behaves exactly like source.read):
data = reader(202401)

# You can pass runtime overrides and bypass reserved words via reserved_kwargs:
data = reader(202401, filtro="inactivo", reserved_kwargs={"reload": True})

# 2. Subscriptable access (reads a single period):
data = reader[202401]

# 3. Slice range access (reads an inclusive monthly range):
data = reader[202401:202406]
```

## Source Central Registry (SourceManager)

`SourceManager` provides a centralized registry to manage and read multiple sources:

```python
from monthpack import SourceManager

manager = SourceManager()

# Batch register one or more sources
manager.add_source(source_sales, source_finance)

# Access sources by name or insertion index
sales = manager["sales"]

# Proxy reads transparently
data = manager.read("sales", (202401, 202406), reserved_kwargs={"filtro": "activo"})
```
