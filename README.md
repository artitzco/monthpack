# monthpack

`monthpack` is a Python library for organizing data sources with monthly
periodicity, such as bank statements, income statements, and similar records.

The project is centered around source-local `source.config.json` files that define:

- base metadata without `period`
- persistent changes starting at a given `period`
- temporary changes for one specific `period`
- placeholders such as `{period}`, `{period.year}`, `{period.month}`, and `{source}`

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

## source.config.json

In general terms, a `source.config.json` file is structured like this:

```json
{
  "source": "bank_statements",
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
  ],
  "storage": [
    {
      "writer": "pandas",
      "collection": "concat",
      "concat_axis": 0,
      "period_column": "period",
      "persistence": true,
      "metadata": [
        {
          "outpath": "{period.year}/{period}_{source}.bin"
        }
      ]
    }
  ],
  "input": {
    "relative": true,
    "input_dir": "input"
  },
  "output": {
    "relative": true,
    "output_dir": "output"
  }
}
```

Field overview:

- `source`: logical source name used by the configuration and template rendering.
- `metadata`: temporal metadata definitions. Entries without `period` are base values; entries with `period` override from that month onward; entries with `temporary: true` apply only for that exact month.
- `storage`: processed-data storage definitions. Each item defines writer and collection behavior, and can also contain its own `metadata` list. Storage metadata is merged on top of global metadata, so matching keys override the global values and new keys are added.
- `input`: optional input directory configuration. If `relative` is `true`, `input_dir` is resolved relative to the JSON file.
- `output`: optional output directory configuration. If `relative` is `true`, `output_dir` is resolved relative to the JSON file.

At runtime, `Source.from_path(...)` reads this file, resolves relative directory references from `input` and `output`, and builds a `Source` instance from it.

`Source.resolve_metadata(...)` returns a `Metadata` object. Resolved keys are available both as attributes and as dictionary-style accessors, so user transforms can use either `metadata.inpath` or `metadata["inpath"]`. The period itself is exposed as `metadata.period`, not as `metadata["period"]`.

When `period=None`, `resolve_metadata(...)` returns only the base metadata, without applying any `periodic` or `temporary` entries.

## Read Behavior

- `source.read(period, ...)` reads one period.
- `source.read(None, ...)` reads the atemporal/base case.
- `source.read([period1, period2, ...], ...)` respects the exact order of the list.
- `source.read((start, end), ...)` expands a continuous monthly range, ascending or descending according to the tuple order.
- `source.read_one(period, ...)` is the single-period helper used internally.

`skip_error=True` returns `None` only for the missing-read cases identified by the library itself, such as a missing processed file or a missing persistence anchor. With `skip_error=False`, those cases raise `FileNotFoundError`. Programming errors inside transforms are not swallowed.

## Storage Options

Within each `storage` item:

- `writer`: currently supports `pandas` and `pickle`.
- `collection`: one of `list`, `dict`, or `concat`.
- `concat_axis`: axis used when `collection = "concat"`.
- `period_column`: when defined and the value is a pandas `DataFrame`, adds the requested period as a column during collection reads.
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
