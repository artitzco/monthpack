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
current = source.resolve_metadata(202401)
```

## source.config.json

In general terms, a `source.config.json` file is structured like this:

```json
{
  "source": "bank_statements",
  "path": "../bank_statements",
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
      "writer": "pandas"
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
- `path`: optional base path for the source data. When it is relative, it is resolved relative to the JSON file location.
- `metadata`: temporal metadata definitions. Entries without `period` are base values; entries with `period` override from that month onward; entries with `temporary: true` apply only for that exact month.
- `storage`: processed-data storage definitions. Each item describes where a processed artifact is written and which writer should be used.
- `input`: optional input directory configuration. If `relative` is `true`, `input_dir` is resolved relative to the JSON file.
- `output`: optional output directory configuration. If `relative` is `true`, `output_dir` is resolved relative to the JSON file.

At runtime, `Source.from_path(...)` reads this file, resolves relative directory references, and builds a `Source` instance from it.
