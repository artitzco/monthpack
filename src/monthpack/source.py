"""Source loading and period-aware metadata and I/O resolution."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from string import Formatter
from typing import Any
from typing import Callable
from typing import Mapping

Preprocessor = Callable[["Metadata"], Any]
Postprocessor = Callable[..., Any]


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
    """Represents one configured source with a single implicit storage setup."""

    writer: str
    metadata: tuple[dict[str, Any], ...]
    pandas_type: str | None = None
    persistence: bool = False
    min_period: int | None = None
    collection: str = "list"
    concat_axis: int = 0
    period_label: str | None = None
    period_as_index: bool = False
    name: str | None = None
    input: Path | None = None
    output: Path | None = None
    preprocessor: Preprocessor | None = None
    postprocessor: Postprocessor | None = None
    admin_user: bool = True

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        input: str | Path | None = None,
        output: str | Path | None = None,
        preprocessor: Preprocessor | None = None,
        postprocessor: Postprocessor | None = None,
        admin_user: bool = True,
    ) -> Source:
        """Load a source from a ``source.config.json`` file."""
        source_path = Path(path)
        with source_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        metadata_data = tuple(
            _copy_mapping(entry)
            for entry in payload.get("metadata", [])
        )
        config_root = source_path.parent

        input_path = None
        raw_input = input if input is not None else payload.get("input")
        if raw_input is not None:
            input_path = cls._resolve_directory(raw_input, config_root)

        output_path = None
        raw_output = output if output is not None else payload.get("output")
        if raw_output is not None:
            output_path = cls._resolve_directory(raw_output, config_root)

        return cls(
            writer=str(payload["writer"]),
            metadata=metadata_data,
            pandas_type=(
                str(payload["pandas_type"])
                if payload.get("pandas_type") is not None
                else None
            ),
            persistence=bool(payload.get("persistence", False)),
            min_period=payload.get("min_period"),
            collection=str(payload.get("collection", "list")),
            concat_axis=int(payload.get("concat_axis", 0)),
            period_label=(
                str(payload["period_label"])
                if payload.get("period_label") is not None
                else None
            ),
            period_as_index=bool(payload.get("period_as_index", False)),
            name=(
                str(payload["name"])
                if payload.get("name") is not None
                else None
            ),
            input=input_path,
            output=output_path,
            admin_user=admin_user,
            preprocessor=preprocessor,
            postprocessor=postprocessor,
        )

    def resolve_metastate(
        self,
        period: int | None = None,
        verbose: bool = True,
    ) -> Metadata:
        """Resolve metadata state for one period."""
        return self._resolve_metastate_values(
            period,
            verbose=verbose,
            include_temporary=True,
        )

    def _resolve_metastate_values(
        self,
        period: int | None,
        *,
        verbose: bool,
        include_temporary: bool,
        resolve_inpaths: bool = True,
        resolve_outpaths: bool = True,
    ) -> Metadata:
        """Internal metadata resolution with optional temporary and path control."""
        resolved_period = period if period is not None else None
        resolved = self._metadata_raw(period, include_temporary=include_temporary)
        rendered = self._render_templates(resolved, period=resolved_period)
        values = dict(rendered.items())
        if resolve_inpaths:
            values = self._resolve_inpaths(values, verbose=verbose)
        if resolve_outpaths:
            values = self._resolve_outpaths(values)
        return Metadata(resolved_period, values)

    def set_preprocessor(self, preprocessor: Preprocessor) -> None:
        """Register the single source preprocessor."""
        self.preprocessor = preprocessor

    def set_postprocessor(self, postprocessor: Postprocessor | None) -> None:
        """Register the single source postprocessor."""
        self.postprocessor = postprocessor

    def set_user(self) -> None:
        """Switch to read-only user mode."""
        self.admin_user = False

    def set_admin(self) -> None:
        """Switch back to admin mode."""
        self.admin_user = True

    def save(self, period: int | None, verbose: bool = True) -> Path | None:
        """Build and save processed data for one period."""
        if not self.admin_user:
            raise PermissionError("save is not available in user mode")

        metadata = self._resolve_metastate_values(
            period,
            verbose=verbose,
            include_temporary=not self.persistence,
            resolve_inpaths=not self.persistence or period is None,
        )
        if self.persistence and period is not None:
            return self._save_persistent(metadata, verbose=verbose)
        return self._save_one(metadata)

    def _save_one(self, metadata: Metadata) -> Path | None:
        """Save one processed artifact using already-resolved metadata."""
        value = self._preprocess(metadata)
        if value is None:
            return None
        return self._write_value(value, metadata)

    def _save_persistent(self, target_metadata: Metadata, *, verbose: bool) -> Path | None:
        """Save the requested period using the nearest prior valid preprocessor result."""
        value = self._persistent_value(target_metadata.period, verbose=verbose)
        if value is None:
            return None
        return self._write_value(value, target_metadata)

    def _preprocess(self, metadata: Metadata) -> Any:
        if self.preprocessor is None:
            raise ValueError("preprocessor is not defined for this source")
        return self.preprocessor(metadata)

    def _write_value(self, value: Any, metadata: Metadata) -> Path:
        import pandas as pd

        destination = self._output_path(metadata.outpath)
        destination.parent.mkdir(parents=True, exist_ok=True)

        if self.writer == "pandas":
            if self.pandas_type == "dataframe":
                value.to_feather(destination)
            elif self.pandas_type == "series":
                if not isinstance(value, pd.Series):
                    raise ValueError("pandas_type 'series' requires a pandas Series preprocessor result")
                self._series_to_frame(value).to_feather(destination)
            else:
                raise ValueError(f"Unsupported pandas_type: {self.pandas_type}")
        elif self.writer == "pickle":
            value.to_pickle(destination)
        else:
            raise ValueError(f"Unsupported writer: {self.writer}")
        return destination

    def read(
        self,
        periods: int | None | list[int] | tuple[int, int] = None,
        reload: bool = False,
        skip_error: bool = True,
        verbose: bool = True,
        postprocessor_kwargs: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any | None:
        """Read one period or a collection of periods."""
        normalized_periods = self._normalize_periods(periods)
        if len(normalized_periods) == 1 and (isinstance(periods, int) or periods is None):
            return self.read_one(
                normalized_periods[0],
                reload=reload,
                skip_error=skip_error,
                verbose=verbose,
                postprocessor_kwargs=postprocessor_kwargs,
                **kwargs,
            )

        cache: dict[tuple[str, int | None], Any | None] = {}
        values: list[Any | None] = []
        for period in normalized_periods:
            cache_key = self._read_cache_key(period)
            if cache_key not in cache:
                cache[cache_key] = self.read_one(
                    period,
                    reload=reload,
                    skip_error=skip_error,
                    verbose=verbose,
                    postprocessor_kwargs=postprocessor_kwargs,
                    **kwargs,
                )
            values.append(cache[cache_key])

        return self._collect_reads(normalized_periods, values)

    def read_one(
        self,
        period: int | None,
        reload: bool = False,
        skip_error: bool = True,
        verbose: bool = True,
        postprocessor_kwargs: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any | None:
        """Read one processed artifact and rebuild it first when needed."""
        import pandas as pd

        metadata = self._resolve_metastate_values(
            period,
            verbose=verbose,
            include_temporary=not self.persistence,
            resolve_inpaths=False,
        )
        source_path = self._output_path(metadata.outpath)
        should_build = (reload or not source_path.exists()) and self.admin_user
        if should_build:
            if self.save(period, verbose=verbose) is None:
                return None

        if not source_path.exists():
            return self._missing_read(
                f"Processed file not found: {source_path}",
                skip_error=skip_error,
                verbose=verbose,
            )

        if self.writer == "pandas":
            frame = pd.read_feather(source_path)
            value = self._pandas_value(frame)
            return self._apply_postprocessor(
                value,
                metadata,
                postprocessor_kwargs=self._merge_postprocessor_kwargs(
                    postprocessor_kwargs,
                    kwargs,
                ),
            )
        if self.writer == "pickle":
            value = pd.read_pickle(source_path)
            return self._apply_postprocessor(
                value,
                metadata,
                postprocessor_kwargs=self._merge_postprocessor_kwargs(
                    postprocessor_kwargs,
                    kwargs,
                ),
            )
        raise ValueError(f"Unsupported writer: {self.writer}")

    @staticmethod
    def _merge_postprocessor_kwargs(
        postprocessor_kwargs: Mapping[str, Any] | None,
        overrides: Mapping[str, Any],
    ) -> dict[str, Any]:
        merged = dict(postprocessor_kwargs.items()) if postprocessor_kwargs is not None else {}
        merged.update(overrides)
        return merged

    def _metadata_raw(
        self,
        period: int | None,
        *,
        include_temporary: bool,
    ) -> dict[str, Any]:
        entries = self.metadata
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

        temporary_metadata: list[dict[str, Any]] = []
        if include_temporary:
            temporary_metadata = [
                entry
                for entry in entries
                if _is_period_rule(entry) and _is_temporary(entry) and int(entry["period"]) == period
            ]

        resolved = {}
        for entry in [*base_metadata, *persistent_metadata, *temporary_metadata]:
            resolved.update(self._metadata_payload(entry))
        return resolved

    def _metadata_payload(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in entry.items()
            if key not in {"period", "temporary"}
        }

    def _read_cache_key(self, period: int | None) -> tuple[str, int | None]:
        return ("period", period)

    def _persistent_value(self, period: int, *, verbose: bool) -> Any | None:
        min_period = self._min_period()
        if min_period is None:
            self._warn(
                f"No min_period defined for persistent source: {period}",
                verbose=verbose,
            )
            return None
        if period < min_period:
            self._warn(
                f"No persistent data found for: {period} before min_period: {min_period}",
                verbose=verbose,
            )
            return None

        for candidate_period in self._periods_back_to(period, min_period):
            metadata = self._resolve_metastate_values(
                candidate_period,
                verbose=False,
                include_temporary=False,
            )
            value = self._preprocess(metadata)
            if value is not None:
                return value

        self._warn(
            f"No persistent data found for: {period} down to min_period: {min_period}",
            verbose=verbose,
        )
        return None

    def _min_period(self) -> int | None:
        if self.min_period is None:
            return None
        if not isinstance(self.min_period, int):
            raise TypeError("min_period must be an integer YYYYMM value or None")
        return self.min_period

    def _warn(self, message: str, *, verbose: bool) -> None:
        if verbose and self.admin_user:
            print(f"[monthpack] {message}")

    def _periods_back_to(self, start: int, end: int) -> list[int]:
        periods = [start]
        current = start
        while current != end:
            current = self._advance_period(current, -1)
            if current < end:
                break
            periods.append(current)
        return periods

    def _output_path(self, outpath: Any) -> Path:
        path = Path(str(outpath))
        if path.is_absolute():
            return path
        if self.output is not None:
            path = self.output / path
        return path

    def _resolve_inpaths(self, metadata: Mapping[str, Any], *, verbose: bool) -> dict[str, Any]:
        resolved = dict(metadata.items())
        for key, value in metadata.items():
            if key.endswith("inpath") and isinstance(value, str):
                resolved[key] = self._resolve_inpath(key, value, verbose=verbose)
        return resolved

    def _resolve_outpaths(self, metadata: Mapping[str, Any]) -> dict[str, Any]:
        resolved = dict(metadata.items())
        for key, value in metadata.items():
            if key.endswith("outpath") and isinstance(value, str):
                resolved[key] = self._output_path(value)
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
    ) -> Any | None:
        values = self._apply_period_label(periods, values)
        if self.collection == "list":
            return values
        if self.collection == "dict":
            return dict(zip(periods, values, strict=False))
        if self.collection == "concat":
            return self._concat_reads(values)
        raise ValueError(f"Unsupported collection: {self.collection}")

    def _concat_reads(self, values: list[Any | None]) -> Any | None:
        import pandas as pd

        concat_values = [value for value in values if value is not None]
        if not concat_values:
            return None
        return pd.concat(concat_values, axis=self.concat_axis)

    def _apply_period_label(
        self,
        periods: list[int],
        values: list[Any | None],
    ) -> list[Any | None]:
        if self.period_label is None or self.writer != "pandas":
            return values

        import pandas as pd

        updated_values: list[Any | None] = []
        for period, value in zip(periods, values, strict=False):
            if value is None or not isinstance(value, pd.DataFrame):
                if value is not None and isinstance(value, pd.Series):
                    if self.period_as_index:
                        period_index = pd.Index(
                            [period] * len(value),
                            name=str(self.period_label),
                        )
                        updated_values.append(
                            pd.Series(
                                value.to_numpy(),
                                index=period_index,
                                name=value.name,
                            )
                        )
                    else:
                        updated_values.append(
                            pd.concat({period: value}, names=[str(self.period_label)])
                        )
                else:
                    updated_values.append(value)
                continue
            frame = value.copy()
            if self.period_as_index:
                frame.index = pd.Index([period] * len(frame), name=str(self.period_label))
            else:
                frame[str(self.period_label)] = period
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
        search_dir = self._input_directory()
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

    def _input_directory(self) -> Path:
        if self.input is not None:
            return self.input
        return Path()

    @staticmethod
    def _input_path_sort_key(path: Path) -> tuple[str, float]:
        return (path.name, path.stat().st_mtime)

    @staticmethod
    def _resolve_directory(value: Any, config_root: Path) -> Path:
        if not isinstance(value, (str, Path)):
            raise ValueError("input/output must be declared as a string or pathlib.Path")
        raw_path = str(value)
        if raw_path.startswith("|"):
            resolved_path = (config_root / raw_path.removeprefix("|")).resolve()
        else:
            resolved_path = Path(raw_path).absolute()
        return resolved_path

    def _apply_postprocessor(
        self,
        data: Any,
        metadata: Metadata,
        *,
        postprocessor_kwargs: Mapping[str, Any] | None,
    ) -> Any:
        if self.postprocessor is None:
            return data
        kwargs = dict(postprocessor_kwargs.items()) if postprocessor_kwargs is not None else {}
        return self.postprocessor(metadata, data, **kwargs)

    @staticmethod
    def _series_to_frame(value: Any) -> Any:
        import pandas as pd

        if not isinstance(value, pd.Series):
            raise ValueError("series serialization requires a pandas Series")
        value_name = value.name if value.name is not None else "__monthpack_series_value__"
        return value.rename(value_name).reset_index()

    def _pandas_value(self, frame: Any) -> Any:
        if self.pandas_type == "dataframe":
            return frame
        if self.pandas_type == "series":
            return Source._frame_to_series(frame)
        raise ValueError(f"Unsupported pandas_type: {self.pandas_type}")

    @staticmethod
    def _frame_to_series(frame: Any) -> Any:
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

    def _render_templates(
        self,
        values: Mapping[str, Any],
        *,
        period: int | None,
    ) -> dict[str, Any]:
        context = self._template_context(period)
        return {
            key: self._render_value(value, context)
            for key, value in values.items()
        }

    def _template_context(self, period: int | None) -> dict[str, Any]:
        context: dict[str, Any] = {}
        if period is not None:
            context["period"] = _Period(period)
        if self.name is not None:
            context["name"] = self.name
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
