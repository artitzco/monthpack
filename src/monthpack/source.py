"""Source loading and period-aware metadata resolution."""

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


DEFAULT_OUTPATH = (
    {
        "path": "{period.year}/{period}_{source}.bin",
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
    outpath_data: tuple[dict[str, Any], ...]
    metadata_data: tuple[dict[str, Any], ...]
    root: Path | None = None
    transforms: list[Callable[[dict[str, Any]], DataFrame]] = field(default_factory=list)

    @classmethod
    def from_path(cls, path: str | Path) -> Source:
        """Load source configuration from a JSON file."""
        source_path = Path(path)
        with source_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if "outpath" not in payload:
            payload["outpath"] = [dict(item) for item in DEFAULT_OUTPATH]
            with source_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
        return cls.from_dict(payload, root=source_path.parent)

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        root: str | Path | None = None,
    ) -> Source:
        """Build a source object from a mapping."""
        source = str(payload["source"])
        raw_outpath = payload.get("outpath", DEFAULT_OUTPATH)
        outpath_data = tuple(_copy_mapping(item) for item in raw_outpath)
        raw_metadata = payload.get("metadata", [])
        metadata_data = tuple(_copy_mapping(entry) for entry in raw_metadata)
        resolved_root = Path(root) if root is not None else None
        return cls(
            source=source,
            outpath_data=outpath_data,
            metadata_data=metadata_data,
            root=resolved_root,
        )

    def metadata(self, period: int | None = None) -> dict[str, Any]:
        """Resolve metadata values for a specific period."""
        resolved = self._metadata_raw(period)
        resolved["outpath"] = self._render_outpath(period)
        return self._render_templates(resolved, period=period)

    def set_transforms(
        self,
        transforms: list[Callable[[dict[str, Any]], DataFrame]],
    ) -> None:
        """Register output transforms by outpath position."""
        self.transforms = list(transforms)

    def save(self, period: int, outpath: int = 0) -> Path:
        """Build and save data for a period using the selected outpath."""
        metadata = self.metadata(period)
        transform = self._transform(outpath)
        dataframe = transform(metadata)
        outpath_item = self._outpath_item(metadata["outpath"], outpath)
        destination = self._output_path(outpath_item)
        destination.parent.mkdir(parents=True, exist_ok=True)
        writer = str(outpath_item["writer"])
        if writer == "pandas":
            dataframe.to_feather(destination)
        elif writer == "pickle":
            dataframe.to_pickle(destination)
        else:
            raise ValueError(f"Unsupported writer: {writer}")
        return destination

    def read(self, period: int, outpath: int = 0, reload: bool = False) -> PandasDataFrame:
        """Read data for a period, building it first when needed."""
        import pandas as pd

        metadata = self.metadata(period)
        outpath_item = self._outpath_item(metadata["outpath"], outpath)
        source_path = self._output_path(outpath_item)
        if reload or not source_path.exists():
            self.save(period, outpath)
        writer = str(outpath_item["writer"])
        if writer == "pandas":
            return pd.read_feather(source_path)
        if writer == "pickle":
            return pd.read_pickle(source_path)
        raise ValueError(f"Unsupported writer: {writer}")

    def _metadata_raw(self, period: int | None) -> dict[str, Any]:
        base_entries = [entry for entry in self.metadata_data if not _is_period_rule(entry)]
        resolved_period = self._resolve_period(period)
        persistent_entries = sorted(
            (
                entry
                for entry in self.metadata_data
                if _is_period_rule(entry)
                and not _is_temporary(entry)
                and int(entry["period"]) <= resolved_period
            ),
            key=lambda entry: int(entry["period"]),
        )
        temporary_entries = [
            entry
            for entry in self.metadata_data
            if _is_period_rule(entry) and _is_temporary(entry) and int(entry["period"]) == resolved_period
        ]

        resolved: dict[str, Any] = {}
        for entry in [*base_entries, *persistent_entries, *temporary_entries]:
            resolved.update(self._entry_payload(entry))
        return resolved

    def _resolve_period(self, period: int | None) -> int:
        if period is not None:
            return period

        periods = [
            int(entry["period"])
            for entry in self.metadata_data
            if _is_period_rule(entry) and not _is_temporary(entry)
        ]
        if periods:
            return max(periods)
        return 0

    def _entry_payload(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in entry.items()
            if key not in {"period", "temporary"}
        }

    def _render_outpath(self, period: int | None) -> list[dict[str, Any]]:
        return [
            self._render_value(item, self._template_context(period))
            for item in self.outpath_data
        ]

    def _outpath_item(self, value: Any, outpath: int) -> Mapping[str, Any]:
        if isinstance(value, list) and 0 <= outpath < len(value):
            return value[outpath]
        raise ValueError("outpath must contain at least one item")

    def _output_path(self, outpath_item: Mapping[str, Any]) -> Path:
        path = Path(str(outpath_item["path"]))
        if self.root is not None:
            path = self.root / "output" / path
        return path

    def _transform(self, outpath: int) -> Callable[[dict[str, Any]], DataFrame]:
        if 0 <= outpath < len(self.transforms):
            return self.transforms[outpath]
        raise ValueError("transform is not defined for the requested outpath index")

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
