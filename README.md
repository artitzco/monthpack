# monthpack

`monthpack` is a Python library for organizing data sources with monthly
periodicity, such as bank statements, income statements, and similar records.

The project is centered around source-local `metadata.json` files that define:

- base entries without `period`
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
from monthpack import Metadata

metadata = Metadata.from_path("data/source/metadata.json")
current = metadata.entries(202401)
```
