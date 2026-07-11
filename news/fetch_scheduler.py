# news/fetch_scheduler.py

"""
BahuvuNewsAI - News Fetch Scheduler
Version: 1.0.0

This module coordinates all configured news collectors and produces one
unified collection run.

Responsibilities:

- Register collector classes by SourceType
- Select the correct collector for every NewsSource
- Respect source activity and fetch intervals
- Process sources in priority order
- Support sequential and concurrent collection
- Retry failed collection attempts with exponential backoff
- Optionally perform source health checks
- Isolate failures so one source cannot stop the complete run
- Aggregate canonical NewsArticle objects
- Record source-level and run-level statistics
- Produce JSON-compatible operational reports
- Provide a deterministic, network-free self-test

The individual collectors remain responsible for downloading, validating,
and normalizing their source data. The scheduler coordinates them without
duplicating collector logic.
"""

from __future__ import annotations

from concurrent.futures import (
    Future,
    ThreadPoolExecutor,
    as_completed,
)
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
import threading
import time
from typing import Any, Iterable, Mapping, TypeAlias

from news.api_collector import APICollector
from news.models import (
    NewsArticle,
    NewsSource,
    SourceStatus,
    SourceType,
)
from news.rss_collector import RSSCollector
from news.source_manager import (
    BaseNewsCollector,
    CollectionResult,
    SourceHealth,
    SourceManager,
)
from news.web_collector import WebCollector


LOGGER = logging.getLogger("BahuvuNewsAI.news.fetch_scheduler")


# ==========================================================
# TYPE DEFINITIONS
# ==========================================================

CollectorClass: TypeAlias = type[BaseNewsCollector]


# ==========================================================
# TIME HELPERS
# ==========================================================

def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""

    return datetime.now(timezone.utc)


def ensure_utc(value: datetime | None) -> datetime | None:
    """Normalize a datetime to timezone-aware UTC."""

    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


# ==========================================================
# EXCEPTIONS
# ==========================================================

class FetchSchedulerError(RuntimeError):
    """Base exception for fetch-scheduler failures."""


class CollectorNotRegisteredError(FetchSchedulerError):
    """Raised when no collector supports a source type."""


class SchedulerConfigurationError(FetchSchedulerError):
    """Raised when scheduler configuration is invalid."""


# ==========================================================
# SCHEDULER CONFIGURATION
# ==========================================================

@dataclass(slots=True)
class FetchSchedulerConfig:
    """
    Runtime configuration for FetchScheduler.

    max_workers:
        Maximum concurrent source jobs.

    max_retries:
        Number of additional attempts after the initial attempt.

    retry_backoff_seconds:
        Initial retry delay. Every later retry multiplies this delay by
        retry_backoff_multiplier.

    retry_backoff_multiplier:
        Exponential retry-delay multiplier.

    maximum_retry_delay_seconds:
        Maximum delay allowed between attempts.

    perform_health_checks:
        Whether a collector health check should run before collection.

    skip_unhealthy_sources:
        Whether collection should be skipped when the health check fails.

    respect_fetch_intervals:
        Whether sources fetched too recently should be skipped.

    concurrent:
        Whether multiple sources may be processed concurrently.
    """

    max_workers: int = 4
    max_retries: int = 2
    retry_backoff_seconds: float = 1.0
    retry_backoff_multiplier: float = 2.0
    maximum_retry_delay_seconds: float = 30.0

    perform_health_checks: bool = False
    skip_unhealthy_sources: bool = False
    respect_fetch_intervals: bool = True
    concurrent: bool = True

    def __post_init__(self) -> None:
        self.max_workers = int(self.max_workers)
        self.max_retries = int(self.max_retries)
        self.retry_backoff_seconds = float(
            self.retry_backoff_seconds
        )
        self.retry_backoff_multiplier = float(
            self.retry_backoff_multiplier
        )
        self.maximum_retry_delay_seconds = float(
            self.maximum_retry_delay_seconds
        )

        if self.max_workers < 1:
            raise SchedulerConfigurationError(
                "max_workers must be at least 1."
            )

        if self.max_retries < 0:
            raise SchedulerConfigurationError(
                "max_retries cannot be negative."
            )

        if self.retry_backoff_seconds < 0:
            raise SchedulerConfigurationError(
                "retry_backoff_seconds cannot be negative."
            )

        if self.retry_backoff_multiplier < 1:
            raise SchedulerConfigurationError(
                "retry_backoff_multiplier must be at least 1."
            )

        if self.maximum_retry_delay_seconds < 0:
            raise SchedulerConfigurationError(
                "maximum_retry_delay_seconds cannot be negative."
            )

    @property
    def maximum_attempts(self) -> int:
        """Return the initial attempt plus configured retries."""

        return self.max_retries + 1

    def retry_delay(self, failed_attempt_number: int) -> float:
        """
        Return the delay after a failed attempt.

        failed_attempt_number is one-based. A value of 1 means the first
        collection attempt has just failed.
        """

        if failed_attempt_number < 1:
            return 0.0

        delay = (
            self.retry_backoff_seconds
            * (
                self.retry_backoff_multiplier
                ** (failed_attempt_number - 1)
            )
        )

        return min(
            delay,
            self.maximum_retry_delay_seconds,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize scheduler configuration."""

        return {
            "max_workers": self.max_workers,
            "max_retries": self.max_retries,
            "maximum_attempts": self.maximum_attempts,
            "retry_backoff_seconds": (
                self.retry_backoff_seconds
            ),
            "retry_backoff_multiplier": (
                self.retry_backoff_multiplier
            ),
            "maximum_retry_delay_seconds": (
                self.maximum_retry_delay_seconds
            ),
            "perform_health_checks": (
                self.perform_health_checks
            ),
            "skip_unhealthy_sources": (
                self.skip_unhealthy_sources
            ),
            "respect_fetch_intervals": (
                self.respect_fetch_intervals
            ),
            "concurrent": self.concurrent,
        }


# ==========================================================
# SOURCE EXECUTION RECORD
# ==========================================================

@dataclass(slots=True)
class SourceFetchRecord:
    """Complete scheduler record for one source."""

    source_id: str
    source_name: str
    source_type: SourceType
    priority: int

    scheduled: bool = True
    skipped: bool = False
    skip_reason: str = ""

    attempts: int = 0
    retried: bool = False

    collection_result: CollectionResult | None = None
    health: SourceHealth | None = None

    started_at: datetime = field(default_factory=utc_now)
    completed_at: datetime | None = None

    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.source_id = str(self.source_id).strip()
        self.source_name = str(self.source_name).strip()

        if not isinstance(self.source_type, SourceType):
            self.source_type = SourceType(
                str(self.source_type)
            )

        self.priority = int(self.priority)
        self.skip_reason = str(
            self.skip_reason or ""
        ).strip()
        self.attempts = int(self.attempts)
        self.errors = [
            str(error).strip()
            for error in self.errors
            if str(error).strip()
        ]
        self.metadata = dict(self.metadata or {})
        self.started_at = (
            ensure_utc(self.started_at)
            or utc_now()
        )
        self.completed_at = ensure_utc(
            self.completed_at
        )

        if not self.source_id:
            raise ValueError(
                "SourceFetchRecord.source_id cannot be empty."
            )

        if not self.source_name:
            raise ValueError(
                "SourceFetchRecord.source_name cannot be empty."
            )

        if not 0 <= self.priority <= 100:
            raise ValueError(
                "SourceFetchRecord.priority must be between 0 and 100."
            )

        if self.attempts < 0:
            raise ValueError(
                "SourceFetchRecord.attempts cannot be negative."
            )

    @property
    def success(self) -> bool:
        """Return whether source collection completed successfully."""

        return bool(
            not self.skipped
            and self.collection_result is not None
            and self.collection_result.success
        )

    @property
    def failed(self) -> bool:
        """Return whether the source ran but ultimately failed."""

        return bool(
            not self.skipped
            and self.completed_at is not None
            and not self.success
        )

    @property
    def article_count(self) -> int:
        """Return the normalized article count."""

        if self.collection_result is None:
            return 0

        return self.collection_result.article_count

    @property
    def raw_items_count(self) -> int:
        """Return the total raw item count."""

        if self.collection_result is None:
            return 0

        return self.collection_result.raw_items_count

    @property
    def rejected_items_count(self) -> int:
        """Return the rejected item count."""

        if self.collection_result is None:
            return 0

        return self.collection_result.rejected_items_count

    @property
    def duration_seconds(self) -> float | None:
        """Return scheduler processing time for this source."""

        if self.completed_at is None:
            return None

        return max(
            0.0,
            (
                self.completed_at - self.started_at
            ).total_seconds(),
        )

    @property
    def articles(self) -> list[NewsArticle]:
        """Return the articles produced by this source."""

        if self.collection_result is None:
            return []

        return list(self.collection_result.articles)

    @property
    def final_error(self) -> str:
        """Return the last recorded source error."""

        if self.collection_result is not None:
            if self.collection_result.error:
                return self.collection_result.error

        if self.errors:
            return self.errors[-1]

        return ""

    def mark_skipped(self, reason: str) -> None:
        """Mark the source as skipped."""

        self.skipped = True
        self.skip_reason = str(reason).strip()
        self.completed_at = utc_now()

    def complete(self) -> None:
        """Mark source processing as complete."""

        self.completed_at = utc_now()

    def to_dict(
        self,
        *,
        include_articles: bool = False,
    ) -> dict[str, Any]:
        """Serialize the source execution record."""

        data: dict[str, Any] = {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_type": self.source_type.value,
            "priority": self.priority,
            "scheduled": self.scheduled,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "success": self.success,
            "failed": self.failed,
            "attempts": self.attempts,
            "retried": self.retried,
            "article_count": self.article_count,
            "raw_items_count": self.raw_items_count,
            "rejected_items_count": (
                self.rejected_items_count
            ),
            "started_at": self.started_at.isoformat(),
            "completed_at": (
                self.completed_at.isoformat()
                if self.completed_at is not None
                else None
            ),
            "duration_seconds": self.duration_seconds,
            "final_error": self.final_error,
            "errors": list(self.errors),
            "health": (
                self.health.to_dict()
                if self.health is not None
                else None
            ),
            "metadata": dict(self.metadata),
        }

        if include_articles:
            data["articles"] = [
                article.to_dict()
                for article in self.articles
            ]

        return data


# ==========================================================
# COMPLETE SCHEDULER RUN
# ==========================================================

@dataclass(slots=True)
class FetchRunResult:
    """Aggregated result of one scheduler execution."""

    run_id: str
    records: list[SourceFetchRecord] = field(
        default_factory=list
    )
    started_at: datetime = field(default_factory=utc_now)
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.run_id = str(self.run_id).strip()
        self.records = list(self.records or [])
        self.started_at = (
            ensure_utc(self.started_at)
            or utc_now()
        )
        self.completed_at = ensure_utc(
            self.completed_at
        )
        self.metadata = dict(self.metadata or {})

        if not self.run_id:
            raise ValueError(
                "FetchRunResult.run_id cannot be empty."
            )

    @property
    def articles(self) -> list[NewsArticle]:
        """Return all articles in scheduler record order."""

        combined: list[NewsArticle] = []

        for record in self.records:
            combined.extend(record.articles)

        return combined

    @property
    def total_sources(self) -> int:
        """Return all source records in the run."""

        return len(self.records)

    @property
    def processed_sources(self) -> int:
        """Return sources that were not skipped."""

        return sum(
            1
            for record in self.records
            if not record.skipped
        )

    @property
    def successful_sources(self) -> int:
        """Return successfully collected sources."""

        return sum(
            1
            for record in self.records
            if record.success
        )

    @property
    def failed_sources(self) -> int:
        """Return sources that ultimately failed."""

        return sum(
            1
            for record in self.records
            if record.failed
        )

    @property
    def skipped_sources(self) -> int:
        """Return skipped source count."""

        return sum(
            1
            for record in self.records
            if record.skipped
        )

    @property
    def retried_sources(self) -> int:
        """Return sources that needed multiple attempts."""

        return sum(
            1
            for record in self.records
            if record.retried
        )

    @property
    def total_attempts(self) -> int:
        """Return all collection attempts."""

        return sum(
            record.attempts
            for record in self.records
        )

    @property
    def raw_items_count(self) -> int:
        """Return raw item total."""

        return sum(
            record.raw_items_count
            for record in self.records
        )

    @property
    def rejected_items_count(self) -> int:
        """Return rejected item total."""

        return sum(
            record.rejected_items_count
            for record in self.records
        )

    @property
    def article_count(self) -> int:
        """Return normalized article total."""

        return sum(
            record.article_count
            for record in self.records
        )

    @property
    def success(self) -> bool:
        """
        Return whether the run completed without source failures.

        Skipped sources do not make a scheduler run unsuccessful.
        """

        return self.failed_sources == 0

    @property
    def duration_seconds(self) -> float | None:
        """Return total run duration."""

        if self.completed_at is None:
            return None

        return max(
            0.0,
            (
                self.completed_at - self.started_at
            ).total_seconds(),
        )

    def complete(self) -> None:
        """Mark the scheduler run as complete."""

        self.completed_at = utc_now()

    def summary(self) -> dict[str, Any]:
        """Return compact scheduler statistics."""

        return {
            "run_id": self.run_id,
            "success": self.success,
            "total_sources": self.total_sources,
            "processed_sources": self.processed_sources,
            "successful_sources": self.successful_sources,
            "failed_sources": self.failed_sources,
            "skipped_sources": self.skipped_sources,
            "retried_sources": self.retried_sources,
            "total_attempts": self.total_attempts,
            "raw_items_count": self.raw_items_count,
            "article_count": self.article_count,
            "rejected_items_count": (
                self.rejected_items_count
            ),
            "started_at": self.started_at.isoformat(),
            "completed_at": (
                self.completed_at.isoformat()
                if self.completed_at is not None
                else None
            ),
            "duration_seconds": self.duration_seconds,
        }

    def to_dict(
        self,
        *,
        include_articles: bool = False,
    ) -> dict[str, Any]:
        """Serialize the complete scheduler run."""

        return {
            **self.summary(),
            "metadata": dict(self.metadata),
            "records": [
                record.to_dict(
                    include_articles=include_articles
                )
                for record in self.records
            ],
        }


# ==========================================================
# FETCH SCHEDULER
# ==========================================================

class FetchScheduler:
    """
    Coordinate collection across all registered news sources.

    Collector classes are stored in a registry keyed by SourceType.
    Additional collectors can be registered without changing the main
    scheduler algorithm.
    """

    def __init__(
        self,
        source_manager: SourceManager | None = None,
        *,
        config: FetchSchedulerConfig | None = None,
        register_default_collectors: bool = True,
    ) -> None:
        self.source_manager = (
            source_manager
            if source_manager is not None
            else SourceManager()
        )

        if not isinstance(
            self.source_manager,
            SourceManager,
        ):
            raise TypeError(
                "source_manager must be a SourceManager instance."
            )

        self.config = (
            config
            if config is not None
            else FetchSchedulerConfig()
        )

        if not isinstance(
            self.config,
            FetchSchedulerConfig,
        ):
            raise TypeError(
                "config must be a FetchSchedulerConfig instance."
            )

        self._collector_registry: dict[
            SourceType,
            CollectorClass,
        ] = {}

        self._run_counter = 0
        self._counter_lock = threading.Lock()

        if register_default_collectors:
            self.register_default_collectors()

    # ======================================================
    # COLLECTOR REGISTRY
    # ======================================================

    def register_default_collectors(self) -> None:
        """Register the built-in collector classes."""

        self.register_collector(
            SourceType.RSS,
            RSSCollector,
            replace=True,
        )
        self.register_collector(
            SourceType.API,
            APICollector,
            replace=True,
        )
        self.register_collector(
            SourceType.WEBSITE,
            WebCollector,
            replace=True,
        )

    def register_collector(
        self,
        source_type: SourceType | str,
        collector_class: CollectorClass,
        *,
        replace: bool = False,
    ) -> None:
        """Register a collector class for one source type."""

        normalized_type = (
            source_type
            if isinstance(source_type, SourceType)
            else SourceType(str(source_type))
        )

        if not isinstance(collector_class, type):
            raise TypeError(
                "collector_class must be a class."
            )

        if not issubclass(
            collector_class,
            BaseNewsCollector,
        ):
            raise TypeError(
                "collector_class must inherit BaseNewsCollector."
            )

        supported_types = getattr(
            collector_class,
            "supported_source_types",
            frozenset(),
        )

        if (
            supported_types
            and normalized_type not in supported_types
        ):
            raise ValueError(
                f"{collector_class.__name__} does not declare support "
                f"for SourceType.{normalized_type.name}."
            )

        if (
            normalized_type in self._collector_registry
            and not replace
        ):
            existing = self._collector_registry[
                normalized_type
            ]

            raise ValueError(
                f"A collector is already registered for "
                f"'{normalized_type.value}': {existing.__name__}."
            )

        self._collector_registry[
            normalized_type
        ] = collector_class

        LOGGER.info(
            "Collector registered | type=%s | collector=%s",
            normalized_type.value,
            collector_class.__name__,
        )

    def unregister_collector(
        self,
        source_type: SourceType | str,
    ) -> CollectorClass:
        """Remove and return a registered collector class."""

        normalized_type = (
            source_type
            if isinstance(source_type, SourceType)
            else SourceType(str(source_type))
        )

        try:
            collector_class = self._collector_registry.pop(
                normalized_type
            )
        except KeyError as error:
            raise CollectorNotRegisteredError(
                f"No collector is registered for "
                f"'{normalized_type.value}'."
            ) from error

        LOGGER.info(
            "Collector unregistered | type=%s | collector=%s",
            normalized_type.value,
            collector_class.__name__,
        )

        return collector_class

    def collector_class_for(
        self,
        source_type: SourceType | str,
    ) -> CollectorClass:
        """Return the registered collector class."""

        normalized_type = (
            source_type
            if isinstance(source_type, SourceType)
            else SourceType(str(source_type))
        )

        try:
            return self._collector_registry[
                normalized_type
            ]
        except KeyError as error:
            raise CollectorNotRegisteredError(
                f"No collector is registered for source type "
                f"'{normalized_type.value}'."
            ) from error

    def create_collector(
        self,
        source: NewsSource,
    ) -> BaseNewsCollector:
        """Create a new collector instance for a source."""

        if not isinstance(source, NewsSource):
            raise TypeError(
                "source must be a NewsSource instance."
            )

        collector_class = self.collector_class_for(
            source.source_type
        )

        return collector_class(source)

    def registered_collectors(
        self,
    ) -> dict[str, str]:
        """Return a readable collector registry."""

        return {
            source_type.value: collector_class.__name__
            for source_type, collector_class
            in sorted(
                self._collector_registry.items(),
                key=lambda item: item[0].value,
            )
        }

    # ======================================================
    # SOURCE ELIGIBILITY
    # ======================================================

    def is_source_due(
        self,
        source: NewsSource,
        *,
        reference_time: datetime | None = None,
    ) -> bool:
        """Return whether the source fetch interval has elapsed."""

        if not isinstance(source, NewsSource):
            raise TypeError(
                "source must be a NewsSource instance."
            )

        last_fetched_at = ensure_utc(
            source.last_fetched_at
        )

        if last_fetched_at is None:
            return True

        now = (
            ensure_utc(reference_time)
            or utc_now()
        )

        next_fetch_at = (
            last_fetched_at
            + timedelta(
                minutes=source.fetch_interval_minutes
            )
        )

        return now >= next_fetch_at

    def source_skip_reason(
        self,
        source: NewsSource,
        *,
        force: bool = False,
        reference_time: datetime | None = None,
    ) -> str:
        """Return why a source should be skipped, or an empty string."""

        if not source.is_active:
            return (
                f"Source status is '{source.status.value}', "
                "not 'active'."
            )

        if (
            source.source_type
            not in self._collector_registry
        ):
            return (
                "No collector is registered for source type "
                f"'{source.source_type.value}'."
            )

        if (
            not force
            and self.config.respect_fetch_intervals
            and not self.is_source_due(
                source,
                reference_time=reference_time,
            )
        ):
            return (
                "Fetch interval has not elapsed since the "
                "previous attempt."
            )

        return ""

    def eligible_sources(
        self,
        sources: Iterable[NewsSource] | None = None,
        *,
        force: bool = False,
        reference_time: datetime | None = None,
    ) -> list[NewsSource]:
        """Return eligible sources in priority order."""

        source_list = self._normalize_sources(sources)

        return [
            source
            for source in source_list
            if not self.source_skip_reason(
                source,
                force=force,
                reference_time=reference_time,
            )
        ]

    # ======================================================
    # HEALTH CHECK
    # ======================================================

    def check_source_health(
        self,
        source: NewsSource,
    ) -> SourceHealth:
        """Run one isolated collector health check."""

        collector: BaseNewsCollector | None = None

        try:
            collector = self.create_collector(source)
            return collector.health_check()

        except Exception as error:
            return SourceHealth(
                source_id=source.source_id,
                source_name=source.name,
                status=source.status,
                healthy=False,
                message=(
                    f"{error.__class__.__name__}: {error}"
                ),
            )

        finally:
            if (
                collector is not None
                and not collector.is_closed
            ):
                try:
                    collector.close()
                except Exception:
                    LOGGER.exception(
                        "Collector close failed after health check | "
                        "source=%s",
                        source.name,
                    )

    # ======================================================
    # SOURCE COLLECTION
    # ======================================================

    def collect_source(
        self,
        source: NewsSource,
        *,
        force: bool = False,
        reference_time: datetime | None = None,
    ) -> SourceFetchRecord:
        """
        Collect one source with health checks and retries.

        A fresh collector instance is created for every attempt because
        collectors are intentionally closed after use.
        """

        if not isinstance(source, NewsSource):
            raise TypeError(
                "source must be a NewsSource instance."
            )

        record = SourceFetchRecord(
            source_id=source.source_id,
            source_name=source.name,
            source_type=source.source_type,
            priority=source.priority,
        )

        skip_reason = self.source_skip_reason(
            source,
            force=force,
            reference_time=reference_time,
        )

        if skip_reason:
            record.mark_skipped(skip_reason)

            LOGGER.info(
                "Source skipped | source=%s | reason=%s",
                source.name,
                skip_reason,
            )

            return record

        if self.config.perform_health_checks:
            record.health = self.check_source_health(
                source
            )

            if (
                self.config.skip_unhealthy_sources
                and not record.health.healthy
            ):
                record.mark_skipped(
                    "Health check failed: "
                    f"{record.health.message}"
                )

                LOGGER.warning(
                    "Unhealthy source skipped | source=%s | "
                    "message=%s",
                    source.name,
                    record.health.message,
                )

                return record

        original_status = source.status

        for attempt_number in range(
            1,
            self.config.maximum_attempts + 1,
        ):
            record.attempts = attempt_number
            record.retried = attempt_number > 1

            if attempt_number > 1:
                # BaseNewsCollector records a failed attempt as DEGRADED.
                # Temporarily reactivate it so the retry can execute.
                source.status = SourceStatus.ACTIVE

            collector: BaseNewsCollector | None = None

            try:
                collector = self.create_collector(source)

                LOGGER.info(
                    "Source collection attempt | source=%s | "
                    "attempt=%s/%s",
                    source.name,
                    attempt_number,
                    self.config.maximum_attempts,
                )

                result = collector.collect()
                record.collection_result = result

                if result.success:
                    record.complete()

                    LOGGER.info(
                        "Source collection successful | source=%s | "
                        "attempts=%s | articles=%s",
                        source.name,
                        record.attempts,
                        record.article_count,
                    )

                    return record

                error_message = (
                    result.error
                    or "Collector returned an unsuccessful result."
                )
                record.errors.append(error_message)

            except Exception as error:
                error_message = (
                    f"{error.__class__.__name__}: {error}"
                    if str(error)
                    else error.__class__.__name__
                )
                record.errors.append(error_message)

                LOGGER.exception(
                    "Unexpected scheduler collection error | "
                    "source=%s | attempt=%s",
                    source.name,
                    attempt_number,
                )

            finally:
                if (
                    collector is not None
                    and not collector.is_closed
                ):
                    try:
                        collector.close()
                    except Exception as close_error:
                        close_message = (
                            f"{close_error.__class__.__name__}: "
                            f"{close_error}"
                        )
                        record.errors.append(
                            f"Collector close failure: "
                            f"{close_message}"
                        )

                        LOGGER.exception(
                            "Collector close failed | source=%s",
                            source.name,
                        )

            if (
                attempt_number
                < self.config.maximum_attempts
            ):
                retry_delay = self.config.retry_delay(
                    attempt_number
                )

                LOGGER.warning(
                    "Source collection will retry | source=%s | "
                    "attempt=%s | delay=%.2f seconds",
                    source.name,
                    attempt_number,
                    retry_delay,
                )

                if retry_delay > 0:
                    time.sleep(retry_delay)

        # The source should remain degraded or error after all attempts.
        if source.status == SourceStatus.ACTIVE:
            source.status = (
                SourceStatus.ERROR
                if source.consecutive_failures >= 5
                else SourceStatus.DEGRADED
            )

        record.metadata["initial_source_status"] = (
            original_status.value
        )
        record.metadata["final_source_status"] = (
            source.status.value
        )
        record.complete()

        LOGGER.error(
            "Source collection exhausted retries | source=%s | "
            "attempts=%s | error=%s",
            source.name,
            record.attempts,
            record.final_error,
        )

        return record

    # ======================================================
    # SCHEDULER RUN
    # ======================================================

    def run(
        self,
        sources: Iterable[NewsSource] | None = None,
        *,
        force: bool = False,
        concurrent: bool | None = None,
    ) -> FetchRunResult:
        """
        Execute one complete scheduler run.

        sources:
            Optional source subset. When omitted, every registered source
            in SourceManager is considered.

        force:
            Ignore fetch intervals. Inactive sources remain skipped.

        concurrent:
            Override the configured concurrency mode for this run.
        """

        source_list = self._normalize_sources(sources)
        run_id = self._next_run_id()

        run_result = FetchRunResult(
            run_id=run_id,
            metadata={
                "force": bool(force),
                "registered_collectors": (
                    self.registered_collectors()
                ),
                "scheduler_config": self.config.to_dict(),
            },
        )

        reference_time = run_result.started_at
        use_concurrency = (
            self.config.concurrent
            if concurrent is None
            else bool(concurrent)
        )

        LOGGER.info(
            "Fetch scheduler started | run_id=%s | sources=%s | "
            "concurrent=%s",
            run_id,
            len(source_list),
            use_concurrency,
        )

        runnable_sources: list[NewsSource] = []

        for source in source_list:
            skip_reason = self.source_skip_reason(
                source,
                force=force,
                reference_time=reference_time,
            )

            if skip_reason:
                skipped_record = SourceFetchRecord(
                    source_id=source.source_id,
                    source_name=source.name,
                    source_type=source.source_type,
                    priority=source.priority,
                )
                skipped_record.mark_skipped(skip_reason)
                run_result.records.append(
                    skipped_record
                )
            else:
                runnable_sources.append(source)

        if use_concurrency and len(runnable_sources) > 1:
            completed_records = self._run_concurrent(
                runnable_sources,
                force=force,
                reference_time=reference_time,
            )
        else:
            completed_records = self._run_sequential(
                runnable_sources,
                force=force,
                reference_time=reference_time,
            )

        run_result.records.extend(completed_records)

        priority_by_source_id = {
            source.source_id: index
            for index, source in enumerate(source_list)
        }

        run_result.records.sort(
            key=lambda record: priority_by_source_id.get(
                record.source_id,
                len(priority_by_source_id),
            )
        )

        run_result.complete()

        LOGGER.info(
            "Fetch scheduler completed | run_id=%s | "
            "successful=%s | failed=%s | skipped=%s | "
            "articles=%s | duration=%.3f",
            run_id,
            run_result.successful_sources,
            run_result.failed_sources,
            run_result.skipped_sources,
            run_result.article_count,
            run_result.duration_seconds or 0.0,
        )

        return run_result

    def _run_sequential(
        self,
        sources: list[NewsSource],
        *,
        force: bool,
        reference_time: datetime,
    ) -> list[SourceFetchRecord]:
        """Process sources one after another."""

        records: list[SourceFetchRecord] = []

        for source in sources:
            records.append(
                self.collect_source(
                    source,
                    force=force,
                    reference_time=reference_time,
                )
            )

        return records

    def _run_concurrent(
        self,
        sources: list[NewsSource],
        *,
        force: bool,
        reference_time: datetime,
    ) -> list[SourceFetchRecord]:
        """Process sources concurrently with isolated failures."""

        records: list[SourceFetchRecord] = []
        worker_count = min(
            self.config.max_workers,
            len(sources),
        )

        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="bahuvu-fetch",
        ) as executor:
            future_map: dict[
                Future[SourceFetchRecord],
                NewsSource,
            ] = {
                executor.submit(
                    self.collect_source,
                    source,
                    force=force,
                    reference_time=reference_time,
                ): source
                for source in sources
            }

            for future in as_completed(future_map):
                source = future_map[future]

                try:
                    records.append(future.result())

                except Exception as error:
                    LOGGER.exception(
                        "Concurrent source task failed unexpectedly | "
                        "source=%s",
                        source.name,
                    )

                    failed_record = SourceFetchRecord(
                        source_id=source.source_id,
                        source_name=source.name,
                        source_type=source.source_type,
                        priority=source.priority,
                    )
                    failed_record.attempts = 1
                    failed_record.errors.append(
                        f"{error.__class__.__name__}: {error}"
                    )
                    failed_record.complete()
                    records.append(failed_record)

        return records

    # ======================================================
    # REPORTING
    # ======================================================

    def health_report(
        self,
        sources: Iterable[NewsSource] | None = None,
        *,
        active_only: bool = True,
        concurrent: bool | None = None,
    ) -> list[SourceHealth]:
        """Return operational health for configured sources."""

        source_list = self._normalize_sources(sources)

        if active_only:
            source_list = [
                source
                for source in source_list
                if source.is_active
            ]

        use_concurrency = (
            self.config.concurrent
            if concurrent is None
            else bool(concurrent)
        )

        if not use_concurrency or len(source_list) <= 1:
            return [
                self.check_source_health(source)
                for source in source_list
            ]

        health_results: list[SourceHealth] = []

        with ThreadPoolExecutor(
            max_workers=min(
                self.config.max_workers,
                len(source_list),
            ),
            thread_name_prefix="bahuvu-health",
        ) as executor:
            future_map = {
                executor.submit(
                    self.check_source_health,
                    source,
                ): source
                for source in source_list
            }

            for future in as_completed(future_map):
                health_results.append(
                    future.result()
                )

        source_order = {
            source.source_id: index
            for index, source in enumerate(source_list)
        }

        health_results.sort(
            key=lambda health: source_order.get(
                health.source_id,
                len(source_order),
            )
        )

        return health_results

    def summary(self) -> dict[str, Any]:
        """Return scheduler registration and configuration details."""

        return {
            "registered_source_count": len(
                self.source_manager
            ),
            "source_manager": (
                self.source_manager.summary()
            ),
            "registered_collectors": (
                self.registered_collectors()
            ),
            "config": self.config.to_dict(),
        }

    # ======================================================
    # INTERNAL HELPERS
    # ======================================================

    def _normalize_sources(
        self,
        sources: Iterable[NewsSource] | None,
    ) -> list[NewsSource]:
        """Validate, deduplicate, and priority-sort sources."""

        if sources is None:
            source_values = (
                self.source_manager.list_sources()
            )
        else:
            source_values = list(sources)

        normalized: list[NewsSource] = []
        seen_ids: set[str] = set()

        for source in source_values:
            if not isinstance(source, NewsSource):
                raise TypeError(
                    "Every scheduler source must be a "
                    "NewsSource instance."
                )

            if source.source_id in seen_ids:
                continue

            seen_ids.add(source.source_id)
            normalized.append(source)

        return sorted(
            normalized,
            key=lambda source: (
                -source.priority,
                source.name.casefold(),
            ),
        )

    def _next_run_id(self) -> str:
        """Generate a process-local scheduler run ID."""

        with self._counter_lock:
            self._run_counter += 1
            run_number = self._run_counter

        timestamp = utc_now().strftime(
            "%Y%m%dT%H%M%S%fZ"
        )

        return (
            f"fetch_run_{timestamp}_{run_number:04d}"
        )


# ==========================================================
# MODULE SELF-TEST
# ==========================================================

def _run_self_test() -> None:
    """
    Run deterministic, network-free scheduler tests.

    A fake collector is registered for RSS sources so no internet
    connection is needed.
    """

    from news.models import (
        LanguageCode,
        NewsCategory,
    )

    attempt_counts: dict[str, int] = {}

    class FakeCollector(BaseNewsCollector):
        """Network-free collector used only by this self-test."""

        supported_source_types = frozenset(
            {SourceType.RSS}
        )

        def connect(self) -> None:
            self._mark_connected()

        def fetch(self) -> list[dict[str, str]]:
            attempt_counts[self.source.source_id] = (
                attempt_counts.get(
                    self.source.source_id,
                    0,
                )
                + 1
            )

            required_failures = int(
                self.source.metadata.get(
                    "fail_attempts",
                    0,
                )
            )

            if (
                attempt_counts[self.source.source_id]
                <= required_failures
            ):
                raise RuntimeError(
                    "Intentional self-test collection failure."
                )

            article_count = int(
                self.source.metadata.get(
                    "article_count",
                    1,
                )
            )

            return [
                {
                    "title": (
                        f"{self.source.name} Article {index}"
                    ),
                    "url": (
                        f"https://example.com/"
                        f"{self.source.source_id}/{index}"
                    ),
                    "description": (
                        "Deterministic scheduler self-test article."
                    ),
                }
                for index in range(
                    1,
                    article_count + 1,
                )
            ]

        def validate_item(
            self,
            raw_item: Any,
        ) -> bool:
            return bool(
                isinstance(raw_item, Mapping)
                and raw_item.get("title")
                and raw_item.get("url")
            )

        def normalize_item(
            self,
            raw_item: Any,
        ) -> NewsArticle:
            return NewsArticle(
                title=str(raw_item["title"]),
                url=str(raw_item["url"]),
                canonical_url=str(raw_item["url"]),
                source_id=self.source.source_id,
                source_name=self.source.name,
                publisher=self.source.publisher,
                description=str(
                    raw_item.get("description", "")
                ),
                raw_text=str(
                    raw_item.get("description", "")
                ),
                category=(
                    self.source.default_category
                ),
                language=self.source.language,
                reliability_score=(
                    self.source.reliability_score
                ),
                metadata={
                    "collector": "FakeCollector",
                },
            )

        def health_check(self) -> SourceHealth:
            return SourceHealth(
                source_id=self.source.source_id,
                source_name=self.source.name,
                status=self.source.status,
                healthy=True,
                message="Fake source is healthy.",
                response_time_seconds=0.0,
            )

        def close(self) -> None:
            self._mark_closed()

    high_priority_source = NewsSource(
        source_id="source_high",
        name="High Priority Test Feed",
        source_type=SourceType.RSS,
        url="https://example.com/high.xml",
        language=LanguageCode.ENGLISH,
        default_category=NewsCategory.NATIONAL,
        reliability_score=90.0,
        priority=90,
        fetch_interval_minutes=30,
        publisher="Bahuvu Test Publisher",
        metadata={
            "article_count": 2,
            "fail_attempts": 0,
        },
    )

    retry_source = NewsSource(
        source_id="source_retry",
        name="Retry Test Feed",
        source_type=SourceType.RSS,
        url="https://example.com/retry.xml",
        language=LanguageCode.ENGLISH,
        default_category=NewsCategory.TECHNOLOGY,
        reliability_score=80.0,
        priority=70,
        fetch_interval_minutes=30,
        publisher="Bahuvu Test Publisher",
        metadata={
            "article_count": 1,
            "fail_attempts": 1,
        },
    )

    paused_source = NewsSource(
        source_id="source_paused",
        name="Paused Test Feed",
        source_type=SourceType.RSS,
        url="https://example.com/paused.xml",
        status=SourceStatus.PAUSED,
        language=LanguageCode.ENGLISH,
        default_category=NewsCategory.OTHER,
        priority=50,
    )

    recent_source = NewsSource(
        source_id="source_recent",
        name="Recently Fetched Feed",
        source_type=SourceType.RSS,
        url="https://example.com/recent.xml",
        language=LanguageCode.ENGLISH,
        default_category=NewsCategory.OTHER,
        priority=40,
        fetch_interval_minutes=60,
        last_fetched_at=utc_now(),
    )

    manager = SourceManager(
        [
            recent_source,
            paused_source,
            retry_source,
            high_priority_source,
        ]
    )

    config = FetchSchedulerConfig(
        max_workers=2,
        max_retries=2,
        retry_backoff_seconds=0.0,
        perform_health_checks=True,
        skip_unhealthy_sources=True,
        respect_fetch_intervals=True,
        concurrent=True,
    )

    scheduler = FetchScheduler(
        manager,
        config=config,
        register_default_collectors=False,
    )

    scheduler.register_collector(
        SourceType.RSS,
        FakeCollector,
    )

    assert scheduler.collector_class_for(
        SourceType.RSS
    ) is FakeCollector

    assert scheduler.is_source_due(
        high_priority_source
    )
    assert not scheduler.is_source_due(
        recent_source
    )

    run_result = scheduler.run()

    assert run_result.total_sources == 4
    assert run_result.processed_sources == 2
    assert run_result.successful_sources == 2
    assert run_result.failed_sources == 0
    assert run_result.skipped_sources == 2
    assert run_result.retried_sources == 1
    assert run_result.total_attempts == 3
    assert run_result.article_count == 3
    assert run_result.raw_items_count == 3
    assert run_result.rejected_items_count == 0
    assert run_result.success is True

    assert (
        run_result.records[0].source_id
        == high_priority_source.source_id
    )
    assert (
        run_result.records[1].source_id
        == retry_source.source_id
    )
    assert (
        run_result.records[2].source_id
        == paused_source.source_id
    )
    assert (
        run_result.records[3].source_id
        == recent_source.source_id
    )

    retry_record = next(
        record
        for record in run_result.records
        if record.source_id
        == retry_source.source_id
    )

    assert retry_record.success
    assert retry_record.attempts == 2
    assert retry_record.retried
    assert retry_source.status == SourceStatus.ACTIVE
    assert retry_source.consecutive_failures == 0

    paused_record = next(
        record
        for record in run_result.records
        if record.source_id
        == paused_source.source_id
    )

    recent_record = next(
        record
        for record in run_result.records
        if record.source_id
        == recent_source.source_id
    )

    assert paused_record.skipped
    assert "paused" in paused_record.skip_reason
    assert recent_record.skipped
    assert "interval" in recent_record.skip_reason.lower()

    articles = run_result.articles

    assert len(articles) == 3
    assert all(
        isinstance(article, NewsArticle)
        for article in articles
    )
    assert all(
        article.metadata["collector"]
        == "FakeCollector"
        for article in articles
    )

    health_results = scheduler.health_report(
        [
            high_priority_source,
            retry_source,
        ],
        concurrent=True,
    )

    assert len(health_results) == 2
    assert all(
        health.healthy
        for health in health_results
    )

    serialized = run_result.to_dict(
        include_articles=True
    )

    assert serialized["article_count"] == 3
    assert len(serialized["records"]) == 4
    assert (
        len(serialized["records"][0]["articles"])
        == 2
    )

    print("Fetch scheduler initialized successfully.")
    print(
        "Registered collectors: "
        f"{scheduler.registered_collectors()}"
    )
    print(
        f"Sources considered: {run_result.total_sources}"
    )
    print(
        f"Sources processed: {run_result.processed_sources}"
    )
    print(
        f"Sources successful: {run_result.successful_sources}"
    )
    print(
        f"Sources failed: {run_result.failed_sources}"
    )
    print(
        f"Sources skipped: {run_result.skipped_sources}"
    )
    print(
        f"Sources retried: {run_result.retried_sources}"
    )
    print(
        f"Collection attempts: {run_result.total_attempts}"
    )
    print(
        f"Articles collected: {run_result.article_count}"
    )
    print(
        f"Raw items: {run_result.raw_items_count}"
    )
    print(
        f"Rejected items: {run_result.rejected_items_count}"
    )
    print("Fetch scheduler self-test passed.")


if __name__ == "__main__":
    _run_self_test()