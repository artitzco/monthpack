"""Independent period-ordered metadata primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class MetadataState:
    """Resolved metadata state for one discrete period or the base case."""

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
class MetadataRule:
    """One metadata rule applied on an ordered discrete timeline."""

    values: dict[str, Any]
    period: int | None = None
    temporary: bool = False

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> MetadataRule:
        copied = dict(payload.items())
        period = copied.pop("period", None)
        temporary = bool(copied.pop("temporary", False))
        return cls(values=copied, period=period, temporary=temporary)


@dataclass(frozen=True)
class Metadata:
    """Generic metadata timeline resolved over discrete ordered periods."""

    rules: tuple[MetadataRule, ...] = field(default_factory=tuple)

    @classmethod
    def from_entries(cls, entries: Iterable[Mapping[str, Any] | MetadataRule]) -> Metadata:
        rules: list[MetadataRule] = []
        for entry in entries:
            if isinstance(entry, MetadataRule):
                rules.append(entry)
            else:
                rules.append(MetadataRule.from_mapping(entry))
        return cls(tuple(rules))

    def periods(self) -> tuple[int, ...]:
        periods = sorted({rule.period for rule in self.rules if rule.period is not None})
        return tuple(periods)

    def resolve(self, period: int | None = None, *, include_temporary: bool = True) -> MetadataState:
        values: dict[str, Any] = {}
        for rule in self.rules:
            if rule.period is None:
                values.update(rule.values)

        if period is None:
            return MetadataState(period=None, values=values)

        periodic_rules = sorted(
            (
                rule
                for rule in self.rules
                if rule.period is not None and not rule.temporary and rule.period <= period
            ),
            key=lambda rule: rule.period,
        )
        for rule in periodic_rules:
            values.update(rule.values)

        if include_temporary:
            temporary_rules = [
                rule
                for rule in self.rules
                if rule.period == period and rule.temporary
            ]
            for rule in temporary_rules:
                values.update(rule.values)

        return MetadataState(period=period, values=values)
