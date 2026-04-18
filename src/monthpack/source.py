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
    path: str | None = None
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    transforms: list[Callable[[dict[str, Any]], DataFrame]] = field(default_factory=list)

    @classmethod
    def from_path(cls, path: str | Path) -> Source:
        """Load source configuration from a JSON file."""
        source_path = Path(path)
        with source_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return cls.from_dict(payload, source_path=source_path)

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        source_path: str | Path | None = None,
    ) -> Source:
        """Build a source object from a mapping."""
        source = str(payload["source"])
        raw_storage = payload["storage"]
        storage_data = tuple(_copy_mapping(item) for item in raw_storage)
        raw_metadata = payload["metadata"]
        metadata_data = tuple(_copy_mapping(entry) for entry in raw_metadata)
        path_value = str(payload["path"]) if "path" in payload else None
        source_file = Path(source_path) if source_path is not None else None
        base_path = source_file.parent if source_file is not None else None
        base_dir = None
        if path_value is not None:
            path_candidate = Path(path_value)
            if base_path is not None and not path_candidate.is_absolute():
                base_dir = (base_path / path_candidate).resolve()
            else:
                base_dir = path_candidate
        elif base_path is not None:
            base_dir = base_path

        input_config = None
        if "input" in payload:
            input_config = cls._resolve_io_config(payload["input"], base_dir, "input_dir")

        output_config = None
        if "output" in payload:
            output_config = cls._resolve_io_config(payload["output"], base_dir, "output_dir")

        return cls(
            source=source,
            storage=storage_data,
            metadata=metadata_data,
            path=path_value,
            input=input_config,
            output=output_config,
        )

    def resolve_metadata(self, period: int | None = None, verbose: bool = True) -> dict[str, Any]:
        """Resolve metadata values for a specific period."""
        resolved_period = self._resolve_period(period)
        resolved = self._metadata_raw(period)
        resolved["period"] = resolved_period
        rendered = self._render_templates(resolved, period=period)
        return self._resolve_inpaths(rendered, verbose=verbose)

    def set_transforms(
        self,
        transforms: list[Callable[[dict[str, Any]], DataFrame]],
    ) -> None:
        """Register transforms by storage position."""
        self.transforms = list(transforms)

    def save(self, period: int, storage: int = 0, verbose: bool = True) -> Path:
        """Build and save data for a period using the selected storage item."""
        metadata = self.resolve_metadata(period, verbose=verbose)
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

    def read(
        self,
        period: int,
        storage: int = 0,
        reload: bool = False,
        verbose: bool = True,
    ) -> PandasDataFrame | None:
        """Read data for a period, building it first when needed."""
        import pandas as pd

        storage_item = self.resolve_storage_item(period, storage)
        source_path = self._storage_path(storage_item)
        if reload or not source_path.exists():
            metadata = self.resolve_metadata(period, verbose=verbose)
            missing_inpaths = self._missing_inpaths(metadata)
            if missing_inpaths:
                if str(storage_item.get("on_missing", "error")) == "none":
                    return None
                missing_keys = ", ".join(missing_inpaths)
                raise FileNotFoundError(f"Missing input path for: {missing_keys}")
            self.save(period, storage, verbose=verbose)
        if not source_path.exists():
            if str(storage_item.get("on_missing", "error")) == "none":
                return None
            raise FileNotFoundError(source_path)
        writer = str(storage_item["writer"])
        if writer == "pandas":
            return pd.read_feather(source_path)
        if writer == "pickle":
            return pd.read_pickle(source_path)
        raise ValueError(f"Unsupported writer: {writer}")

    def load(
        self,
        period: int,
        storage: int = 0,
        reload: bool = False,
        verbose: bool = True,
    ) -> PandasDataFrame | None:
        """Load data for a period using the selected storage item."""
        return self.read(period, storage=storage, reload=reload, verbose=verbose)

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
        path = Path(str(storage_item["path"]))
        if self.output is not None:
            path = Path(str(self.output["output_dir"])) / path
        return path

    def _resolve_inpaths(self, metadata: Mapping[str, Any], *, verbose: bool) -> dict[str, Any]:
        resolved = dict(metadata.items())
        for key, value in metadata.items():
            if key.endswith("inpath") and isinstance(value, str):
                resolved[key] = self._resolve_inpath(key, value, verbose=verbose)
        return resolved

    @staticmethod
    def _missing_inpaths(metadata: Mapping[str, Any]) -> list[str]:
        return [
            key
            for key, value in metadata.items()
            if key.endswith("inpath") and value is None
        ]

    def _resolve_inpath(self, key: str, pattern: str, *, verbose: bool) -> Path | None:
        search_dir = self._input_dir()
        matches = list(search_dir.glob(pattern))
        if not matches:
            if verbose:
                print(f"[monthpack] No matches found for {key}: {pattern}")
            return None

        selected = max(matches, key=self._input_path_sort_key)
        if len(matches) > 1 and verbose:
            print(
                f"[monthpack] Multiple matches found for {key}: {pattern}. "
                f"Using {selected}."
            )
        return selected

    def _input_dir(self) -> Path:
        if self.input is not None:
            return Path(str(self.input["input_dir"]))
        return Path()

    @staticmethod
    def _input_path_sort_key(path: Path) -> tuple[str, float]:
        return (path.name, path.stat().st_mtime)

    @staticmethod
    def _resolve_io_config(config: Any, base_dir: Path | None, dir_key: str) -> dict[str, Any]:
        if not isinstance(config, Mapping):
            raise ValueError(f"{dir_key} configuration must be a mapping")
        if dir_key not in config:
            raise ValueError(f"{dir_key} configuration must define {dir_key}")

        resolved = dict(config.items())
        relative = bool(resolved.get("relative", False))
        dir_value = Path(str(resolved[dir_key]))
        if relative:
            if base_dir is None:
                raise ValueError(f"{dir_key} cannot be relative without a source path")
            resolved[dir_key] = str((base_dir / dir_value).resolve())
        else:
            resolved[dir_key] = str(dir_value)
        return resolved

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
