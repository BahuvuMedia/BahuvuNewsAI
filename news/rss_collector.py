# news/rss_collector.py

"""
BahuvuNewsAI - RSS and Atom News Collector
Version: 1.0

This module downloads RSS or Atom feeds and converts valid feed entries
into the canonical news.models.NewsArticle structure.

The collector inherits the shared lifecycle, source-state handling,
logging, and collection-result behavior from BaseNewsCollector.
"""

from __future__ import annotations

from datetime import datetime, timezone
import html
import logging
import re
import time
from typing import Any, Mapping
from urllib.parse import urljoin

import feedparser
import requests

from news.models import (
    LanguageCode,
    NewsArticle,
    SourceType,
)
from news.source_manager import (
    BaseNewsCollector,
    CollectorConnectionError,
    CollectorFetchError,
    CollectorNormalizationError,
    SourceHealth,
)


LOGGER = logging.getLogger("BahuvuNewsAI.news.rss_collector")


# ==========================================================
# TEXT HELPERS
# ==========================================================


_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_WHITESPACE_PATTERN = re.compile(r"\s+")


def clean_feed_text(value: Any) -> str:
    """
    Convert an RSS text value into normalized plain text.

    RSS descriptions and summaries commonly contain HTML fragments,
    escaped entities, repeated whitespace, or non-breaking spaces.
    """

    if value is None:
        return ""

    text = str(value)
    text = html.unescape(text)
    text = _HTML_TAG_PATTERN.sub(" ", text)
    text = text.replace("\xa0", " ")
    text = _WHITESPACE_PATTERN.sub(" ", text)

    return text.strip()


def ensure_utc(value: datetime | None) -> datetime | None:
    """Normalize a datetime into timezone-aware UTC."""

    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def struct_time_to_datetime(value: Any) -> datetime | None:
    """
    Convert a feedparser time structure into a UTC datetime.

    feedparser exposes parsed publication dates as time.struct_time-like
    objects in fields such as published_parsed and updated_parsed.
    """

    if value is None:
        return None

    try:
        timestamp = time.mktime(value)
        local_datetime = datetime.fromtimestamp(
            timestamp,
            tz=timezone.utc,
        )
        return ensure_utc(local_datetime)
    except (TypeError, ValueError, OverflowError):
        return None


# ==========================================================
# RSS COLLECTOR
# ==========================================================


class RSSCollector(BaseNewsCollector):
    """
    Collect and normalize articles from RSS and Atom feeds.

    Supported source type:
        SourceType.RSS
    """

    supported_source_types = frozenset({SourceType.RSS})

    def __init__(self, source) -> None:
        super().__init__(source)

        self._session: requests.Session | None = None
        self._last_response_status: int | None = None
        self._last_response_time: float | None = None
        self._last_feed_metadata: dict[str, Any] = {}

    # ======================================================
    # CONNECTION LIFECYCLE
    # ======================================================

    def connect(self) -> None:
        """Create and configure the HTTP session."""

        if self.is_closed:
            raise CollectorConnectionError(
                "Cannot reconnect a closed RSSCollector instance."
            )

        if self.is_connected:
            return

        try:
            session = requests.Session()

            default_headers = {
                "User-Agent": (
                    "BahuvuNewsAI/1.0 "
                    "(RSS News Collector; +https://github.com/"
                    "BahuvuMedia/BahuvuNewsAI)"
                ),
                "Accept": (
                    "application/rss+xml, "
                    "application/atom+xml, "
                    "application/xml, "
                    "text/xml, "
                    "*/*;q=0.8"
                ),
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
            }

            session.headers.update(default_headers)

            if self.source.headers:
                session.headers.update(self.source.headers)

            self._session = session
            self._mark_connected()

            LOGGER.debug(
                "RSS session connected | source=%s",
                self.source.name,
            )

        except Exception as error:
            raise CollectorConnectionError(
                f"Unable to initialize RSS session: {error}"
            ) from error

    def close(self) -> None:
        """Close the HTTP session safely."""

        if self._session is not None:
            try:
                self._session.close()
            finally:
                self._session = None

        self._mark_closed()

        LOGGER.debug(
            "RSS session closed | source=%s",
            self.source.name,
        )

    # ======================================================
    # NETWORK FETCH
    # ======================================================

    def fetch(self) -> Any:
        """
        Download and parse the configured RSS or Atom feed.

        Returns:
            A list of feedparser entry objects.
        """

        if not self.is_connected or self._session is None:
            raise CollectorConnectionError(
                "RSSCollector must be connected before fetching."
            )

        started_at = time.perf_counter()

        try:
            response = self._session.get(
                self.source.url,
                timeout=self.source.request_timeout_seconds,
                allow_redirects=True,
            )

            self._last_response_time = (
                time.perf_counter() - started_at
            )
            self._last_response_status = response.status_code

            response.raise_for_status()

        except requests.Timeout as error:
            raise CollectorFetchError(
                "RSS request timed out after "
                f"{self.source.request_timeout_seconds} seconds."
            ) from error

        except requests.ConnectionError as error:
            raise CollectorFetchError(
                f"Unable to connect to RSS source: {error}"
            ) from error

        except requests.HTTPError as error:
            status_code = (
                error.response.status_code
                if error.response is not None
                else self._last_response_status
            )

            raise CollectorFetchError(
                f"RSS source returned HTTP status {status_code}."
            ) from error

        except requests.RequestException as error:
            raise CollectorFetchError(
                f"RSS request failed: {error}"
            ) from error

        parsed_feed = feedparser.parse(response.content)

        if getattr(parsed_feed, "bozo", False):
            bozo_exception = getattr(
                parsed_feed,
                "bozo_exception",
                None,
            )

            entries = list(
                getattr(parsed_feed, "entries", []) or []
            )

            if not entries:
                raise CollectorFetchError(
                    "RSS feed could not be parsed"
                    + (
                        f": {bozo_exception}"
                        if bozo_exception
                        else "."
                    )
                )

            LOGGER.warning(
                "RSS feed contained a recoverable parsing issue | "
                "source=%s | error=%s",
                self.source.name,
                bozo_exception,
            )

        entries = list(
            getattr(parsed_feed, "entries", []) or []
        )

        feed_metadata = getattr(parsed_feed, "feed", {}) or {}

        self._last_feed_metadata = {
            "feed_title": clean_feed_text(
                self._value(feed_metadata, "title")
            ),
            "feed_link": str(
                self._value(feed_metadata, "link") or ""
            ).strip(),
            "feed_language": str(
                self._value(feed_metadata, "language") or ""
            ).strip(),
            "http_status": self._last_response_status,
            "response_time_seconds": self._last_response_time,
            "entry_count": len(entries),
            "resolved_url": response.url,
        }

        LOGGER.info(
            "RSS feed downloaded | source=%s | status=%s | entries=%s",
            self.source.name,
            self._last_response_status,
            len(entries),
        )

        return entries

    # ======================================================
    # ENTRY VALIDATION
    # ======================================================

    def validate_item(self, raw_item: Any) -> bool:
        """
        Validate one RSS or Atom entry before normalization.

        A valid entry must contain both a non-empty title and a valid-looking
        HTTP or HTTPS article URL.
        """

        if raw_item is None:
            return False

        title = clean_feed_text(
            self._value(raw_item, "title")
        )

        article_url = self._extract_entry_url(raw_item)

        if not title:
            return False

        if not article_url:
            return False

        return article_url.startswith(
            ("http://", "https://")
        )

    # ======================================================
    # NORMALIZATION
    # ======================================================

    def normalize_item(self, raw_item: Any) -> NewsArticle:
        """Convert one feed entry into a canonical NewsArticle."""

        title = clean_feed_text(
            self._value(raw_item, "title")
        )

        article_url = self._extract_entry_url(raw_item)

        if not title:
            raise CollectorNormalizationError(
                "RSS entry title is empty."
            )

        if not article_url:
            raise CollectorNormalizationError(
                "RSS entry URL is empty."
            )

        description = self._extract_description(raw_item)
        raw_text = self._extract_content(raw_item)

        if not raw_text:
            raw_text = description

        author = clean_feed_text(
            self._value(raw_item, "author")
            or self._value(raw_item, "dc_creator")
        )

        published_at = self._extract_published_datetime(
            raw_item
        )

        image_url = self._extract_image_url(raw_item)

        categories = self._extract_tags(raw_item)

        entry_id = clean_feed_text(
            self._value(raw_item, "id")
            or self._value(raw_item, "guid")
        )

        metadata = {
            "collector": self.__class__.__name__,
            "feed_url": self.source.url,
            "feed_entry_id": entry_id,
            "feed_title": self._last_feed_metadata.get(
                "feed_title",
                "",
            ),
            "feed_language": self._last_feed_metadata.get(
                "feed_language",
                "",
            ),
        }

        article = NewsArticle(
            title=title,
            url=article_url,
            canonical_url=article_url,
            source_id=self.source.source_id,
            source_name=self.source.name,
            publisher=(
                self.source.publisher
                or self._last_feed_metadata.get(
                    "feed_title",
                    "",
                )
            ),
            author=author,
            description=description,
            raw_text=raw_text,
            image_url=image_url,
            published_at=published_at,
            category=self.source.default_category,
            language=self.source.language,
            reliability_score=self.source.reliability_score,
            tags=categories,
            metadata=metadata,
        )

        return article

    # ======================================================
    # HEALTH CHECK
    # ======================================================

    def health_check(self) -> SourceHealth:
        """
        Perform a lightweight source availability check.

        The health check uses an HTTP GET because many RSS servers either do
        not support HEAD requests or return inaccurate HEAD responses.
        """

        temporary_connection = False
        started_at = time.perf_counter()

        try:
            if not self.is_connected:
                self.connect()
                temporary_connection = True

            if self._session is None:
                raise CollectorConnectionError(
                    "RSS HTTP session is unavailable."
                )

            response = self._session.get(
                self.source.url,
                timeout=self.source.request_timeout_seconds,
                allow_redirects=True,
                stream=True,
            )

            response_time = time.perf_counter() - started_at
            status_code = response.status_code

            response.raise_for_status()

            return SourceHealth(
                source_id=self.source.source_id,
                source_name=self.source.name,
                status=self.source.status,
                healthy=True,
                message=f"RSS source returned HTTP {status_code}.",
                response_time_seconds=response_time,
                metadata={
                    "http_status": status_code,
                    "resolved_url": response.url,
                },
            )

        except Exception as error:
            response_time = time.perf_counter() - started_at

            return SourceHealth(
                source_id=self.source.source_id,
                source_name=self.source.name,
                status=self.source.status,
                healthy=False,
                message=(
                    f"{error.__class__.__name__}: {error}"
                ),
                response_time_seconds=response_time,
                metadata={
                    "http_status": self._last_response_status,
                },
            )

        finally:
            if temporary_connection:
                self.close()

    # ======================================================
    # RSS FIELD EXTRACTION
    # ======================================================

    @staticmethod
    def _value(container: Any, key: str) -> Any:
        """Read a field from either a mapping or feedparser object."""

        if container is None:
            return None

        if isinstance(container, Mapping):
            return container.get(key)

        return getattr(container, key, None)

    def _extract_entry_url(self, raw_item: Any) -> str:
        """Extract and normalize the primary URL from a feed entry."""

        direct_link = str(
            self._value(raw_item, "link") or ""
        ).strip()

        if direct_link:
            return urljoin(self.source.url, direct_link)

        links = self._value(raw_item, "links") or []

        for link_item in links:
            href = str(
                self._value(link_item, "href") or ""
            ).strip()

            relation = str(
                self._value(link_item, "rel") or ""
            ).strip().casefold()

            if href and relation in {"", "alternate"}:
                return urljoin(self.source.url, href)

        return ""

    def _extract_description(self, raw_item: Any) -> str:
        """Extract the best short description from a feed entry."""

        candidates = (
            self._value(raw_item, "summary"),
            self._value(raw_item, "description"),
            self._value(raw_item, "subtitle"),
        )

        for candidate in candidates:
            cleaned = clean_feed_text(candidate)

            if cleaned:
                return cleaned

        return ""

    def _extract_content(self, raw_item: Any) -> str:
        """Extract the longest available article-content fragment."""

        content_items = self._value(raw_item, "content") or []

        extracted_values: list[str] = []

        for content_item in content_items:
            value = self._value(content_item, "value")
            cleaned = clean_feed_text(value)

            if cleaned:
                extracted_values.append(cleaned)

        if extracted_values:
            return max(extracted_values, key=len)

        return ""

    def _extract_published_datetime(
        self,
        raw_item: Any,
    ) -> datetime | None:
        """Extract the best parsed publication or update datetime."""

        parsed_candidates = (
            self._value(raw_item, "published_parsed"),
            self._value(raw_item, "updated_parsed"),
            self._value(raw_item, "created_parsed"),
        )

        for candidate in parsed_candidates:
            converted = struct_time_to_datetime(candidate)

            if converted is not None:
                return converted

        return None

    def _extract_image_url(self, raw_item: Any) -> str:
        """Extract the best candidate image URL from an RSS entry."""

        media_content = (
            self._value(raw_item, "media_content") or []
        )

        for media_item in media_content:
            media_url = str(
                self._value(media_item, "url") or ""
            ).strip()

            media_type = str(
                self._value(media_item, "type") or ""
            ).strip().casefold()

            medium = str(
                self._value(media_item, "medium") or ""
            ).strip().casefold()

            if (
                media_url
                and (
                    media_type.startswith("image/")
                    or medium == "image"
                    or not media_type
                )
            ):
                return urljoin(self.source.url, media_url)

        media_thumbnail = (
            self._value(raw_item, "media_thumbnail") or []
        )

        for thumbnail in media_thumbnail:
            thumbnail_url = str(
                self._value(thumbnail, "url") or ""
            ).strip()

            if thumbnail_url:
                return urljoin(
                    self.source.url,
                    thumbnail_url,
                )

        enclosures = self._value(raw_item, "enclosures") or []

        for enclosure in enclosures:
            enclosure_url = str(
                self._value(enclosure, "href")
                or self._value(enclosure, "url")
                or ""
            ).strip()

            enclosure_type = str(
                self._value(enclosure, "type") or ""
            ).strip().casefold()

            if (
                enclosure_url
                and (
                    enclosure_type.startswith("image/")
                    or not enclosure_type
                )
            ):
                return urljoin(
                    self.source.url,
                    enclosure_url,
                )

        return ""

    def _extract_tags(self, raw_item: Any) -> list[str]:
        """Extract normalized category labels from a feed entry."""

        tags = self._value(raw_item, "tags") or []

        results: list[str] = []
        seen: set[str] = set()

        for tag in tags:
            term = clean_feed_text(
                self._value(tag, "term")
                or self._value(tag, "label")
            )

            if not term:
                continue

            key = term.casefold()

            if key not in seen:
                seen.add(key)
                results.append(term)

        return results


# ==========================================================
# MODULE SELF-TEST
# ==========================================================


def _run_self_test() -> None:
    """
    Run a deterministic, network-free RSS normalization test.

    The self-test deliberately does not depend on a live news website.
    """

    from news.models import (
        NewsCategory,
        NewsSource,
    )

    sample_source = NewsSource(
        name="Bahuvu RSS Test",
        source_type=SourceType.RSS,
        url="https://example.com/rss.xml",
        publisher="Bahuvu Test Publisher",
        default_category=NewsCategory.NATIONAL,
        language=LanguageCode.ENGLISH,
        reliability_score=80.0,
    )

    collector = RSSCollector(sample_source)

    collector._last_feed_metadata = {
        "feed_title": "Bahuvu Test Feed",
        "feed_language": "en",
    }

    sample_entry = {
        "id": "test-entry-001",
        "title": "  Sample &amp; Verified News Headline  ",
        "link": "https://example.com/articles/test-story",
        "summary": (
            "<p>This is a <strong>sample</strong> article summary.</p>"
        ),
        "author": "Test Reporter",
        "media_content": [
            {
                "url": "https://example.com/images/test.jpg",
                "type": "image/jpeg",
            }
        ],
        "tags": [
            {"term": "National"},
            {"term": "Testing"},
        ],
    }

    assert collector.validate_item(sample_entry) is True

    article = collector.normalize_item(sample_entry)

    assert article.title == "Sample & Verified News Headline"
    assert article.url == (
        "https://example.com/articles/test-story"
    )
    assert article.source_id == sample_source.source_id
    assert article.source_name == sample_source.name
    assert article.publisher == "Bahuvu Test Publisher"
    assert article.description == (
        "This is a sample article summary."
    )
    assert article.raw_text == article.description
    assert article.image_url == (
        "https://example.com/images/test.jpg"
    )
    assert article.tags == ["National", "Testing"]
    assert article.reliability_score == 80.0
    assert article.category == NewsCategory.NATIONAL
    assert article.language == LanguageCode.ENGLISH

    health = SourceHealth(
        source_id=sample_source.source_id,
        source_name=sample_source.name,
        status=sample_source.status,
        healthy=True,
        message="Self-test health check.",
        response_time_seconds=0.01,
    )

    assert health.healthy is True

    collector.close()

    print("RSS collector initialized successfully.")
    print(f"Article title: {article.title}")
    print(f"Article source: {article.source_name}")
    print(f"Article category: {article.category.value}")
    print(f"Article tags: {', '.join(article.tags)}")
    print("RSS collector self-test passed.")


if __name__ == "__main__":
    _run_self_test()