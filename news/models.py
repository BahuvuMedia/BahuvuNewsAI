# news/models.py

"""
BahuvuNewsAI - Canonical News Data Models
Version: 1.0.0

This module defines the stable data contracts used by the BahuvuNewsAI
news collection and editorial pipeline.

All collectors, classifiers, ranking systems, translators, renderers,
and publishing agents should exchange news data through these models
instead of using loosely structured dictionaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping
from urllib.parse import urlparse
from uuid import uuid4


# ==========================================================
# HELPERS
# ==========================================================


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""

    return datetime.now(timezone.utc)


def generate_id(prefix: str) -> str:
    """Generate a readable globally unique identifier."""

    normalized_prefix = prefix.strip().lower() or "item"
    return f"{normalized_prefix}_{uuid4().hex}"


def normalize_text(value: str | None) -> str:
    """Normalize optional text without changing its meaning."""

    if value is None:
        return ""

    return " ".join(str(value).strip().split())


def ensure_utc(value: datetime | None) -> datetime | None:
    """
    Return a timezone-aware UTC datetime.

    Naive datetimes are treated as UTC because news feeds frequently
    omit timezone information.
    """

    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def datetime_to_iso(value: datetime | None) -> str | None:
    """Convert a datetime to an ISO-8601 UTC string."""

    normalized = ensure_utc(value)

    if normalized is None:
        return None

    return normalized.isoformat()


def datetime_from_iso(value: str | datetime | None) -> datetime | None:
    """Parse an ISO-8601 string or normalize an existing datetime."""

    if value is None or value == "":
        return None

    if isinstance(value, datetime):
        return ensure_utc(value)

    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return ensure_utc(parsed)


def is_valid_http_url(value: str) -> bool:
    """Return True when a value is a valid HTTP or HTTPS URL."""

    try:
        parsed = urlparse(value)
    except (TypeError, ValueError):
        return False

    return (
        parsed.scheme.lower() in {"http", "https"}
        and bool(parsed.netloc)
    )


def enum_value(
    enum_class: type[StrEnum],
    value: StrEnum | str,
) -> StrEnum:
    """Convert a string or enum value into the requested enum type."""

    if isinstance(value, enum_class):
        return value

    return enum_class(str(value).strip().lower())


# ==========================================================
# ENUMERATIONS
# ==========================================================


class SourceType(StrEnum):
    """Supported mechanisms for collecting news."""

    RSS = "rss"
    API = "api"
    WEBSITE = "website"
    GOVERNMENT = "government"
    PRESS_RELEASE = "press_release"
    SOCIAL = "social"
    MANUAL = "manual"
    OTHER = "other"


class SourceStatus(StrEnum):
    """Operational state of a news source."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    PAUSED = "paused"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    ERROR = "error"


class NewsCategory(StrEnum):
    """Canonical editorial categories used throughout the system."""

    BREAKING = "breaking"
    NATIONAL = "national"
    INTERNATIONAL = "international"
    TELANGANA = "telangana"
    ANDHRA_PRADESH = "andhra_pradesh"
    POLITICS = "politics"
    GOVERNMENT = "government"
    BUSINESS = "business"
    ECONOMY = "economy"
    TECHNOLOGY = "technology"
    SCIENCE = "science"
    HEALTH = "health"
    EDUCATION = "education"
    AGRICULTURE = "agriculture"
    ENVIRONMENT = "environment"
    WEATHER = "weather"
    SPORTS = "sports"
    ENTERTAINMENT = "entertainment"
    CRIME = "crime"
    LAW = "law"
    CULTURE = "culture"
    LIFESTYLE = "lifestyle"
    FACT_CHECK = "fact_check"
    OPINION = "opinion"
    OTHER = "other"


class ArticleStatus(StrEnum):
    """Processing state of an article inside the newsroom pipeline."""

    COLLECTED = "collected"
    EXTRACTED = "extracted"
    CLEANED = "cleaned"
    VALIDATED = "validated"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"
    RANKED = "ranked"
    SELECTED = "selected"
    SCRIPTED = "scripted"
    TRANSLATED = "translated"
    PUBLISHED = "published"
    FAILED = "failed"


class LanguageCode(StrEnum):
    """Primary languages supported by BahuvuNewsAI."""

    ENGLISH = "en"
    TELUGU = "te"
    HINDI = "hi"
    UNKNOWN = "unknown"


# ==========================================================
# NEWS SOURCE MODEL
# ==========================================================


@dataclass(slots=True)
class NewsSource:
    """
    A configured source from which news articles can be collected.

    Reliability and priority use a 0-100 scale:

    reliability_score:
        Editorial confidence in the source.

    priority:
        Importance of fetching this source relative to other sources.
    """

    name: str
    source_type: SourceType
    url: str

    source_id: str = field(default_factory=lambda: generate_id("source"))
    status: SourceStatus = SourceStatus.ACTIVE
    language: LanguageCode = LanguageCode.ENGLISH
    default_category: NewsCategory = NewsCategory.OTHER

    reliability_score: float = 50.0
    priority: int = 50
    fetch_interval_minutes: int = 30
    request_timeout_seconds: int = 20

    country: str = ""
    region: str = ""
    publisher: str = ""

    headers: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    last_fetched_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error: str = ""
    consecutive_failures: int = 0

    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.name = normalize_text(self.name)
        self.url = self.url.strip()
        self.source_id = normalize_text(self.source_id)

        self.source_type = enum_value(
            SourceType,
            self.source_type,
        )
        self.status = enum_value(
            SourceStatus,
            self.status,
        )
        self.language = enum_value(
            LanguageCode,
            self.language,
        )
        self.default_category = enum_value(
            NewsCategory,
            self.default_category,
        )

        self.country = normalize_text(self.country)
        self.region = normalize_text(self.region)
        self.publisher = normalize_text(self.publisher)
        self.last_error = normalize_text(self.last_error)

        self.reliability_score = float(self.reliability_score)
        self.priority = int(self.priority)
        self.fetch_interval_minutes = int(self.fetch_interval_minutes)
        self.request_timeout_seconds = int(self.request_timeout_seconds)
        self.consecutive_failures = int(self.consecutive_failures)

        self.last_fetched_at = ensure_utc(self.last_fetched_at)
        self.last_success_at = ensure_utc(self.last_success_at)
        self.last_error_at = ensure_utc(self.last_error_at)
        self.created_at = ensure_utc(self.created_at) or utc_now()
        self.updated_at = ensure_utc(self.updated_at) or utc_now()

        self.headers = dict(self.headers or {})
        self.metadata = dict(self.metadata or {})

        self.validate()

    def validate(self) -> None:
        """Validate all source invariants."""

        if not self.source_id:
            raise ValueError("NewsSource.source_id cannot be empty.")

        if not self.name:
            raise ValueError("NewsSource.name cannot be empty.")

        if not is_valid_http_url(self.url):
            raise ValueError(
                "NewsSource.url must be a valid HTTP or HTTPS URL."
            )

        if not 0.0 <= self.reliability_score <= 100.0:
            raise ValueError(
                "NewsSource.reliability_score must be between 0 and 100."
            )

        if not 0 <= self.priority <= 100:
            raise ValueError(
                "NewsSource.priority must be between 0 and 100."
            )

        if self.fetch_interval_minutes < 1:
            raise ValueError(
                "NewsSource.fetch_interval_minutes must be at least 1."
            )

        if self.request_timeout_seconds < 1:
            raise ValueError(
                "NewsSource.request_timeout_seconds must be at least 1."
            )

        if self.consecutive_failures < 0:
            raise ValueError(
                "NewsSource.consecutive_failures cannot be negative."
            )

    @property
    def is_active(self) -> bool:
        """Return whether the source is currently available for fetching."""

        return self.status == SourceStatus.ACTIVE

    def mark_fetch_success(
        self,
        fetched_at: datetime | None = None,
    ) -> None:
        """Record a successful fetch operation."""

        timestamp = ensure_utc(fetched_at) or utc_now()

        self.status = SourceStatus.ACTIVE
        self.last_fetched_at = timestamp
        self.last_success_at = timestamp
        self.last_error = ""
        self.consecutive_failures = 0
        self.updated_at = timestamp

    def mark_fetch_failure(
        self,
        error: str,
        failed_at: datetime | None = None,
    ) -> None:
        """Record a failed fetch operation."""

        timestamp = ensure_utc(failed_at) or utc_now()

        self.last_fetched_at = timestamp
        self.last_error_at = timestamp
        self.last_error = normalize_text(error)
        self.consecutive_failures += 1
        self.updated_at = timestamp

        if self.consecutive_failures >= 5:
            self.status = SourceStatus.ERROR
        else:
            self.status = SourceStatus.DEGRADED

    def to_dict(self) -> dict[str, Any]:
        """Serialize the source into JSON-compatible data."""

        return {
            "source_id": self.source_id,
            "name": self.name,
            "source_type": self.source_type.value,
            "url": self.url,
            "status": self.status.value,
            "language": self.language.value,
            "default_category": self.default_category.value,
            "reliability_score": self.reliability_score,
            "priority": self.priority,
            "fetch_interval_minutes": self.fetch_interval_minutes,
            "request_timeout_seconds": self.request_timeout_seconds,
            "country": self.country,
            "region": self.region,
            "publisher": self.publisher,
            "headers": dict(self.headers),
            "metadata": dict(self.metadata),
            "last_fetched_at": datetime_to_iso(self.last_fetched_at),
            "last_success_at": datetime_to_iso(self.last_success_at),
            "last_error_at": datetime_to_iso(self.last_error_at),
            "last_error": self.last_error,
            "consecutive_failures": self.consecutive_failures,
            "created_at": datetime_to_iso(self.created_at),
            "updated_at": datetime_to_iso(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> NewsSource:
        """Create a NewsSource from serialized data."""

        return cls(
            source_id=str(data.get("source_id") or generate_id("source")),
            name=str(data.get("name", "")),
            source_type=SourceType(
                str(data.get("source_type", SourceType.OTHER.value))
            ),
            url=str(data.get("url", "")),
            status=SourceStatus(
                str(data.get("status", SourceStatus.ACTIVE.value))
            ),
            language=LanguageCode(
                str(data.get("language", LanguageCode.ENGLISH.value))
            ),
            default_category=NewsCategory(
                str(
                    data.get(
                        "default_category",
                        NewsCategory.OTHER.value,
                    )
                )
            ),
            reliability_score=float(
                data.get("reliability_score", 50.0)
            ),
            priority=int(data.get("priority", 50)),
            fetch_interval_minutes=int(
                data.get("fetch_interval_minutes", 30)
            ),
            request_timeout_seconds=int(
                data.get("request_timeout_seconds", 20)
            ),
            country=str(data.get("country", "")),
            region=str(data.get("region", "")),
            publisher=str(data.get("publisher", "")),
            headers=dict(data.get("headers") or {}),
            metadata=dict(data.get("metadata") or {}),
            last_fetched_at=datetime_from_iso(
                data.get("last_fetched_at")
            ),
            last_success_at=datetime_from_iso(
                data.get("last_success_at")
            ),
            last_error_at=datetime_from_iso(
                data.get("last_error_at")
            ),
            last_error=str(data.get("last_error", "")),
            consecutive_failures=int(
                data.get("consecutive_failures", 0)
            ),
            created_at=datetime_from_iso(
                data.get("created_at")
            )
            or utc_now(),
            updated_at=datetime_from_iso(
                data.get("updated_at")
            )
            or utc_now(),
        )


# ==========================================================
# NEWS ARTICLE MODEL
# ==========================================================


@dataclass(slots=True)
class NewsArticle:
    """
    Canonical article exchanged throughout the news pipeline.

    The model stores both raw collected material and progressively
    enriched editorial fields, allowing every pipeline stage to update
    the same stable article contract.
    """

    title: str
    url: str
    source_id: str

    article_id: str = field(default_factory=lambda: generate_id("article"))
    status: ArticleStatus = ArticleStatus.COLLECTED
    category: NewsCategory = NewsCategory.OTHER
    language: LanguageCode = LanguageCode.UNKNOWN

    source_name: str = ""
    publisher: str = ""
    author: str = ""

    description: str = ""
    raw_text: str = ""
    cleaned_text: str = ""
    summary: str = ""
    generated_headline: str = ""
    telugu_headline: str = ""
    telugu_summary: str = ""
    script: str = ""
    telugu_script: str = ""

    image_url: str = ""
    local_image_path: str = ""
    canonical_url: str = ""

    published_at: datetime | None = None
    collected_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    reliability_score: float = 0.0
    relevance_score: float = 0.0
    importance_score: float = 0.0
    editorial_score: float = 0.0

    duplicate_of: str = ""
    rejection_reason: str = ""
    content_hash: str = ""

    keywords: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    related_urls: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.article_id = normalize_text(self.article_id)
        self.title = normalize_text(self.title)
        self.url = self.url.strip()
        self.source_id = normalize_text(self.source_id)

        self.status = enum_value(
            ArticleStatus,
            self.status,
        )
        self.category = enum_value(
            NewsCategory,
            self.category,
        )
        self.language = enum_value(
            LanguageCode,
            self.language,
        )

        text_fields = (
            "source_name",
            "publisher",
            "author",
            "description",
            "raw_text",
            "cleaned_text",
            "summary",
            "generated_headline",
            "telugu_headline",
            "telugu_summary",
            "script",
            "telugu_script",
            "duplicate_of",
            "rejection_reason",
            "content_hash",
        )

        for field_name in text_fields:
            setattr(
                self,
                field_name,
                normalize_text(getattr(self, field_name)),
            )

        self.image_url = self.image_url.strip()
        self.local_image_path = self.local_image_path.strip()
        self.canonical_url = self.canonical_url.strip()

        self.published_at = ensure_utc(self.published_at)
        self.collected_at = ensure_utc(self.collected_at) or utc_now()
        self.updated_at = ensure_utc(self.updated_at) or utc_now()

        self.reliability_score = float(self.reliability_score)
        self.relevance_score = float(self.relevance_score)
        self.importance_score = float(self.importance_score)
        self.editorial_score = float(self.editorial_score)

        self.keywords = self._normalize_string_list(self.keywords)
        self.tags = self._normalize_string_list(self.tags)
        self.related_urls = self._normalize_url_list(self.related_urls)
        self.metadata = dict(self.metadata or {})

        self.validate()

    @staticmethod
    def _normalize_string_list(values: list[str]) -> list[str]:
        """Normalize and deduplicate a list while preserving order."""

        result: list[str] = []
        seen: set[str] = set()

        for value in values or []:
            normalized = normalize_text(value)

            if not normalized:
                continue

            key = normalized.casefold()

            if key not in seen:
                seen.add(key)
                result.append(normalized)

        return result

    @staticmethod
    def _normalize_url_list(values: list[str]) -> list[str]:
        """Normalize, validate, and deduplicate URLs."""

        result: list[str] = []
        seen: set[str] = set()

        for value in values or []:
            normalized = str(value).strip()

            if not is_valid_http_url(normalized):
                continue

            if normalized not in seen:
                seen.add(normalized)
                result.append(normalized)

        return result

    def validate(self) -> None:
        """Validate all article invariants."""

        if not self.article_id:
            raise ValueError("NewsArticle.article_id cannot be empty.")

        if not self.title:
            raise ValueError("NewsArticle.title cannot be empty.")

        if not self.source_id:
            raise ValueError("NewsArticle.source_id cannot be empty.")

        if not is_valid_http_url(self.url):
            raise ValueError(
                "NewsArticle.url must be a valid HTTP or HTTPS URL."
            )

        if self.image_url and not is_valid_http_url(self.image_url):
            raise ValueError(
                "NewsArticle.image_url must be a valid HTTP or HTTPS URL."
            )

        if self.canonical_url and not is_valid_http_url(
            self.canonical_url
        ):
            raise ValueError(
                "NewsArticle.canonical_url must be a valid HTTP or HTTPS URL."
            )

        score_fields = {
            "reliability_score": self.reliability_score,
            "relevance_score": self.relevance_score,
            "importance_score": self.importance_score,
            "editorial_score": self.editorial_score,
        }

        for field_name, score in score_fields.items():
            if not 0.0 <= score <= 100.0:
                raise ValueError(
                    f"NewsArticle.{field_name} must be between 0 and 100."
                )

        if self.status == ArticleStatus.DUPLICATE and not self.duplicate_of:
            raise ValueError(
                "A duplicate article must identify duplicate_of."
            )

        if self.status == ArticleStatus.REJECTED and not self.rejection_reason:
            raise ValueError(
                "A rejected article must include rejection_reason."
            )

    @property
    def effective_text(self) -> str:
        """Return the best available article text."""

        return (
            self.cleaned_text
            or self.raw_text
            or self.description
        )

    @property
    def effective_headline(self) -> str:
        """Return the best available English headline."""

        return self.generated_headline or self.title

    @property
    def effective_url(self) -> str:
        """Return the canonical URL when available."""

        return self.canonical_url or self.url

    @property
    def is_publishable(self) -> bool:
        """Return whether the article has passed editorial selection."""

        blocked_statuses = {
            ArticleStatus.REJECTED,
            ArticleStatus.DUPLICATE,
            ArticleStatus.FAILED,
        }

        return (
            self.status not in blocked_statuses
            and bool(self.effective_headline)
            and bool(self.effective_text)
        )

    def update_status(
        self,
        status: ArticleStatus,
        *,
        rejection_reason: str = "",
        duplicate_of: str = "",
    ) -> None:
        """Update article status while enforcing required metadata."""

        new_status = enum_value(
            ArticleStatus,
            status,
        )

        if new_status == ArticleStatus.REJECTED:
            normalized_reason = normalize_text(rejection_reason)

            if not normalized_reason:
                raise ValueError(
                    "rejection_reason is required for rejected articles."
                )

            self.rejection_reason = normalized_reason

        if new_status == ArticleStatus.DUPLICATE:
            normalized_duplicate_id = normalize_text(duplicate_of)

            if not normalized_duplicate_id:
                raise ValueError(
                    "duplicate_of is required for duplicate articles."
                )

            self.duplicate_of = normalized_duplicate_id

        self.status = new_status
        self.updated_at = utc_now()
        self.validate()

    def set_editorial_scores(
        self,
        *,
        reliability: float | None = None,
        relevance: float | None = None,
        importance: float | None = None,
        editorial: float | None = None,
    ) -> None:
        """Update one or more newsroom scores safely."""

        updates = {
            "reliability_score": reliability,
            "relevance_score": relevance,
            "importance_score": importance,
            "editorial_score": editorial,
        }

        for field_name, value in updates.items():
            if value is None:
                continue

            numeric_value = float(value)

            if not 0.0 <= numeric_value <= 100.0:
                raise ValueError(
                    f"{field_name} must be between 0 and 100."
                )

            setattr(self, field_name, numeric_value)

        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        """Serialize the article into JSON-compatible data."""

        return {
            "article_id": self.article_id,
            "title": self.title,
            "url": self.url,
            "source_id": self.source_id,
            "status": self.status.value,
            "category": self.category.value,
            "language": self.language.value,
            "source_name": self.source_name,
            "publisher": self.publisher,
            "author": self.author,
            "description": self.description,
            "raw_text": self.raw_text,
            "cleaned_text": self.cleaned_text,
            "summary": self.summary,
            "generated_headline": self.generated_headline,
            "telugu_headline": self.telugu_headline,
            "telugu_summary": self.telugu_summary,
            "script": self.script,
            "telugu_script": self.telugu_script,
            "image_url": self.image_url,
            "local_image_path": self.local_image_path,
            "canonical_url": self.canonical_url,
            "published_at": datetime_to_iso(self.published_at),
            "collected_at": datetime_to_iso(self.collected_at),
            "updated_at": datetime_to_iso(self.updated_at),
            "reliability_score": self.reliability_score,
            "relevance_score": self.relevance_score,
            "importance_score": self.importance_score,
            "editorial_score": self.editorial_score,
            "duplicate_of": self.duplicate_of,
            "rejection_reason": self.rejection_reason,
            "content_hash": self.content_hash,
            "keywords": list(self.keywords),
            "tags": list(self.tags),
            "related_urls": list(self.related_urls),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> NewsArticle:
        """Create a NewsArticle from serialized data."""

        return cls(
            article_id=str(
                data.get("article_id") or generate_id("article")
            ),
            title=str(data.get("title", "")),
            url=str(data.get("url", "")),
            source_id=str(data.get("source_id", "")),
            status=ArticleStatus(
                str(data.get("status", ArticleStatus.COLLECTED.value))
            ),
            category=NewsCategory(
                str(data.get("category", NewsCategory.OTHER.value))
            ),
            language=LanguageCode(
                str(data.get("language", LanguageCode.UNKNOWN.value))
            ),
            source_name=str(data.get("source_name", "")),
            publisher=str(data.get("publisher", "")),
            author=str(data.get("author", "")),
            description=str(data.get("description", "")),
            raw_text=str(data.get("raw_text", "")),
            cleaned_text=str(data.get("cleaned_text", "")),
            summary=str(data.get("summary", "")),
            generated_headline=str(
                data.get("generated_headline", "")
            ),
            telugu_headline=str(data.get("telugu_headline", "")),
            telugu_summary=str(data.get("telugu_summary", "")),
            script=str(data.get("script", "")),
            telugu_script=str(data.get("telugu_script", "")),
            image_url=str(data.get("image_url", "")),
            local_image_path=str(
                data.get("local_image_path", "")
            ),
            canonical_url=str(data.get("canonical_url", "")),
            published_at=datetime_from_iso(
                data.get("published_at")
            ),
            collected_at=datetime_from_iso(
                data.get("collected_at")
            )
            or utc_now(),
            updated_at=datetime_from_iso(
                data.get("updated_at")
            )
            or utc_now(),
            reliability_score=float(
                data.get("reliability_score", 0.0)
            ),
            relevance_score=float(
                data.get("relevance_score", 0.0)
            ),
            importance_score=float(
                data.get("importance_score", 0.0)
            ),
            editorial_score=float(
                data.get("editorial_score", 0.0)
            ),
            duplicate_of=str(data.get("duplicate_of", "")),
            rejection_reason=str(
                data.get("rejection_reason", "")
            ),
            content_hash=str(data.get("content_hash", "")),
            keywords=list(data.get("keywords") or []),
            tags=list(data.get("tags") or []),
            related_urls=list(data.get("related_urls") or []),
            metadata=dict(data.get("metadata") or {}),
        )


# ==========================================================
# MODULE SELF-TEST
# ==========================================================


def _run_self_test() -> None:
    """Run a small deterministic model and serialization test."""

    source = NewsSource(
        name="Bahuvu Test Feed",
        source_type=SourceType.RSS,
        url="https://example.com/news/feed.xml",
        language=LanguageCode.ENGLISH,
        default_category=NewsCategory.NATIONAL,
        reliability_score=85.0,
        priority=80,
        country="India",
        publisher="Example News",
    )

    article = NewsArticle(
        title="Heavy rain continues across Andhra Pradesh",
        url="https://example.com/news/heavy-rain",
        source_id=source.source_id,
        source_name=source.name,
        publisher=source.publisher,
        category=NewsCategory.WEATHER,
        language=LanguageCode.ENGLISH,
        description=(
            "Officials issued alerts as heavy rainfall continued "
            "across several districts."
        ),
        published_at=utc_now(),
        reliability_score=source.reliability_score,
    )

    source_copy = NewsSource.from_dict(source.to_dict())
    article_copy = NewsArticle.from_dict(article.to_dict())

    assert source_copy.source_id == source.source_id
    assert source_copy.source_type == SourceType.RSS
    assert article_copy.article_id == article.article_id
    assert article_copy.category == NewsCategory.WEATHER
    assert article_copy.effective_text == article.description
    assert article_copy.is_publishable

    print("News data models initialized successfully.")
    print(f"Source ID : {source.source_id}")
    print(f"Source    : {source.name}")
    print(f"Article ID: {article.article_id}")
    print(f"Headline  : {article.effective_headline}")
    print(f"Category  : {article.category.value}")
    print(f"Status    : {article.status.value}")
    print("Serialization test: PASSED")


if __name__ == "__main__":
    _run_self_test()