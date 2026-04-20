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
    "input": {
        "relative": true,
        "directory": "input"
    },
    "output": {
        "relative": true,
        "directory": "output"
    },
    "storage": [
        {
            "name": "main",
            "writer": "pandas",
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
- `input`: optional input directory configuration. If `relative` is `true`, `directory` is resolved relative to the JSON file.
- `output`: optional output directory configuration. If `relative` is `true`, `directory` is resolved relative to the JSON file.

At runtime, `Source.from_path(...)` reads this file, resolves relative
directory references from `input` and `output`, and builds a `Source`
instance from it.

`Source.resolve_metadata(...)` returns a `Metadata` object. Resolved keys are available both as attributes and as dictionary-style accessors, so user transforms can use either `metadata.inpath` or `metadata["inpath"]`. The period itself is exposed as `metadata.period`, not as `metadata["period"]`.

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
those cases raise `FileNotFoundError`. Programming errors inside transforms
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
