# monthpack

`monthpack` is a Python library for organizing period-based data sources, such
as bank statements, income statements, and similar records.

The project is centered around local `source.config.json` files that define:

- base metadata without `period`
- persistent changes starting at a given `period`
- temporary changes for one specific `period`
- placeholders such as `{period}`, `{period.year}`, and `{period.month}`

## Current Layout

```text
monthpack/
  data/
  src/
    monthpack/
  pyproject.toml
  README.md
```

## Example

```python
from monthpack import Source

source = Source.from_path("data/source/source.config.json")
metadata = source.resolve_metadata(202401, storage=0)

print(metadata.period)
print(metadata.year)
print(metadata.month)
print(metadata.inpath)
print(metadata["reader"])

data = source.read((202401, 202406), storage=0, skip_error=True)
```

## Metadata Module

`monthpack` now also includes an experimental independent metadata module:

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

print(base.reader)      # csv
print(current.reader)   # parquet
print(current.year)     # 2025
print(current.month)    # 2
```

This module is designed as a generic ordered metadata resolver:

- `Metadata` stores the full sequence of metadata rules.
- `MetadataRule` represents one base, periodic, or temporary rule.
- `MetadataState` is the resolved state for one period.

Current rule behavior:

- entries without `period` are base values
- entries with `period` apply from that period onward
- entries with `temporary: true` apply only for the exact period

For now, this module is independent from `Source` and `source.config.json`.
It is documented here because it is part of the package, but it is not yet
wired into the main source-loading workflow.

## Period Module

`monthpack` also includes an independent `Period` class for working with
monthly periods represented as `YYYYMM`:

```python
from datetime import date

from monthpack import Period

period = Period(202504)

print(period.year)              # 2025
print(period.month)             # 4
print(period + 1)               # 202505
print(period - 3)               # 202501
print(period - Period(202501))  # 3
```

`Period` also provides explicit constructors and a general coercion helper:

```python
from monthpack import Period

print(Period.from_int(2601))          # 202601
print(Period.from_string("26-01"))    # 202601
print(Period.from_string("2026-01"))  # 202601
print(Period.from_date(date(2026, 1, 15)))  # 202601

print(Period.coerce(2601))         # 202601
print(Period.coerce("2026-01"))    # 202601
```

Current `Period` behavior:

- `Period(202504)` expects the canonical integer form `YYYYMM`.
- `from_int(...)` accepts `YYYYMM` and short `YYMM`, where `YYMM` is interpreted as `20YYMM`.
- `from_string(...)` accepts formats such as `YYYYMM`, `YYMM`, `YYYY-MM`, `YY-MM`, and full dates like `YYYY-MM-DD`.
- `from_date(...)` accepts date-like objects with integer `year` and `month`, including `date`, `datetime`, and `pandas.Timestamp`.
- `coerce(...)` normalizes common inputs into a `Period`.
- `Period.range(start, end)` expands an inclusive monthly sequence in ascending or descending order.

Like the metadata module, `Period` is currently documented as an independent
building block. It is not yet wired into `Source` or the metadata resolver.

You can also initialize the source with `admin_user` and `preprocessors`:

```python
source = Source.from_path(
    "data/source/source.config.json",
    admin_user=True,
    preprocessors=[preprocess_main, preprocess_backup],
)
```

You can also override `input` or `output` when loading the config:

```python
from pathlib import Path

source = Source.from_path(
    "data/source/source.config.json",
    input=Path("D:/raw/monthpack"),
    output="D:/processed_alt",
)
```

## Config Templates

`monthpack` also exposes a helper function for generating a starter
`source.config.json` file:

```python
from monthpack import write_sample_config

write_sample_config("data/sample/source.config.json")
```

This helper generates one example file with three storages already configured:

- `dataframe`: `pandas` with `pandas_type = "dataframe"`
- `series`: `pandas` with `pandas_type = "series"`
- `pickle`: `pickle`

## source.config.json

In general terms, a `source.config.json` file is structured like this:

```json
{
    "input": "|input",
    "output": "|output",
    "storage": [
        {
            "name": "main",
            "writer": "pandas",
            "pandas_type": "dataframe",
            "collection": "concat",
            "concat_axis": 0,
            "period_label": "period",
            "persistence": true,
            "metadata": [
                {
                    "outpath": "{period.year}/{period}_{name}.bin"
                }
            ]
        }
    ],
    "metadata": [
        {
            "inpath": "**/{period}_*.csv",
            "reader": "csv"
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

- `metadata`: temporal metadata definitions. Entries without `period` are base values; entries with `period` override from that month onward; entries with `temporary: true` apply only for that exact month.
- `storage`: processed-data storage definitions. Each item defines writer and collection behavior, and can also contain its own `metadata` list.
- `input`: optional input directory.
- `output`: optional output directory.

Path resolution rules:

- `"|input"`: relative to the folder containing the JSON file.
- `"input"`: relative to the current execution directory.
- `"C:/data/input"`: absolute path.

At runtime, `Source.from_path(...)` reads this file, resolves `input` and
`output`, and builds a `Source` instance from it. The same method also accepts
optional `input` and `output` overrides. Those values can be:

- a `str`
- a `pathlib.Path`

When `input` or `output` are passed to `from_path(...)`, they completely replace
the corresponding block from the JSON file. Strings and `Path` objects are
treated as direct paths; if they are relative, they are resolved from the
current execution directory and normalized to absolute paths. Strings starting
with `|` are resolved relative to the JSON file directory. You can also pass
`admin_user` and `preprocessors` directly to the same constructor.

`Source.resolve_metadata(...)` returns a `Metadata` object. Resolved keys are available both as attributes and as dictionary-style accessors, so user preprocessors can use either `metadata.inpath` or `metadata["inpath"]`. The period itself is exposed as `metadata.period`, not as `metadata["period"]`.

When `period=None`, `resolve_metadata(...)` returns only the base metadata,
without applying any `periodic` or `temporary` entries.

Storage references can be passed either as:

- an index, for example `storage=0`
- a storage name, for example `storage="main"`

When `name` is defined inside `storage`, it must be unique across the
configuration.

## Read Behavior

- `source.read(period, ...)` reads one period.
- `source.read(None, ...)` reads the atemporal/base case.
- `source.read([period1, period2, ...], ...)` respects the exact order of the list.
- `source.read((start, end), ...)` expands a continuous monthly range, ascending or descending according to the tuple order.
- `source.read_one(period, ...)` is the single-period helper used internally.

`skip_error=True` returns `None` for missing-read cases such as a missing
processed file or a missing persistence anchor. With `skip_error=False`,
those cases raise `FileNotFoundError`. Programming errors inside preprocessors
are not swallowed.

## Storage Options

Within each `storage` item:

- `name`: optional unique identifier that lets the storage be referenced by name instead of only by index.
- `writer`: currently supports `pandas` and `pickle`.
- `pandas_type`: required when `writer = "pandas"`. Use `dataframe` or `series`.
- `collection`: one of `list`, `dict`, or `concat`.
- `concat_axis`: axis used when `collection = "concat"`.
- `period_label`: when defined, adds the requested period to pandas outputs
  during collection reads. For `DataFrame`, it is used as a column name; for
  `Series`, it is used as the outer index level name.
- `persistence`: when `true`, only `metadata` entries of type `periodic` act as anchors; later periods reuse the latest valid anchor.
- `metadata`: storage-specific metadata. This is also where `outpath` should be declared.

Within storage metadata:

- `outpath`: output path template for the stored artifact.

## User Mode

`Source` can run in read-only user mode:

```python
source.set_user()
data = source.read(202401)
```

In user mode:

- `read(...)` only returns already processed data.
- missing processed files are not regenerated from raw inputs.
- `save(...)` is not available.
