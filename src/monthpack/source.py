"""Source loading and period-aware metadata and storage resolution."""

from __future__ import annotations

from bisect import bisect_right
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

StorageRef = int | str


def _is_period_rule(rule: Mapping[str, Any]) -> bool:
    return "period" in rule


def _is_temporary(rule: Mapping[str, Any]) -> bool:
    return bool(rule.get("temporary", False))


def _copy_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    return dict(mapping.items())


@dataclass(frozen=True)
class Metadata:
    """Resolved metadata for one period or for the base atemporal case."""

    period: int | None
    values: dict[str, Any]

    @property
    def year(self) -> int | None:
        if self.period is None:
            return None
        return self.period // 100

    @property
    def month(self) -> int | None:
        if self.period is None:
            return None
        return self.period % 100

    def __getattr__(self, name: str) -> Any:
        try:
            return self.values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def items(self):
        return self.values.items()

    def keys(self):
        return self.values.keys()

    def to_dict(self) -> dict[str, Any]:
        return dict(self.values.items())


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
    """Represents one configured source and orchestrates metadata, storage, and I/O."""

    source: str
    storage: tuple[dict[str, Any], ...]
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    user: bool = False
    transforms: list[Callable[[Metadata], DataFrame]] = field(default_factory=list)

    @classmethod
    def from_path(cls, path: str | Path) -> Source:
        """Load a source from a ``source.config.json`` file."""
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
        """Build a source from an already-loaded mapping."""
        source = str(payload["source"])
        raw_metadata = payload.get("metadata", [])
        metadata_data = tuple(_copy_mapping(entry) for entry in raw_metadata)
        raw_storage = payload["storage"]
        storage_data = tuple(
            cls._prepare_storage_item(item, metadata_data)
            for item in raw_storage
        )
        cls._validate_storage_names(storage_data)
        source_file = Path(source_path) if source_path is not None else None
        base_path = source_file.parent if source_file is not None else None
        base_dir = base_path
        if "path" in payload:
            path_candidate = Path(str(payload["path"]))
            if base_path is not None and not path_candidate.is_absolute():
                base_dir = (base_path / path_candidate).resolve()
            else:
                base_dir = path_candidate

        input_config = None
        if "input" in payload:
            input_config = cls._resolve_io_config(payload["input"], base_dir, "input_dir")

        output_config = None
        if "output" in payload:
            output_config = cls._resolve_io_config(payload["output"], base_dir, "output_dir")

        return cls(
            source=source,
            storage=storage_data,
            input=input_config,
            output=output_config,
        )

    def resolve_metadata(
        self,
        period: int | None = None,
        storage: StorageRef | None = None,
        verbose: bool = True,
    ) -> Metadata:
        """Resolve metadata for a period and optional storage override."""
        return self._resolve_metadata_values(
            period,
            verbose=verbose,
            include_temporary=True,
            storage=storage,
        )

    def _resolve_metadata_values(
        self,
        period: int | None,
        *,
        verbose: bool,
        include_temporary: bool,
        storage: StorageRef | None,
        resolve_inpaths: bool = True,
    ) -> Metadata:
        """Internal metadata resolution with optional temporary and inpath control."""
        resolved_period = period if period is not None else None
        resolved = self._metadata_raw(
            self._metadata_entries(storage),
            period,
            include_temporary=include_temporary,
        )
        rendered = self._render_templates(resolved, period=resolved_period)
        values = (
            self._resolve_inpaths(rendered, verbose=verbose)
            if resolve_inpaths
            else dict(rendered.items())
        )
        return Metadata(resolved_period, values)

    def set_transforms(
        self,
        transforms: list[Callable[[Metadata], DataFrame]],
    ) -> None:
        """Register one transform per storage position."""
        self.transforms = list(transforms)

    def set_user(self) -> None:
        """Switch to read-only user mode."""
        self.user = True

    def set_admin(self) -> None:
        """Switch back to admin mode."""
        self.user = False

    def save(self, period: int | None, storage: StorageRef = 0, verbose: bool = True) -> Path:
        """Build and save processed data for one period and storage reference."""
        if self.user:
            raise PermissionError("save is not available in user mode")
        storage_item = self.resolve_storage_item(period, storage)
        effective_period = self._effective_period(period, storage_item, storage=storage)
        if period is not None and effective_period is None:
            raise FileNotFoundError(f"No periodic anchor found for: {period}")
        metadata = self._resolve_metadata_values(
            effective_period,
            verbose=verbose,
            include_temporary=not self._is_storage_persistent(storage_item),
            storage=storage,
        )
        return self._save_one(effective_period, storage, metadata)

    def _save_one(self, period: int | None, storage: StorageRef, metadata: Metadata) -> Path:
        """Save one processed artifact using already-resolved metadata."""
        import pandas as pd

        transform = self._transform(storage)
        value = transform(metadata)
        storage_item = self.resolve_storage_item(period, storage)
        destination = self._storage_path(metadata.outpath)
        destination.parent.mkdir(parents=True, exist_ok=True)
        writer = str(storage_item["writer"])
        if writer == "pandas":
            pandas_type = self._pandas_type(storage_item)
            if pandas_type == "dataframe":
                value.to_feather(destination)
            elif pandas_type == "series":
                if not isinstance(value, pd.Series):
                    raise ValueError("pandas_type 'series' requires a pandas Series transform result")
                self._series_to_frame(value).to_feather(destination)
            else:
                raise ValueError(f"Unsupported pandas_type: {pandas_type}")
        elif writer == "pickle":
            value.to_pickle(destination)
        else:
            raise ValueError(f"Unsupported writer: {writer}")
        return destination

    def read(
        self,
        periods: int | None | list[int] | tuple[int, int],
        storage: StorageRef = 0,
        reload: bool = False,
        skip_error: bool = True,
        verbose: bool = True,
    ) -> Any | None:
        """Read one period or a collection of periods for a storage reference."""
        normalized_periods = self._normalize_periods(periods)
        if len(normalized_periods) == 1 and (isinstance(periods, int) or periods is None):
            return self.read_one(
                normalized_periods[0],
                storage=storage,
                reload=reload,
                skip_error=skip_error,
                verbose=verbose,
            )

        cache: dict[tuple[str, int | None], Any | None] = {}
        values: list[Any | None] = []
        for period in normalized_periods:
            storage_item = self.resolve_storage_item(period, storage)
            cache_key = self._read_cache_key(period, storage_item, storage=storage)
            if cache_key not in cache:
                cache[cache_key] = self.read_one(
                    period,
                    storage=storage,
                    reload=reload,
                    skip_error=skip_error,
                    verbose=verbose,
                )
            values.append(cache[cache_key])
        storage_item = self.resolve_storage_item(normalized_periods[0], storage)
        return self._collect_reads(normalized_periods, values, storage_item)

    def read_one(
        self,
        period: int | None,
        storage: StorageRef = 0,
        reload: bool = False,
        skip_error: bool = True,
        verbose: bool = True,
    ) -> Any | None:
        """Read one processed artifact and rebuild it first when needed."""
        import pandas as pd

        storage_item = self.resolve_storage_item(period, storage)
        effective_period = self._effective_period(period, storage_item, storage=storage)
        if period is not None and effective_period is None:
            return self._missing_read(
                f"No periodic anchor found for: {period}",
                skip_error=skip_error,
                verbose=verbose,
            )

        metadata = self._resolve_metadata_values(
            effective_period,
            verbose=verbose,
            include_temporary=not self._is_storage_persistent(storage_item),
            storage=storage,
            resolve_inpaths=False,
        )
        effective_storage_item = self.resolve_storage_item(effective_period, storage)
        source_path = self._storage_path(metadata.outpath)
        should_build = (reload or not source_path.exists()) and not self.user
        if should_build:
            metadata = self._resolve_metadata_values(
                effective_period,
                verbose=verbose,
                include_temporary=not self._is_storage_persistent(storage_item),
                storage=storage,
            )
            self._save_one(effective_period, storage, metadata)
        if not source_path.exists():
            return self._missing_read(
                f"Processed file not found: {source_path}",
                skip_error=skip_error,
                verbose=verbose,
            )
        writer = str(effective_storage_item["writer"])
        if writer == "pandas":
            frame = pd.read_feather(source_path)
            return self._pandas_value(frame, effective_storage_item)
        if writer == "pickle":
            return pd.read_pickle(source_path)
        raise ValueError(f"Unsupported writer: {writer}")

    def resolve_storage(self, period: int | None = None) -> list[dict[str, Any]]:
        """Resolve all storage definitions for one period."""
        return self._render_storage(period)

    def resolve_storage_item(self, period: int | None = None, storage: StorageRef = 0) -> dict[str, Any]:
        """Resolve one storage definition by index or name."""
        return dict(self._storage_item(self.resolve_storage(period), storage))

    def _metadata_entries(self, storage: StorageRef | None) -> tuple[dict[str, Any], ...]:
        if storage is None:
            if len(self.storage) == 1:
                return tuple(self.storage[0].get("metadata", ()))
            raise ValueError("storage must be specified when source has multiple storage items")
        return tuple(self._storage_item(self.storage, storage).get("metadata", ()))

    def _metadata_raw(
        self,
        entries: tuple[dict[str, Any], ...],
        period: int | None,
        *,
        include_temporary: bool,
    ) -> dict[str, Any]:
        base_metadata = [entry for entry in entries if not _is_period_rule(entry)]
        if period is None:
            resolved: dict[str, Any] = {}
            for entry in base_metadata:
                resolved.update(self._metadata_payload(entry))
            return resolved
        persistent_metadata = sorted(
            (
                entry
                for entry in entries
                if _is_period_rule(entry)
                and not _is_temporary(entry)
                and int(entry["period"]) <= period
            ),
            key=lambda entry: int(entry["period"]),
        )
        temporary_metadata = []
        if include_temporary:
            temporary_metadata = [
                entry
                for entry in entries
                if _is_period_rule(entry) and _is_temporary(entry) and int(entry["period"]) == period
            ]

        resolved: dict[str, Any] = {}
        for entry in [*base_metadata, *persistent_metadata, *temporary_metadata]:
            resolved.update(self._metadata_payload(entry))
        return resolved

    def _periodic_periods(self, storage: StorageRef | None = None) -> list[int]:
        return sorted(
            {
                int(entry["period"])
                for entry in self._metadata_entries(storage)
                if _is_period_rule(entry) and not _is_temporary(entry)
            }
        )

    def _metadata_payload(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in entry.items()
            if key not in {"period", "temporary"}
        }

    def _render_storage(self, period: int | None) -> list[dict[str, Any]]:
        return [
            {
                key: (value if key == "metadata" else self._render_value(value, self._template_context(period)))
                for key, value in item.items()
            }
            for item in self.storage
        ]

    @staticmethod
    def _is_storage_persistent(storage_item: Mapping[str, Any]) -> bool:
        return bool(storage_item.get("persistence", False))

    def _effective_period(
        self,
        period: int | None,
        storage_item: Mapping[str, Any],
        *,
        storage: StorageRef | None = None,
    ) -> int | None:
        if not self._is_storage_persistent(storage_item):
            return period
        if period is None:
            return None

        periodic_periods = self._periodic_periods(storage)
        index = bisect_right(periodic_periods, period) - 1
        if index < 0:
            return None
        return periodic_periods[index]

    def _read_cache_key(
        self,
        period: int | None,
        storage_item: Mapping[str, Any],
        *,
        storage: StorageRef | None = None,
    ) -> tuple[str, int | None]:
        if self._is_storage_persistent(storage_item):
            return ("anchor", self._effective_period(period, storage_item, storage=storage))
        return ("period", period)

    def _storage_item(self, value: Any, storage: StorageRef) -> Mapping[str, Any]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("storage must contain at least one item")
        if isinstance(storage, int) and 0 <= storage < len(value):
            return value[storage]
        if isinstance(storage, str):
            for item in value:
                if str(item.get("name")) == storage:
                    return item
            raise ValueError(f"storage name is not defined: {storage}")
        raise ValueError("storage must contain at least one item")

    def _storage_path(self, outpath: Any) -> Path:
        path = Path(str(outpath))
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
    def _missing_read(message: str, *, skip_error: bool, verbose: bool) -> None:
        if skip_error:
            if verbose:
                print(f"[monthpack] {message}")
            return None
        raise FileNotFoundError(message)

    def _collect_reads(
        self,
        periods: list[int],
        values: list[Any | None],
        storage_item: Mapping[str, Any],
    ) -> Any | None:
        values = self._apply_period_label(periods, values, storage_item)
        collection = str(storage_item.get("collection", "list"))
        if collection == "list":
            return values
        if collection == "dict":
            return dict(zip(periods, values, strict=False))
        if collection == "concat":
            return self._concat_reads(values, storage_item)
        raise ValueError(f"Unsupported collection: {collection}")

    @staticmethod
    def _concat_reads(values: list[Any | None], storage_item: Mapping[str, Any]) -> Any | None:
        import pandas as pd

        concat_values = [value for value in values if value is not None]
        if not concat_values:
            return None
        axis = int(storage_item.get("concat_axis", 0))
        return pd.concat(concat_values, axis=axis)

    @staticmethod
    def _apply_period_label(
        periods: list[int],
        values: list[Any | None],
        storage_item: Mapping[str, Any],
    ) -> list[Any | None]:
        period_label = storage_item.get("period_label")
        writer = str(storage_item.get("writer", ""))
        if period_label is None or writer != "pandas":
            return values

        import pandas as pd

        updated_values: list[Any | None] = []
        for period, value in zip(periods, values, strict=False):
            if value is None or not isinstance(value, pd.DataFrame):
                if value is not None and isinstance(value, pd.Series):
                    updated_values.append(
                        pd.concat({period: value}, names=[str(period_label)])
                    )
                else:
                    updated_values.append(value)
                continue
            frame = value.copy()
            frame[str(period_label)] = period
            updated_values.append(frame)
        return updated_values

    def _normalize_periods(self, periods: int | None | list[int] | tuple[int, int]) -> list[int | None]:
        if periods is None:
            return [None]
        if isinstance(periods, int):
            return [periods]
        if isinstance(periods, tuple) and len(periods) == 2:
            return self._period_range(periods[0], periods[1])
        return list(periods)

    def _period_range(self, start: int, end: int) -> list[int]:
        periods = [start]
        if start == end:
            return periods
        current = start
        step = 1 if start < end else -1
        while current != end:
            current = self._advance_period(current, step)
            periods.append(current)
        return periods

    @staticmethod
    def _advance_period(period: int, step: int) -> int:
        year = period // 100
        month = period % 100
        month += step
        if month == 13:
            return (year + 1) * 100 + 1
        if month == 0:
            return (year - 1) * 100 + 12
        return year * 100 + month

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

    @staticmethod
    def _prepare_storage_item(
        item: Mapping[str, Any],
        metadata_data: tuple[dict[str, Any], ...],
    ) -> dict[str, Any]:
        storage_item = _copy_mapping(item)
        storage_metadata = tuple(_copy_mapping(entry) for entry in item.get("metadata", []))
        storage_item["metadata"] = tuple(
            _copy_mapping(entry)
            for entry in [*metadata_data, *storage_metadata]
        )
        return storage_item

    @staticmethod
    def _validate_storage_names(storage_data: tuple[dict[str, Any], ...]) -> None:
        names = [
            str(item["name"])
            for item in storage_data
            if item.get("name") is not None
        ]
        duplicates = {
            name
            for name in names
            if names.count(name) > 1
        }
        if duplicates:
            duplicate_names = ", ".join(sorted(duplicates))
            raise ValueError(f"storage names must be unique: {duplicate_names}")

    def _transform(self, storage: StorageRef) -> Callable[[Metadata], DataFrame]:
        storage_index = self._storage_index(storage)
        if 0 <= storage_index < len(self.transforms):
            return self.transforms[storage_index]
        raise ValueError("transform is not defined for the requested storage index")

    def _storage_index(self, storage: StorageRef) -> int:
        if isinstance(storage, int):
            return storage
        for index, item in enumerate(self.storage):
            if str(item.get("name")) == storage:
                return index
        raise ValueError(f"storage name is not defined: {storage}")

    @staticmethod
    def _series_to_frame(value: PandasDataFrame | Any) -> PandasDataFrame:
        import pandas as pd

        if not isinstance(value, pd.Series):
            raise ValueError("series serialization requires a pandas Series")
        value_name = value.name if value.name is not None else "__monthpack_series_value__"
        return value.rename(value_name).reset_index()

    @staticmethod
    def _pandas_value(frame: PandasDataFrame, storage_item: Mapping[str, Any]) -> Any:
        pandas_type = Source._pandas_type(storage_item)
        if pandas_type == "dataframe":
            return frame
        if pandas_type == "series":
            return Source._frame_to_series(frame)
        raise ValueError(f"Unsupported pandas_type: {pandas_type}")

    @staticmethod
    def _pandas_type(storage_item: Mapping[str, Any]) -> str:
        return str(storage_item["pandas_type"])

    @staticmethod
    def _frame_to_series(frame: PandasDataFrame) -> Any:
        if frame.shape[1] == 0:
            raise ValueError("series deserialization requires at least one column")
        index_columns = list(frame.columns[:-1])
        value_column = frame.columns[-1]
        if index_columns:
            series = frame.set_index(index_columns).iloc[:, -1]
            if len(index_columns) == 1:
                series.index = series.index.get_level_values(0)
        else:
            series = frame.iloc[:, -1]
        series.name = None if value_column == "__monthpack_series_value__" else value_column
        return series

    def _render_templates(self, values: Mapping[str, Any], *, period: int | None) -> dict[str, Any]:
        context = self._template_context(period)
        return {
            key: self._render_value(value, context)
            for key, value in values.items()
        }

    def _template_context(self, period: int | None) -> dict[str, Any]:
        context = {
            "source": self.source,
        }
        if period is not None:
            context["period"] = _Period(period)
        return context

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
        root_names = {
            field_name.split(".", 1)[0].split("[", 1)[0]
            for field_name in field_names
        }
        if not root_names.issubset(context):
            return template
        render_context = {name: context[name] for name in root_names}
        return template.format(**render_context)
