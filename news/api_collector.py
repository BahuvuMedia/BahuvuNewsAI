# news/api_collector.py

"""
BahuvuNewsAI - JSON News API Collector
Version: 1.0

This module collects news from configurable HTTP JSON APIs and converts
API records into the canonical news.models.NewsArticle structure.

The collector supports:

- GET and POST requests
- Query parameters
- JSON request bodies
- Custom headers
- Environment-variable API keys
- Nested JSON response paths
- Configurable article field mappings
- ISO-8601 and Unix publication timestamps
- Relative URL resolution
- Deterministic network-free self-testing

API-specific behaviour is configured through NewsSource.metadata.
"""

from __future__ import annotations

from datetime import datetime, timezone
import html
import logging
import os
import re
import time
from typing import Any, Iterable, Mapping
from urllib.parse import urljoin

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


LOGGER = logging.getLogger("BahuvuNewsAI.news.api_collector")


# ==========================================================
# CONSTANTS
# ==========================================================


_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_WHITESPACE_PATTERN = re.compile(r"\s+")

DEFAULT_FIELD_MAP: dict[str, str] = {
    "title": "title",
    "url": "url",
    "description": "description",
    "content": "content",
    "author": "author",
    "publisher": "source.name",
    "image_url": "urlToImage",
    "published_at": "publishedAt",
    "canonical_url": "url",
    "keywords": "keywords",
    "tags": "tags",
    "article_id": "id",
}

ALLOWED_HTTP_METHODS = frozenset({"GET", "POST"})


# ==========================================================
# TEXT AND VALUE HELPERS
# ==========================================================


def clean_api_text(value: Any) -> str:
    """
    Convert an API text value into normalized plain text.

    API fields may contain HTML fragments, escaped entities, non-breaking
    spaces, or repeated whitespace.
    """

    if value is None:
        return ""

    if isinstance(value, (dict, list, tuple, set)):
        return ""

    text = html.unescape(str(value))
    text = _HTML_TAG_PATTERN.sub(" ", text)
    text = text.replace("\xa0", " ")
    text = _WHITESPACE_PATTERN.sub(" ", text)

    return text.strip()


def get_nested_value(
    container: Any,
    path: str,
    default: Any = None,
) -> Any:
    """
    Read a nested value using a dot-separated path.

    Examples:

        get_nested_value(data, "source.name")
        get_nested_value(data, "response.articles")
        get_nested_value(data, "items.0.title")

    Dictionary keys and numeric list indexes are supported.
    """

    normalized_path = str(path or "").strip()

    if not normalized_path:
        return container

    current = container

    for part in normalized_path.split("."):
        if current is None:
            return default

        if isinstance(current, Mapping):
            if part not in current:
                return default

            current = current[part]
            continue

        if isinstance(current, (list, tuple)):
            try:
                index = int(part)
                current = current[index]
            except (
                ValueError,
                IndexError,
                TypeError,
            ):
                return default

            continue

        try:
            current = getattr(current, part)
        except AttributeError:
            return default

    return current


def first_non_empty(
    container: Any,
    paths: Iterable[str],
) -> Any:
    """Return the first non-empty value found among several paths."""

    for path in paths:
        value = get_nested_value(container, path)

        if value is None:
            continue

        if isinstance(value, str) and not value.strip():
            continue

        if isinstance(value, (list, tuple, dict)) and not value:
            continue

        return value

    return None


def normalize_string_list(value: Any) -> list[str]:
    """
    Convert common API list formats into a normalized string list.

    Accepted formats:

    - ["Politics", "India"]
    - "Politics, India"
    - "Politics; India"
    - [{"name": "Politics"}, {"name": "India"}]
    """

    if value is None:
        return []

    raw_values: list[Any]

    if isinstance(value, str):
        raw_values = re.split(r"[,;|]", value)

    elif isinstance(value, Mapping):
        raw_values = list(value.values())

    elif isinstance(value, Iterable):
        raw_values = list(value)

    else:
        raw_values = [value]

    results: list[str] = []
    seen: set[str] = set()

    for item in raw_values:
        if isinstance(item, Mapping):
            item = first_non_empty(
                item,
                (
                    "name",
                    "label",
                    "term",
                    "title",
                    "value",
                ),
            )

        normalized = clean_api_text(item)

        if not normalized:
            continue

        key = normalized.casefold()

        if key not in seen:
            seen.add(key)
            results.append(normalized)

    return results


def parse_api_datetime(value: Any) -> datetime | None:
    """
    Parse common API date formats into timezone-aware UTC datetimes.

    Supported values include:

    - ISO-8601 strings
    - Strings ending with Z
    - Unix timestamps in seconds
    - Unix timestamps in milliseconds
    - Existing datetime objects
    """

    if value is None or value == "":
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)

        return value.astimezone(timezone.utc)

    if isinstance(value, (int, float)):
        timestamp = float(value)

        if timestamp > 10_000_000_000:
            timestamp /= 1000.0

        try:
            return datetime.fromtimestamp(
                timestamp,
                tz=timezone.utc,
            )
        except (
            ValueError,
            OverflowError,
            OSError,
        ):
            return None

    text = str(value).strip()

    if not text:
        return None

    if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        try:
            return parse_api_datetime(float(text))
        except ValueError:
            return None

    normalized = text

    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None

    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

    fallback_formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
    )

    for date_format in fallback_formats:
        try:
            parsed = datetime.strptime(text, date_format)

            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)

            return parsed.astimezone(timezone.utc)

        except ValueError:
            continue

    return None


# ==========================================================
# API COLLECTOR
# ==========================================================


class APICollector(BaseNewsCollector):
    """
    Collect articles from a configurable JSON news API.

    Supported NewsSource type:
        SourceType.API

    NewsSource.metadata configuration:

        method:
            "GET" or "POST". Default: "GET"

        items_path:
            Dot-separated path to the article list.
            Examples: "articles", "data.items", "response.results"

        field_map:
            Mapping from canonical field names to API JSON paths.

        params:
            Static query-string parameters.

        json_body:
            JSON body for POST requests.

        api_key_env:
            Environment-variable name containing an API key.

        api_key_header:
            Header in which to send the API key.

        api_key_query_param:
            Query parameter in which to send the API key.

        api_key_prefix:
            Optional prefix such as "Bearer ".

        response_metadata_paths:
            Optional mapping of metadata names to response paths.
    """

    supported_source_types = frozenset({SourceType.API})

    def __init__(self, source) -> None:
        super().__init__(source)

        self._session: requests.Session | None = None
        self._last_response_status: int | None = None
        self._last_response_time: float | None = None
        self._last_response_url: str = ""
        self._last_response_metadata: dict[str, Any] = {}

        self._method = str(
            self.source.metadata.get("method", "GET")
        ).strip().upper()

        if self._method not in ALLOWED_HTTP_METHODS:
            raise ValueError(
                "APICollector metadata method must be GET or POST."
            )

        raw_field_map = self.source.metadata.get("field_map") or {}

        if not isinstance(raw_field_map, Mapping):
            raise ValueError(
                "APICollector metadata field_map must be a mapping."
            )

        self._field_map = {
            **DEFAULT_FIELD_MAP,
            **{
                str(key): str(value)
                for key, value in raw_field_map.items()
            },
        }

        self._items_path = str(
            self.source.metadata.get("items_path", "articles")
        ).strip()

    # ======================================================
    # CONNECTION LIFECYCLE
    # ======================================================

    def connect(self) -> None:
        """Create and configure the HTTP session."""

        if self.is_closed:
            raise CollectorConnectionError(
                "Cannot reconnect a closed APICollector instance."
            )

        if self.is_connected:
            return

        try:
            session = requests.Session()

            default_headers = {
                "User-Agent": (
                    "BahuvuNewsAI/1.0 "
                    "(JSON News API Collector; "
                    "https://github.com/BahuvuMedia/BahuvuNewsAI)"
                ),
                "Accept": "application/json",
                "Connection": "keep-alive",
            }

            session.headers.update(default_headers)

            if self.source.headers:
                session.headers.update(self.source.headers)

            api_key_header, api_key_value = (
                self._resolve_api_key_header()
            )

            if api_key_header and api_key_value:
                session.headers[api_key_header] = api_key_value

            self._session = session
            self._mark_connected()

            LOGGER.debug(
                "API session connected | source=%s",
                self.source.name,
            )

        except Exception as error:
            raise CollectorConnectionError(
                f"Unable to initialize API session: {error}"
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
            "API session closed | source=%s",
            self.source.name,
        )

    # ======================================================
    # REQUEST CONFIGURATION
    # ======================================================

    def _resolve_api_key(self) -> str:
        """Resolve an API key from source metadata and environment."""

        environment_name = str(
            self.source.metadata.get("api_key_env", "")
        ).strip()

        if not environment_name:
            return ""

        value = os.getenv(environment_name, "").strip()

        if not value:
            raise CollectorConnectionError(
                f"Environment variable '{environment_name}' "
                "is not configured."
            )

        prefix = str(
            self.source.metadata.get("api_key_prefix", "")
        )

        return f"{prefix}{value}"

    def _resolve_api_key_header(self) -> tuple[str, str]:
        """Return the configured API-key header and value."""

        header_name = str(
            self.source.metadata.get("api_key_header", "")
        ).strip()

        if not header_name:
            return "", ""

        return header_name, self._resolve_api_key()

    def _build_params(self) -> dict[str, Any]:
        """Build query parameters for the API request."""

        raw_params = self.source.metadata.get("params") or {}

        if not isinstance(raw_params, Mapping):
            raise CollectorFetchError(
                "API metadata params must be a mapping."
            )

        params = dict(raw_params)

        query_key_name = str(
            self.source.metadata.get(
                "api_key_query_param",
                "",
            )
        ).strip()

        if query_key_name:
            params[query_key_name] = self._resolve_api_key()

        return params

    def _build_json_body(self) -> dict[str, Any] | None:
        """Build an optional JSON request body."""

        raw_body = self.source.metadata.get("json_body")

        if raw_body is None:
            return None

        if not isinstance(raw_body, Mapping):
            raise CollectorFetchError(
                "API metadata json_body must be a mapping."
            )

        return dict(raw_body)

    # ======================================================
    # NETWORK FETCH
    # ======================================================

    def fetch(self) -> Any:
        """
        Request JSON data and return the configured article collection.

        The API response itself may be a list or a nested JSON object.
        """

        if not self.is_connected or self._session is None:
            raise CollectorConnectionError(
                "APICollector must be connected before fetching."
            )

        params = self._build_params()
        json_body = self._build_json_body()

        started_at = time.perf_counter()

        try:
            response = self._session.request(
                method=self._method,
                url=self.source.url,
                params=params or None,
                json=json_body,
                timeout=self.source.request_timeout_seconds,
                allow_redirects=True,
            )

            self._last_response_time = (
                time.perf_counter() - started_at
            )
            self._last_response_status = response.status_code
            self._last_response_url = response.url

            response.raise_for_status()

        except requests.Timeout as error:
            raise CollectorFetchError(
                "API request timed out after "
                f"{self.source.request_timeout_seconds} seconds."
            ) from error

        except requests.ConnectionError as error:
            raise CollectorFetchError(
                f"Unable to connect to news API: {error}"
            ) from error

        except requests.HTTPError as error:
            status_code = (
                error.response.status_code
                if error.response is not None
                else self._last_response_status
            )

            response_excerpt = ""

            if error.response is not None:
                response_excerpt = clean_api_text(
                    error.response.text[:300]
                )

            message = (
                f"News API returned HTTP status {status_code}."
            )

            if response_excerpt:
                message += f" Response: {response_excerpt}"

            raise CollectorFetchError(message) from error

        except requests.RequestException as error:
            raise CollectorFetchError(
                f"News API request failed: {error}"
            ) from error

        try:
            payload = response.json()
        except ValueError as error:
            content_type = response.headers.get(
                "Content-Type",
                "",
            )

            raise CollectorFetchError(
                "News API response was not valid JSON. "
                f"Content-Type: {content_type or 'unknown'}."
            ) from error

        items = self._extract_items(payload)

        self._last_response_metadata = (
            self._extract_response_metadata(payload)
        )

        self._last_response_metadata.update(
            {
                "http_status": self._last_response_status,
                "response_time_seconds": (
                    self._last_response_time
                ),
                "resolved_url": self._last_response_url,
                "item_count": len(items),
            }
        )

        LOGGER.info(
            "API response downloaded | source=%s | "
            "status=%s | items=%s",
            self.source.name,
            self._last_response_status,
            len(items),
        )

        return items

    def _extract_items(self, payload: Any) -> list[Any]:
        """Extract the article list from an API response payload."""

        if isinstance(payload, list):
            return payload

        if not isinstance(payload, Mapping):
            raise CollectorFetchError(
                "News API JSON response must be an object or list."
            )

        items = get_nested_value(
            payload,
            self._items_path,
        )

        if items is None:
            alternative_paths = (
                "articles",
                "items",
                "results",
                "data",
                "data.articles",
                "data.items",
                "data.results",
                "response.articles",
                "response.items",
                "response.results",
            )

            items = first_non_empty(
                payload,
                alternative_paths,
            )

        if items is None:
            raise CollectorFetchError(
                "Unable to locate an article list in the API response. "
                f"Configured items_path: '{self._items_path}'."
            )

        if isinstance(items, Mapping):
            nested_items = first_non_empty(
                items,
                (
                    "articles",
                    "items",
                    "results",
                    "data",
                ),
            )

            if nested_items is not None:
                items = nested_items

        if not isinstance(items, list):
            raise CollectorFetchError(
                "Configured API items path did not resolve to a list."
            )

        return items

    def _extract_response_metadata(
        self,
        payload: Any,
    ) -> dict[str, Any]:
        """Extract optional provider metadata from the response."""

        configured_paths = self.source.metadata.get(
            "response_metadata_paths"
        ) or {}

        if not isinstance(configured_paths, Mapping):
            return {}

        result: dict[str, Any] = {}

        for metadata_name, path in configured_paths.items():
            value = get_nested_value(
                payload,
                str(path),
            )

            if value is not None:
                result[str(metadata_name)] = value

        return result

    # ======================================================
    # ITEM VALIDATION
    # ======================================================

    def validate_item(self, raw_item: Any) -> bool:
        """
        Validate one API article before normalization.

        Every accepted item must contain a title and HTTP/HTTPS URL.
        """

        if not isinstance(raw_item, Mapping):
            return False

        title = clean_api_text(
            self._mapped_value(raw_item, "title")
        )

        article_url = self._extract_url(raw_item, "url")

        if not title or not article_url:
            return False

        return article_url.startswith(
            ("http://", "https://")
        )

    # ======================================================
    # ARTICLE NORMALIZATION
    # ======================================================

    def normalize_item(self, raw_item: Any) -> NewsArticle:
        """Convert one API record into a canonical NewsArticle."""

        if not isinstance(raw_item, Mapping):
            raise CollectorNormalizationError(
                "API article item must be a mapping."
            )

        title = clean_api_text(
            self._mapped_value(raw_item, "title")
        )
        article_url = self._extract_url(raw_item, "url")

        if not title:
            raise CollectorNormalizationError(
                "API article title is empty."
            )

        if not article_url:
            raise CollectorNormalizationError(
                "API article URL is empty."
            )

        description = clean_api_text(
            self._mapped_value(raw_item, "description")
        )

        raw_text = clean_api_text(
            self._mapped_value(raw_item, "content")
        )

        if not raw_text:
            raw_text = description

        author = clean_api_text(
            self._mapped_value(raw_item, "author")
        )

        publisher = clean_api_text(
            self._mapped_value(raw_item, "publisher")
        )

        if not publisher:
            publisher = (
                self.source.publisher
                or self.source.name
            )

        image_url = self._extract_url(
            raw_item,
            "image_url",
        )

        canonical_url = self._extract_url(
            raw_item,
            "canonical_url",
        )

        if not canonical_url:
            canonical_url = article_url

        published_at = parse_api_datetime(
            self._mapped_value(
                raw_item,
                "published_at",
            )
        )

        keywords = normalize_string_list(
            self._mapped_value(raw_item, "keywords")
        )

        tags = normalize_string_list(
            self._mapped_value(raw_item, "tags")
        )

        provider_article_id = clean_api_text(
            self._mapped_value(raw_item, "article_id")
        )

        metadata = {
            "collector": self.__class__.__name__,
            "api_url": self.source.url,
            "provider_article_id": provider_article_id,
            "http_status": self._last_response_status,
            "resolved_api_url": self._last_response_url,
        }

        configured_metadata_fields = self.source.metadata.get(
            "article_metadata_fields"
        ) or {}

        if isinstance(configured_metadata_fields, Mapping):
            for metadata_name, path in (
                configured_metadata_fields.items()
            ):
                value = get_nested_value(
                    raw_item,
                    str(path),
                )

                if value is not None:
                    metadata[str(metadata_name)] = value

        article = NewsArticle(
            title=title,
            url=article_url,
            canonical_url=canonical_url,
            source_id=self.source.source_id,
            source_name=self.source.name,
            publisher=publisher,
            author=author,
            description=description,
            raw_text=raw_text,
            image_url=image_url,
            published_at=published_at,
            category=self.source.default_category,
            language=self.source.language,
            reliability_score=self.source.reliability_score,
            keywords=keywords,
            tags=tags,
            metadata=metadata,
        )

        return article

    def _mapped_value(
        self,
        raw_item: Any,
        canonical_name: str,
    ) -> Any:
        """Read an API field using the configured canonical mapping."""

        path = self._field_map.get(canonical_name, "")

        if not path:
            return None

        return get_nested_value(raw_item, path)

    def _extract_url(
        self,
        raw_item: Any,
        canonical_name: str,
    ) -> str:
        """Extract and resolve a mapped URL."""

        value = self._mapped_value(
            raw_item,
            canonical_name,
        )

        cleaned = str(value or "").strip()

        if not cleaned:
            return ""

        return urljoin(self.source.url, cleaned)

    # ======================================================
    # HEALTH CHECK
    # ======================================================

    def health_check(self) -> SourceHealth:
        """
        Check whether the configured API endpoint is reachable.

        This check validates HTTP availability but does not modify the
        NewsSource success/failure counters.
        """

        temporary_connection = False
        started_at = time.perf_counter()
        response: requests.Response | None = None

        try:
            if not self.is_connected:
                self.connect()
                temporary_connection = True

            if self._session is None:
                raise CollectorConnectionError(
                    "API HTTP session is unavailable."
                )

            response = self._session.request(
                method=self._method,
                url=self.source.url,
                params=self._build_params() or None,
                json=self._build_json_body(),
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
                message=(
                    f"News API returned HTTP {status_code}."
                ),
                response_time_seconds=response_time,
                metadata={
                    "http_status": status_code,
                    "resolved_url": response.url,
                    "method": self._method,
                },
            )

        except Exception as error:
            response_time = time.perf_counter() - started_at

            status_code = (
                response.status_code
                if response is not None
                else None
            )

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
                    "http_status": status_code,
                    "method": self._method,
                },
            )

        finally:
            if response is not None:
                response.close()

            if temporary_connection:
                self.close()


# ==========================================================
# MODULE SELF-TEST
# ==========================================================


def _run_self_test() -> None:
    """
    Run deterministic, network-free API normalization tests.

    No real API key or external HTTP connection is required.
    """

    from news.models import (
        NewsCategory,
        NewsSource,
    )

    sample_source = NewsSource(
        name="Bahuvu API Test",
        source_type=SourceType.API,
        url="https://example.com/api/news",
        publisher="Bahuvu API Publisher",
        default_category=NewsCategory.TECHNOLOGY,
        language=LanguageCode.ENGLISH,
        reliability_score=85.0,
        metadata={
            "method": "GET",
            "items_path": "response.articles",
            "field_map": {
                "title": "headline",
                "url": "links.web",
                "description": "summary",
                "content": "body",
                "author": "byline.name",
                "publisher": "publisher.name",
                "image_url": "media.image",
                "published_at": "dates.published",
                "canonical_url": "links.canonical",
                "keywords": "keywords",
                "tags": "categories",
                "article_id": "identifier",
            },
        },
    )

    collector = APICollector(sample_source)

    sample_payload = {
        "response": {
            "status": "ok",
            "articles": [
                {
                    "identifier": "api-story-001",
                    "headline": (
                        "  New &amp; Verified Technology Story  "
                    ),
                    "links": {
                        "web": (
                            "https://example.com/news/"
                            "technology-story"
                        ),
                        "canonical": (
                            "https://example.com/news/"
                            "technology-story"
                        ),
                    },
                    "summary": (
                        "<p>This is a <strong>verified</strong> "
                        "technology summary.</p>"
                    ),
                    "body": (
                        "<p>This is the complete technology "
                        "article content.</p>"
                    ),
                    "byline": {
                        "name": "API Reporter",
                    },
                    "publisher": {
                        "name": "Example Technology News",
                    },
                    "media": {
                        "image": (
                            "https://example.com/images/"
                            "technology.jpg"
                        ),
                    },
                    "dates": {
                        "published": "2026-07-10T10:30:00Z",
                    },
                    "keywords": [
                        "Artificial Intelligence",
                        "Technology",
                    ],
                    "categories": "Innovation, Science",
                }
            ],
        }
    }

    extracted_items = collector._extract_items(
        sample_payload
    )

    assert len(extracted_items) == 1

    sample_item = extracted_items[0]

    assert collector.validate_item(sample_item) is True

    article = collector.normalize_item(sample_item)

    assert article.title == (
        "New & Verified Technology Story"
    )
    assert article.url == (
        "https://example.com/news/technology-story"
    )
    assert article.canonical_url == article.url
    assert article.source_id == sample_source.source_id
    assert article.source_name == sample_source.name
    assert article.publisher == (
        "Example Technology News"
    )
    assert article.author == "API Reporter"
    assert article.description == (
        "This is a verified technology summary."
    )
    assert article.raw_text == (
        "This is the complete technology article content."
    )
    assert article.image_url == (
        "https://example.com/images/technology.jpg"
    )
    assert article.published_at is not None
    assert article.published_at.tzinfo is not None
    assert article.keywords == [
        "Artificial Intelligence",
        "Technology",
    ]
    assert article.tags == [
        "Innovation",
        "Science",
    ]
    assert article.reliability_score == 85.0
    assert article.category == NewsCategory.TECHNOLOGY
    assert article.language == LanguageCode.ENGLISH

    assert parse_api_datetime(
        1_752_144_600
    ) is not None

    assert parse_api_datetime(
        1_752_144_600_000
    ) is not None

    assert get_nested_value(
        sample_payload,
        "response.articles.0.headline",
    ) == "  New &amp; Verified Technology Story  "

    collector.close()

    print("API collector initialized successfully.")
    print(f"Article title: {article.title}")
    print(f"Article source: {article.source_name}")
    print(f"Article publisher: {article.publisher}")
    print(f"Article category: {article.category.value}")
    print(f"Article keywords: {', '.join(article.keywords)}")
    print("API collector self-test passed.")


if __name__ == "__main__":
    _run_self_test()