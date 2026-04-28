"""Source manager for grouped source access."""

from __future__ import annotations

from typing import Any
from typing import Iterator

from monthpack.source import Source


class SourceManager:
    """Manage a collection of ``Source`` objects."""

    def __init__(self) -> None:
        self._sources: list[Source] = []

    def add_source(self, source: Source) -> SourceManager:
        """Register one source and return the same manager instance."""
        if source.name is not None and any(
            existing.name == source.name for existing in self._sources
        ):
            raise ValueError(f"Source name already registered: {source.name}")
        self._sources.append(source)
        return self

    def get_source(self, identifier: str | int) -> Source:
        """Return a source by name or insertion index."""
        if isinstance(identifier, int):
            if identifier < 0 or identifier >= len(self._sources):
                raise IndexError(f"Source index out of range: {identifier}")
            return self._sources[identifier]

        if isinstance(identifier, str):
            for source in self._sources:
                if source.name == identifier:
                    return source
            raise KeyError(f"Source name not found: {identifier}")

        raise TypeError("identifier must be a source name (str) or insertion index (int)")

    def set_user(self) -> None:
        """Set all registered sources to user mode."""
        for source in self._sources:
            source.set_user()

    def set_admin(self) -> None:
        """Set all registered sources to admin mode."""
        for source in self._sources:
            source.set_admin()

    def read(
        self,
        identifier: str | int,
        periods,
        reload: bool = False,
        skip_error: bool = True,
        verbose: bool = True,
        postprocessor_kwargs=None,
    ):
        """Proxy source reads by identifier."""
        source = self.get_source(identifier)
        return source.read(
            periods,
            reload=reload,
            skip_error=skip_error,
            verbose=verbose,
            postprocessor_kwargs=postprocessor_kwargs,
        )

    def list_sources(self) -> list[dict[str, Any]]:
        """List registered sources with insertion index and name."""
        return [
            {"index": index, "name": source.name}
            for index, source in enumerate(self._sources)
        ]

    def __len__(self) -> int:
        return len(self._sources)

    def __getitem__(self, identifier: str | int) -> Source:
        return self.get_source(identifier)

    def __iter__(self) -> Iterator[Source]:
        return iter(self._sources)

    def remove_source(self, identifier: str | int) -> SourceManager:
        """Remove a source by name or insertion index."""
        if isinstance(identifier, int):
            if identifier < 0 or identifier >= len(self._sources):
                raise IndexError(f"Source index out of range: {identifier}")
            self._sources.pop(identifier)
            return self

        if isinstance(identifier, str):
            for index, source in enumerate(self._sources):
                if source.name == identifier:
                    self._sources.pop(index)
                    return self
            raise KeyError(f"Source name not found: {identifier}")

        raise TypeError("identifier must be a source name (str) or insertion index (int)")
