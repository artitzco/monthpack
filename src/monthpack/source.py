"""Source loading and period-aware metadata and storage resolution."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import json
from pathlib import Path
from string import Formatter
from typing import TYPE_CHECKING
from typing import Callable
from typing import Any, Mapping

if TYPE_CHECKING:
    from pandas import DataFrame
    from pandas import DataFrame as PandasDataFrame


def _is_period_rule(rule: Mapping[str, Any]) -> bool:
    return "period" in rule


def _is_temporary(rule: Mapping[str, Any]) -> bool:
    return bool(rule.get("temporary", False))


def _copy_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    return dict(mapping.items())


DEFAULT_STORAGE = (
    {
        "outpath": "{period.year}/{period}_{source}.bin",
        "writer": "pickle",
    },
)


@dataclass(frozen=True)
class _Period:
    value: int

    @property
    def year(self) -> int:
        return self.value // 100

    @property
    def month(self) -> int:
        return self.value % 100

    def __str__(self) -> str:
        return str(self.value)


@dataclass
class Source:
    """Represents one source and resolves values for a period."""

    source: str
    storage: tuple[dict[str, Any], ...]
    metadata: tuple[dict[str, Any], ...]
    input_root: Path | None = None
    output_root: Path | None = None
    transforms: list[Callable[[dict[str, Any]], DataFrame]] = field(default_factory=list)

    @classmethod
    def from_path(cls, path: str | Path) -> Source:
        """Load source configuration from a JSON file."""
        source_path = Path(path)
        with source_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        updated = False
        if "storage" not in payload:
            payload["storage"] = [dict(item) for item in DEFAULT_STORAGE]
            updated = True
        if "input_root" not in payload:
            payload["input_root"] = "input"
            updated = True
        if "output_root" not in payload:
            payload["output_root"] = "output"
            updated = True
        if updated:
            with source_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=4)
        data_root = source_path.parent
        if "path" in payload:
            data_root = (source_path.parent / str(payload["path"])).resolve()
        normalized_payload = dict(payload)
        normalized_payload["input_root"] = str(data_root / str(payload.get("input_root", "input")))
        normalized_payload["output_root"] = str(data_root / str(payload.get("output_root", "output")))
        return cls.from_dict(normalized_payload)

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> Source:
        """Build a source object from a mapping."""
        source = str(payload["source"])
        raw_storage = payload.get("storage", DEFAULT_STORAGE)
        storage_data = tuple(_copy_mapping(item) for item in raw_storage)
        raw_metadata = payload.get("metadata", [])
        metadata_data = tuple(_copy_mapping(entry) for entry in raw_metadata)
        return cls(
            source=source,
            storage=storage_data,
            metadata=metadata_data,
            input_root=Path(str(payload["input_root"])) if "input_root" in payload else None,
            output_root=Path(str(payload["output_root"])) if "output_root" in payload else None,
        )

    def resolve_metadata(self, period: int | None = None) -> dict[str, Any]:
        """Resolve metadata values for a specific period."""
        resolved = self._metadata_raw(period)
        return self._render_templates(resolved, period=period)

    def set_transforms(
        self,
        transforms: list[Callable[[dict[str, Any]], DataFrame]],
    ) -> None:
        """Register transforms by storage position."""
        self.transforms = list(transforms)

    def save(self, period: int, storage: int = 0) -> Path:
        """Build and save data for a period using the selected storage item."""
        metadata = self.resolve_metadata(period)
        transform = self._transform(storage)
        dataframe = transform(metadata)
        storage_item = self.resolve_storage_item(period, storage)
        destination = self._storage_path(storage_item)
        destination.parent.mkdir(parents=True, exist_ok=True)
        writer = str(storage_item["writer"])
        if writer == "pandas":
            dataframe.to_feather(destination)
        elif writer == "pickle":
            dataframe.to_pickle(destination)
        else:
            raise ValueError(f"Unsupported writer: {writer}")
        return destination

    def read(self, period: int, storage: int = 0, reload: bool = False) -> PandasDataFrame:
        """Read data for a period, building it first when needed."""
        import pandas as pd

        storage_item = self.resolve_storage_item(period, storage)
        source_path = self._storage_path(storage_item)
        if reload or not source_path.exists():
            self.save(period, storage)
        writer = str(storage_item["writer"])
        if writer == "pandas":
            return pd.read_feather(source_path)
        if writer == "pickle":
            return pd.read_pickle(source_path)
        raise ValueError(f"Unsupported writer: {writer}")

    def resolve_storage(self, period: int | None = None) -> list[dict[str, Any]]:
        """Resolve all storage definitions for a specific period."""
        return self._render_storage(period)

    def resolve_storage_item(self, period: int | None = None, storage: int = 0) -> dict[str, Any]:
        """Resolve one storage definition for a specific period."""
        return dict(self._storage_item(self.resolve_storage(period), storage))

    def _metadata_raw(self, period: int | None) -> dict[str, Any]:
        base_metadata = [entry for entry in self.metadata if not _is_period_rule(entry)]
        resolved_period = self._resolve_period(period)
        persistent_metadata = sorted(
            (
                entry
                for entry in self.metadata
                if _is_period_rule(entry)
                and not _is_temporary(entry)
                and int(entry["period"]) <= resolved_period
            ),
            key=lambda entry: int(entry["period"]),
        )
        temporary_metadata = [
            entry
            for entry in self.metadata
            if _is_period_rule(entry) and _is_temporary(entry) and int(entry["period"]) == resolved_period
        ]

        resolved: dict[str, Any] = {}
        for entry in [*base_metadata, *persistent_metadata, *temporary_metadata]:
            resolved.update(self._metadata_payload(entry))
        return resolved

    def _resolve_period(self, period: int | None) -> int:
        if period is not None:
            return period

        periods = [
            int(entry["period"])
            for entry in self.metadata
            if _is_period_rule(entry) and not _is_temporary(entry)
        ]
        if periods:
            return max(periods)
        return 0

    def _metadata_payload(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in entry.items()
            if key not in {"period", "temporary"}
        }

    def _render_storage(self, period: int | None) -> list[dict[str, Any]]:
        return [
            self._render_value(item, self._template_context(period))
            for item in self.storage
        ]

    def _storage_item(self, value: Any, storage: int) -> Mapping[str, Any]:
        if isinstance(value, list) and 0 <= storage < len(value):
            return value[storage]
        raise ValueError("storage must contain at least one item")

    def _storage_path(self, storage_item: Mapping[str, Any]) -> Path:
        path = Path(str(storage_item["outpath"]))
        if self.output_root is not None:
            path = self.output_root / path
        return path

    def _transform(self, storage: int) -> Callable[[dict[str, Any]], DataFrame]:
        if 0 <= storage < len(self.transforms):
            return self.transforms[storage]
        raise ValueError("transform is not defined for the requested storage index")

    def _render_templates(self, values: Mapping[str, Any], *, period: int | None) -> dict[str, Any]:
        context = self._template_context(period)
        return {
            key: self._render_value(value, context)
            for key, value in values.items()
        }

    def _template_context(self, period: int | None) -> dict[str, Any]:
        resolved_period = self._resolve_period(period)
        return {
            "period": _Period(resolved_period),
            "source": self.source,
        }

    def _render_value(self, value: Any, context: Mapping[str, Any]) -> Any:
        if isinstance(value, str):
            return self._safe_format(value, context)
        if isinstance(value, list):
            return [self._render_value(item, context) for item in value]
        if isinstance(value, dict):
            return {
                key: self._render_value(item, context)
                for key, item in value.items()
            }
        return value

    def _safe_format(self, template: str, context: Mapping[str, Any]) -> str:
        field_names = {
            field_name
            for _, field_name, _, _ in Formatter().parse(template)
            if field_name
        }
        if not field_names:
            return template
        render_context = {name: context[name] for name in field_names if name in context}
        return template.format(**render_context)
