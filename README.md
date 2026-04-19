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
metadata = source.resolve_metadata(202401)

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
      "path": "{period.year}/{period}_{source}.bin",
      "writer": "pandas",
      "collection": "concat",
      "concat_axis": 0,
      "period_column": "period",
      "persistence": true
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
- `storage`: processed-data storage definitions. Each item describes where a processed artifact is written, which writer should be used, how collections should be materialized, and whether data should persist across periods.
- `input`: optional input directory configuration. If `relative` is `true`, `input_dir` is resolved relative to the JSON file.
- `output`: optional output directory configuration. If `relative` is `true`, `output_dir` is resolved relative to the JSON file.

At runtime, `Source.from_path(...)` reads this file, resolves relative directory references from `input` and `output`, and builds a `Source` instance from it.

`Source.resolve_metadata(...)` returns a `Metadata` object. Resolved keys are available both as attributes and as dictionary-style accessors, so user transforms can use either `metadata.inpath` or `metadata["inpath"]`.

## Read Behavior

- `source.read(period, ...)` reads one period.
- `source.read([period1, period2, ...], ...)` respects the exact order of the list.
- `source.read((start, end), ...)` expands a continuous monthly range, ascending or descending according to the tuple order.
- `source.read_one(period, ...)` is the single-period helper used internally.

`skip_error=True` returns `None` when a read cannot be fulfilled. With `skip_error=False`, the underlying error is raised.

## Storage Options

Within each `storage` item:

- `path`: output path template for the stored artifact.
- `writer`: currently supports `pandas` and `pickle`.
- `collection`: one of `list`, `dict`, or `concat`.
- `concat_axis`: axis used when `collection = "concat"`.
- `period_column`: when defined and the value is a pandas `DataFrame`, adds the requested period as a column during collection reads.
- `persistence`: when `true`, only `metadata` entries of type `periodic` act as anchors; later periods reuse the latest valid anchor.

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
