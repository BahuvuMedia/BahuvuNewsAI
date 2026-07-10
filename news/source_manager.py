# news/source_manager.py

"""
BahuvuNewsAI - News Source Management Foundation
Version: 1.0

This module provides the common collection contract and central source
registry used by all news collectors.

Future collectors such as RSSCollector, APICollector, WebCollector, and
GovernmentCollector should inherit from BaseNewsCollector.

The canonical source and article data structures remain in news.models.
This module does not redefine those models.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Iterable, Iterator, Mapping

from news.models import (
    NewsArticle,
    NewsSource,
    SourceStatus,
    SourceType,
)


LOGGER = logging.getLogger("BahuvuNewsAI.news.source_manager")


# ==========================================================
# TIME HELPERS
# ==========================================================


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""

    return datetime.now(timezone.utc)


# ==========================================================
# EXCEPTIONS
# ==========================================================


class SourceManagerError(RuntimeError):
    """Base exception for source-management failures."""


class SourceNotFoundError(SourceManagerError):
    """Raised when a requested source is not registered."""


class DuplicateSourceError(SourceManagerError):
    """Raised when a source ID is already registered."""


class CollectorError(SourceManagerError):
    """Raised when a collector cannot complete an operation."""


class CollectorConnectionError(CollectorError):
    """Raised when a collector cannot connect to its source."""


class CollectorFetchError(CollectorError):
    """Raised when a collector cannot fetch source content."""


class CollectorNormalizationError(CollectorError):
    """Raised when fetched data cannot be normalized."""


# ==========================================================
# COLLECTION RESULT
# ==========================================================


@dataclass(slots=True)
class CollectionResult:
    """
    Result produced by one collector fetch operation.

    A collection attempt may complete successfully while returning no
    articles. Operational failures are represented with success=False.
    """

    source_id: str
    source_name: str
    source_type: SourceType

    success: bool = True
    articles: list[NewsArticle] = field(default_factory=list)
    raw_items_count: int = 0
    rejected_items_count: int = 0

    started_at: datetime = field(default_factory=utc_now)
    completed_at: datetime | None = None
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.source_id = str(self.source_id).strip()
        self.source_name = str(self.source_name).strip()

        if not isinstance(self.source_type, SourceType):
            self.source_type = SourceType(str(self.source_type))

        self.articles = list(self.articles or [])
        self.raw_items_count = int(self.raw_items_count)
        self.rejected_items_count = int(self.rejected_items_count)
        self.error = str(self.error or "").strip()
        self.metadata = dict(self.metadata or {})

        if not self.source_id:
            raise ValueError("CollectionResult.source_id cannot be empty.")

        if not self.source_name:
            raise ValueError("CollectionResult.source_name cannot be empty.")

        if self.raw_items_count < 0:
            raise ValueError(
                "CollectionResult.raw_items_count cannot be negative."
            )

        if self.rejected_items_count < 0:
            raise ValueError(
                "CollectionResult.rejected_items_count cannot be negative."
            )

        if self.completed_at is not None:
            self.completed_at = self._ensure_utc(self.completed_at)

        self.started_at = self._ensure_utc(self.started_at)

    @staticmethod
    def _ensure_utc(value: datetime) -> datetime:
        """Normalize a datetime to timezone-aware UTC."""

        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)

        return value.astimezone(timezone.utc)

    @property
    def article_count(self) -> int:
        """Return the number of normalized articles."""

        return len(self.articles)

    @property
    def duration_seconds(self) -> float | None:
        """Return elapsed collection time when the result is complete."""

        if self.completed_at is None:
            return None

        return max(
            0.0,
            (self.completed_at - self.started_at).total_seconds(),
        )

    def complete(self) -> None:
        """Mark the collection result as completed."""

        self.completed_at = utc_now()

    def fail(self, error: str) -> None:
        """Mark the collection result as failed."""

        self.success = False
        self.error = str(error or "Unknown collection error").strip()
        self.completed_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        """Serialize the result into JSON-compatible data."""

        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_type": self.source_type.value,
            "success": self.success,
            "article_count": self.article_count,
            "raw_items_count": self.raw_items_count,
            "rejected_items_count": self.rejected_items_count,
            "started_at": self.started_at.isoformat(),
            "completed_at": (
                self.completed_at.isoformat()
                if self.completed_at is not None
                else None
            ),
            "duration_seconds": self.duration_seconds,
            "error": self.error,
            "metadata": dict(self.metadata),
            "articles": [
                article.to_dict()
                for article in self.articles
            ],
        }


# ==========================================================
# HEALTH RESULT
# ==========================================================


@dataclass(slots=True)
class SourceHealth:
    """Operational health information for one configured source."""

    source_id: str
    source_name: str
    status: SourceStatus
    healthy: bool

    checked_at: datetime = field(default_factory=utc_now)
    message: str = ""
    response_time_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.source_id = str(self.source_id).strip()
        self.source_name = str(self.source_name).strip()
        self.message = str(self.message or "").strip()
        self.metadata = dict(self.metadata or {})

        if not isinstance(self.status, SourceStatus):
            self.status = SourceStatus(str(self.status))

        if self.response_time_seconds is not None:
            self.response_time_seconds = max(
                0.0,
                float(self.response_time_seconds),
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize health information."""

        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "status": self.status.value,
            "healthy": self.healthy,
            "checked_at": self.checked_at.isoformat(),
            "message": self.message,
            "response_time_seconds": self.response_time_seconds,
            "metadata": dict(self.metadata),
        }


# ==========================================================
# BASE COLLECTOR
# ==========================================================


class BaseNewsCollector(ABC):
    """
    Abstract base class for every BahuvuNewsAI news collector.

    Concrete collectors are responsible for:

    1. Connecting to the configured source.
    2. Fetching raw source data.
    3. Validating raw items.
    4. Normalizing accepted items into NewsArticle objects.
    5. Closing any resources they opened.
    """

    supported_source_types: frozenset[SourceType] = frozenset()

    def __init__(self, source: NewsSource) -> None:
        if not isinstance(source, NewsSource):
            raise TypeError(
                "source must be an instance of news.models.NewsSource."
            )

        self.source = source
        self._connected = False
        self._closed = False

        self._validate_supported_source_type()

    def _validate_supported_source_type(self) -> None:
        """Ensure the collector supports the configured source type."""

        if (
            self.supported_source_types
            and self.source.source_type not in self.supported_source_types
        ):
            supported = ", ".join(
                sorted(item.value for item in self.supported_source_types)
            )

            raise ValueError(
                f"{self.__class__.__name__} does not support source type "
                f"'{self.source.source_type.value}'. "
                f"Supported types: {supported}."
            )

    @property
    def is_connected(self) -> bool:
        """Return whether the collector currently has an open connection."""

        return self._connected and not self._closed

    @property
    def is_closed(self) -> bool:
        """Return whether the collector has been closed."""

        return self._closed

    def _mark_connected(self) -> None:
        """Record a successful collector connection."""

        self._connected = True
        self._closed = False

    def _mark_closed(self) -> None:
        """Record that collector resources have been closed."""

        self._connected = False
        self._closed = True

    def ensure_available(self) -> None:
        """Ensure this source is eligible for collection."""

        if not self.source.is_active:
            raise CollectorError(
                f"Source '{self.source.name}' is not active. "
                f"Current status: {self.source.status.value}."
            )

        if self.is_closed:
            raise CollectorError(
                f"{self.__class__.__name__} has already been closed."
            )

    @abstractmethod
    def connect(self) -> None:
        """Open resources required to communicate with the source."""

    @abstractmethod
    def fetch(self) -> Any:
        """Fetch raw content from the configured source."""

    @abstractmethod
    def validate_item(self, raw_item: Any) -> bool:
        """Return whether one raw item is suitable for normalization."""

    @abstractmethod
    def normalize_item(self, raw_item: Any) -> NewsArticle:
        """Convert one valid raw item into a canonical NewsArticle."""

    @abstractmethod
    def health_check(self) -> SourceHealth:
        """Check whether the configured source is operational."""

    @abstractmethod
    def close(self) -> None:
        """Release network sessions and other collector resources."""

    def iter_raw_items(self, raw_payload: Any) -> Iterable[Any]:
        """
        Return individual items from a fetched payload.

        Collectors may override this when a provider returns an envelope,
        pagination object, feed structure, or other custom payload.
        """

        if raw_payload is None:
            return ()

        if isinstance(raw_payload, Mapping):
            return (raw_payload,)

        if isinstance(raw_payload, (str, bytes)):
            return (raw_payload,)

        try:
            return iter(raw_payload)
        except TypeError:
            return (raw_payload,)

    def collect(self) -> CollectionResult:
        """
        Execute the standard collection lifecycle.

        This method is intentionally shared by every concrete collector so
        source-state updates, logging, rejection counts, and error handling
        remain consistent throughout the project.
        """

        self.ensure_available()

        result = CollectionResult(
            source_id=self.source.source_id,
            source_name=self.source.name,
            source_type=self.source.source_type,
        )

        LOGGER.info(
            "Collection started | source=%s | type=%s",
            self.source.name,
            self.source.source_type.value,
        )

        try:
            if not self.is_connected:
                self.connect()

            if not self.is_connected:
                raise CollectorConnectionError(
                    f"{self.__class__.__name__}.connect() completed "
                    "without marking the collector as connected."
                )

            raw_payload = self.fetch()
            raw_items = self.iter_raw_items(raw_payload)

            for raw_item in raw_items:
                result.raw_items_count += 1

                try:
                    if not self.validate_item(raw_item):
                        result.rejected_items_count += 1
                        continue

                    article = self.normalize_item(raw_item)

                    if not isinstance(article, NewsArticle):
                        raise CollectorNormalizationError(
                            "normalize_item() must return NewsArticle."
                        )

                    result.articles.append(article)

                except Exception as item_error:
                    result.rejected_items_count += 1

                    LOGGER.warning(
                        "Raw item rejected | source=%s | error=%s",
                        self.source.name,
                        item_error,
                    )

            result.complete()
            self.source.mark_fetch_success(result.completed_at)

            LOGGER.info(
                "Collection completed | source=%s | "
                "raw=%s | articles=%s | rejected=%s",
                self.source.name,
                result.raw_items_count,
                result.article_count,
                result.rejected_items_count,
            )

            return result

        except Exception as error:
            message = (
                f"{error.__class__.__name__}: {error}"
                if str(error)
                else error.__class__.__name__
            )

            result.fail(message)
            self.source.mark_fetch_failure(
                message,
                result.completed_at,
            )

            LOGGER.exception(
                "Collection failed | source=%s | error=%s",
                self.source.name,
                message,
            )

            return result

    def __enter__(self) -> BaseNewsCollector:
        """Support collector use as a context manager."""

        self.ensure_available()

        if not self.is_connected:
            self.connect()

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        """Close collector resources when leaving a context block."""

        self.close()


# ==========================================================
# SOURCE MANAGER
# ==========================================================


class SourceManager:
    """
    Central registry for configured news sources.

    The manager controls source registration and lookup. It does not perform
    network collection itself; that responsibility belongs to collector
    implementations.
    """

    def __init__(
        self,
        sources: Iterable[NewsSource] | None = None,
    ) -> None:
        self._sources: dict[str, NewsSource] = {}

        for source in sources or ():
            self.register(source)

    def __len__(self) -> int:
        """Return the number of registered sources."""

        return len(self._sources)

    def __contains__(self, source_id: object) -> bool:
        """Return whether a source ID is registered."""

        return str(source_id) in self._sources

    def __iter__(self) -> Iterator[NewsSource]:
        """Iterate through registered sources."""

        return iter(self.list_sources())

    def register(
        self,
        source: NewsSource,
        *,
        replace: bool = False,
    ) -> NewsSource:
        """
        Register a canonical NewsSource.

        Set replace=True only when intentionally replacing a source with the
        same source_id.
        """

        if not isinstance(source, NewsSource):
            raise TypeError(
                "source must be an instance of news.models.NewsSource."
            )

        source.validate()

        if source.source_id in self._sources and not replace:
            raise DuplicateSourceError(
                f"Source ID '{source.source_id}' is already registered."
            )

        self._sources[source.source_id] = source

        LOGGER.info(
            "Source registered | id=%s | name=%s | type=%s",
            source.source_id,
            source.name,
            source.source_type.value,
        )

        return source

    def register_many(
        self,
        sources: Iterable[NewsSource],
        *,
        replace: bool = False,
    ) -> list[NewsSource]:
        """Register multiple sources and return the registered objects."""

        registered: list[NewsSource] = []

        for source in sources:
            registered.append(
                self.register(source, replace=replace)
            )

        return registered

    def get(self, source_id: str) -> NewsSource:
        """Return one registered source by source ID."""

        normalized_id = str(source_id).strip()

        try:
            return self._sources[normalized_id]
        except KeyError as error:
            raise SourceNotFoundError(
                f"Source ID '{normalized_id}' is not registered."
            ) from error

    def find_by_name(self, name: str) -> list[NewsSource]:
        """Return sources whose names match case-insensitively."""

        normalized_name = str(name).strip().casefold()

        if not normalized_name:
            return []

        return [
            source
            for source in self._sources.values()
            if source.name.casefold() == normalized_name
        ]

    def remove(self, source_id: str) -> NewsSource:
        """Remove and return one registered source."""

        source = self.get(source_id)
        del self._sources[source.source_id]

        LOGGER.info(
            "Source removed | id=%s | name=%s",
            source.source_id,
            source.name,
        )

        return source

    def clear(self) -> None:
        """Remove all registered sources."""

        self._sources.clear()
        LOGGER.info("All registered news sources were cleared.")

    def list_sources(
        self,
        *,
        status: SourceStatus | str | None = None,
        source_type: SourceType | str | None = None,
        active_only: bool = False,
    ) -> list[NewsSource]:
        """
        Return sources with optional status and type filtering.

        Results are ordered by descending priority, followed by source name.
        """

        normalized_status: SourceStatus | None = None
        normalized_type: SourceType | None = None

        if status is not None:
            normalized_status = (
                status
                if isinstance(status, SourceStatus)
                else SourceStatus(str(status))
            )

        if source_type is not None:
            normalized_type = (
                source_type
                if isinstance(source_type, SourceType)
                else SourceType(str(source_type))
            )

        sources = list(self._sources.values())

        if active_only:
            sources = [
                source
                for source in sources
                if source.is_active
            ]

        if normalized_status is not None:
            sources = [
                source
                for source in sources
                if source.status == normalized_status
            ]

        if normalized_type is not None:
            sources = [
                source
                for source in sources
                if source.source_type == normalized_type
            ]

        return sorted(
            sources,
            key=lambda source: (
                -source.priority,
                source.name.casefold(),
            ),
        )

    def active_sources(self) -> list[NewsSource]:
        """Return all active sources ordered by priority."""

        return self.list_sources(active_only=True)

    def pause(self, source_id: str) -> NewsSource:
        """Pause one registered source."""

        source = self.get(source_id)
        source.status = SourceStatus.PAUSED
        source.updated_at = utc_now()

        LOGGER.info(
            "Source paused | id=%s | name=%s",
            source.source_id,
            source.name,
        )

        return source

    def activate(self, source_id: str) -> NewsSource:
        """Activate one registered source."""

        source = self.get(source_id)
        source.status = SourceStatus.ACTIVE
        source.last_error = ""
        source.updated_at = utc_now()

        LOGGER.info(
            "Source activated | id=%s | name=%s",
            source.source_id,
            source.name,
        )

        return source

    def deactivate(self, source_id: str) -> NewsSource:
        """Deactivate one registered source."""

        source = self.get(source_id)
        source.status = SourceStatus.INACTIVE
        source.updated_at = utc_now()

        LOGGER.info(
            "Source deactivated | id=%s | name=%s",
            source.source_id,
            source.name,
        )

        return source

    def summary(self) -> dict[str, Any]:
        """Return a compact operational summary of registered sources."""

        status_counts = {
            status.value: 0
            for status in SourceStatus
        }

        type_counts = {
            source_type.value: 0
            for source_type in SourceType
        }

        for source in self._sources.values():
            status_counts[source.status.value] += 1
            type_counts[source.source_type.value] += 1

        return {
            "total_sources": len(self._sources),
            "active_sources": len(self.active_sources()),
            "status_counts": status_counts,
            "type_counts": type_counts,
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize the complete source registry."""

        return {
            "sources": [
                source.to_dict()
                for source in self.list_sources()
            ],
            "summary": self.summary(),
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> SourceManager:
        """Restore a source manager from serialized source data."""

        raw_sources = data.get("sources") or []

        if not isinstance(raw_sources, list):
            raise ValueError(
                "SourceManager serialized data must contain a sources list."
            )

        sources = [
            NewsSource.from_dict(item)
            for item in raw_sources
        ]

        return cls(sources)


# ==========================================================
# MODULE SELF-TEST
# ==========================================================


def _run_self_test() -> None:
    """Run a local, network-free source-manager validation."""

    sample_source = NewsSource(
        name="Bahuvu Test Feed",
        source_type=SourceType.RSS,
        url="https://example.com/news.xml",
        priority=80,
        reliability_score=75.0,
        fetch_interval_minutes=30,
    )

    manager = SourceManager()
    manager.register(sample_source)

    assert len(manager) == 1
    assert manager.get(sample_source.source_id) is sample_source
    assert manager.active_sources() == [sample_source]
    assert manager.find_by_name("bahuvu test feed") == [sample_source]

    manager.pause(sample_source.source_id)
    assert sample_source.status == SourceStatus.PAUSED
    assert manager.active_sources() == []

    manager.activate(sample_source.source_id)
    assert sample_source.status == SourceStatus.ACTIVE
    assert manager.active_sources() == [sample_source]

    serialized = manager.to_dict()
    restored = SourceManager.from_dict(serialized)

    assert len(restored) == 1
    assert (
        restored.get(sample_source.source_id).name
        == sample_source.name
    )

    print("News source manager initialized successfully.")
    print(f"Registered sources: {len(manager)}")
    print(f"Active sources: {len(manager.active_sources())}")
    print(f"Source ID: {sample_source.source_id}")
    print(f"Source type: {sample_source.source_type.value}")
    print("Source manager self-test passed.")


if __name__ == "__main__":
    _run_self_test()