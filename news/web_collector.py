# news/web_collector.py

"""
BahuvuNewsAI - Web Article Collector
Version: 1.0

This module downloads individual news webpages and converts them into the
canonical news.models.NewsArticle structure.

The collector supports:

- Standard HTML news webpages
- Open Graph metadata
- Twitter Card metadata
- Schema.org JSON-LD metadata
- Canonical URL discovery
- Headline, author, publisher, date, image, and description extraction
- Main article-body extraction
- CSS-selector overrides through NewsSource.metadata
- Relative URL resolution
- Timezone-aware publication dates
- Robust HTTP error handling
- Deterministic network-free self-testing

The collector inherits the shared lifecycle, result tracking, logging,
source-state handling, and error behavior from BaseNewsCollector.
"""

from __future__ import annotations

from datetime import datetime, timezone
import html
import json
import logging
import re
import time
from typing import Any, Iterable, Mapping
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag
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


LOGGER = logging.getLogger("BahuvuNewsAI.news.web_collector")


# ==========================================================
# CONSTANTS
# ==========================================================

_WHITESPACE_PATTERN = re.compile(r"\s+")
_DATE_PREFIX_PATTERN = re.compile(
    r"^(published|updated|posted|last updated)\s*:?\s*",
    flags=re.IGNORECASE,
)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36 "
    "BahuvuNewsAI/1.0"
)

DEFAULT_ACCEPT_HEADER = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,*/*;q=0.8"
)

ARTICLE_BODY_SELECTORS = (
    "article",
    "[itemprop='articleBody']",
    "[data-testid='article-body']",
    "[data-component='text-block']",
    ".article-body",
    ".article__body",
    ".article-content",
    ".article__content",
    ".story-body",
    ".story__body",
    ".story-content",
    ".story__content",
    ".entry-content",
    ".post-content",
    ".news-content",
    ".content-body",
    "#article-body",
    "#article-content",
    "#story-body",
    "#story-content",
)

TITLE_SELECTORS = (
    "h1[itemprop='headline']",
    "article h1",
    "main h1",
    "h1",
)

AUTHOR_SELECTORS = (
    "[rel='author']",
    "[itemprop='author'] [itemprop='name']",
    "[itemprop='author']",
    ".author-name",
    ".article-author",
    ".article__author",
    ".story-author",
    ".story__author",
    ".byline",
    "[class*='author']",
    "[class*='byline']",
)

DATE_SELECTORS = (
    "time[datetime]",
    "[itemprop='datePublished']",
    "[itemprop='dateModified']",
    ".published-date",
    ".publish-date",
    ".article-date",
    ".article__date",
    ".story-date",
    ".story__date",
    "[class*='publish-date']",
    "[class*='published']",
    "[class*='timestamp']",
)

DESCRIPTION_SELECTORS = (
    "[itemprop='description']",
    ".article-summary",
    ".article__summary",
    ".story-summary",
    ".story__summary",
    ".standfirst",
    ".lead",
    ".intro",
    "article > p",
    "main > p",
)

IMAGE_SELECTORS = (
    "article img",
    "main img",
    "[itemprop='image']",
)

NOISE_SELECTORS = (
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "canvas",
    "iframe",
    "form",
    "button",
    "input",
    "select",
    "textarea",
    "nav",
    "footer",
    "aside",
    "[role='navigation']",
    "[role='complementary']",
    ".advertisement",
    ".advert",
    ".ad",
    ".ads",
    ".social-share",
    ".share-buttons",
    ".newsletter",
    ".related-articles",
    ".recommended",
    ".comments",
    "#comments",
)

JSON_LD_ARTICLE_TYPES = frozenset(
    {
        "Article",
        "NewsArticle",
        "ReportageNewsArticle",
        "AnalysisNewsArticle",
        "OpinionNewsArticle",
        "LiveBlogPosting",
        "BlogPosting",
    }
)


# ==========================================================
# TEXT HELPERS
# ==========================================================

def clean_web_text(value: Any) -> str:
    """
    Convert an extracted webpage value into normalized plain text.

    The function removes escaped HTML entities, non-breaking spaces,
    zero-width characters, repeated whitespace, and surrounding space.
    """

    if value is None:
        return ""

    if isinstance(value, (dict, list, tuple, set)):
        return ""

    text = html.unescape(str(value))
    text = text.replace("\xa0", " ")
    text = text.replace("\u200b", "")
    text = text.replace("\u200c", "")
    text = text.replace("\u200d", "")
    text = text.replace("\ufeff", "")
    text = _WHITESPACE_PATTERN.sub(" ", text)

    return text.strip()


def unique_strings(values: Iterable[Any]) -> list[str]:
    """Return normalized, case-insensitively deduplicated strings."""

    results: list[str] = []
    seen: set[str] = set()

    for value in values:
        cleaned = clean_web_text(value)

        if not cleaned:
            continue

        key = cleaned.casefold()

        if key in seen:
            continue

        seen.add(key)
        results.append(cleaned)

    return results


def normalize_url(base_url: str, value: Any) -> str:
    """
    Resolve a possibly relative URL and remove its fragment component.

    Only HTTP and HTTPS URLs are accepted.
    """

    cleaned = clean_web_text(value)

    if not cleaned:
        return ""

    resolved = urljoin(base_url, cleaned)
    parsed = urlparse(resolved)

    if parsed.scheme.casefold() not in {"http", "https"}:
        return ""

    fragmentless = parsed._replace(fragment="")

    return urlunparse(fragmentless)


def parse_web_datetime(value: Any) -> datetime | None:
    """
    Parse common webpage publication-date formats.

    Supported values include:

    - Existing datetime objects
    - ISO-8601 timestamps
    - ISO timestamps ending in Z
    - Unix seconds
    - Unix milliseconds
    - Common news publication date formats
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
        except (ValueError, OverflowError, OSError):
            return None

    text = clean_web_text(value)

    if not text:
        return None

    text = _DATE_PREFIX_PATTERN.sub("", text).strip()

    if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        try:
            return parse_web_datetime(float(text))
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
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y",
        "%B %d, %Y %I:%M %p",
        "%B %d, %Y",
        "%b %d, %Y %I:%M %p",
        "%b %d, %Y",
        "%d %B %Y %I:%M %p",
        "%d %B %Y",
        "%d %b %Y %I:%M %p",
        "%d %b %Y",
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


def normalize_keyword_list(value: Any) -> list[str]:
    """Normalize webpage keywords, tags, or article sections."""

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

    normalized: list[str] = []

    for item in raw_values:
        if isinstance(item, Mapping):
            item = (
                item.get("name")
                or item.get("title")
                or item.get("label")
                or item.get("@value")
            )

        cleaned = clean_web_text(item)

        if cleaned:
            normalized.append(cleaned)

    return unique_strings(normalized)


# ==========================================================
# JSON-LD HELPERS
# ==========================================================

def iter_json_ld_nodes(value: Any) -> Iterable[Mapping[str, Any]]:
    """Recursively yield mapping objects found in JSON-LD data."""

    if isinstance(value, Mapping):
        graph = value.get("@graph")

        if isinstance(graph, list):
            for graph_item in graph:
                yield from iter_json_ld_nodes(graph_item)

        yield value

        for key, nested_value in value.items():
            if key == "@graph":
                continue

            if isinstance(nested_value, (Mapping, list)):
                yield from iter_json_ld_nodes(nested_value)

    elif isinstance(value, list):
        for item in value:
            yield from iter_json_ld_nodes(item)


def json_ld_types(node: Mapping[str, Any]) -> set[str]:
    """Return normalized JSON-LD @type values."""

    raw_type = node.get("@type")

    if isinstance(raw_type, str):
        return {raw_type.strip()}

    if isinstance(raw_type, list):
        return {
            clean_web_text(item)
            for item in raw_type
            if clean_web_text(item)
        }

    return set()


def json_ld_person_name(value: Any) -> str:
    """Extract a person or organization name from JSON-LD data."""

    if isinstance(value, str):
        return clean_web_text(value)

    if isinstance(value, Mapping):
        return clean_web_text(
            value.get("name")
            or value.get("legalName")
            or value.get("alternateName")
        )

    if isinstance(value, list):
        names = [
            json_ld_person_name(item)
            for item in value
        ]

        return ", ".join(unique_strings(names))

    return ""


def json_ld_image_url(value: Any) -> str:
    """Extract a raw image URL from common JSON-LD image structures."""

    if isinstance(value, str):
        return clean_web_text(value)

    if isinstance(value, Mapping):
        return clean_web_text(
            value.get("url")
            or value.get("contentUrl")
            or value.get("@id")
        )

    if isinstance(value, list):
        for item in value:
            image_url = json_ld_image_url(item)

            if image_url:
                return image_url

    return ""


# ==========================================================
# WEB COLLECTOR
# ==========================================================

class WebCollector(BaseNewsCollector):
    """
    Collect and normalize one or more standard news webpages.

    Supported source type:

        SourceType.WEBSITE

    NewsSource.metadata options:

        article_urls:
            Optional list of article URLs. When omitted, source.url is
            treated as the article URL.

        title_selector:
            Optional CSS selector overriding automatic title extraction.

        description_selector:
            Optional CSS selector overriding summary extraction.

        author_selector:
            Optional CSS selector overriding author extraction.

        date_selector:
            Optional CSS selector overriding publication-date extraction.

        image_selector:
            Optional CSS selector overriding image extraction.

        article_body_selector:
            Optional CSS selector overriding article-body extraction.

        publisher_selector:
            Optional CSS selector overriding publisher extraction.

        canonical_selector:
            Optional CSS selector overriding canonical URL extraction.

        remove_selectors:
            Optional list of additional CSS selectors to remove before
            article-body extraction.

        minimum_body_characters:
            Minimum body length preferred during article-body selection.

        maximum_body_characters:
            Maximum number of article-body characters retained.

        verify_ssl:
            Whether HTTPS certificates should be verified. Default: True.

        allow_non_html:
            Whether a response with a non-HTML Content-Type may be parsed.
            Default: False.
    """

    supported_source_types = frozenset({SourceType.WEBSITE})

    def __init__(self, source) -> None:
        super().__init__(source)

        self._session: requests.Session | None = None
        self._last_response_status: int | None = None
        self._last_response_time: float | None = None
        self._last_response_url: str = ""
        self._last_content_type: str = ""
        self._last_page_metadata: dict[str, Any] = {}

        self._verify_ssl = bool(
            self.source.metadata.get("verify_ssl", True)
        )
        self._allow_non_html = bool(
            self.source.metadata.get("allow_non_html", False)
        )

        self._minimum_body_characters = self._positive_integer_metadata(
            "minimum_body_characters",
            default=200,
        )
        self._maximum_body_characters = self._positive_integer_metadata(
            "maximum_body_characters",
            default=50_000,
        )

        if (
            self._maximum_body_characters
            < self._minimum_body_characters
        ):
            raise ValueError(
                "maximum_body_characters cannot be smaller than "
                "minimum_body_characters."
            )

    # ======================================================
    # CONNECTION LIFECYCLE
    # ======================================================

    def connect(self) -> None:
        """Create and configure the HTTP session."""

        if self.is_closed:
            raise CollectorConnectionError(
                "Cannot reconnect a closed WebCollector instance."
            )

        if self.is_connected:
            return

        try:
            session = requests.Session()

            default_headers = {
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": DEFAULT_ACCEPT_HEADER,
                "Accept-Language": "en-US,en;q=0.9,te;q=0.8",
                "Accept-Encoding": "gzip, deflate",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "DNT": "1",
                "Upgrade-Insecure-Requests": "1",
            }

            session.headers.update(default_headers)

            if self.source.headers:
                session.headers.update(self.source.headers)

            self._session = session
            self._mark_connected()

            LOGGER.debug(
                "Web session connected | source=%s",
                self.source.name,
            )

        except Exception as error:
            raise CollectorConnectionError(
                f"Unable to initialize web session: {error}"
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
            "Web session closed | source=%s",
            self.source.name,
        )

    # ======================================================
    # NETWORK FETCH
    # ======================================================

    def fetch(self) -> list[dict[str, Any]]:
        """
        Download every configured article webpage.

        Each returned raw item contains the requested URL, resolved URL,
        response metadata, HTML text, and parsed BeautifulSoup document.
        """

        if not self.is_connected or self._session is None:
            raise CollectorConnectionError(
                "WebCollector must be connected before fetching."
            )

        article_urls = self._configured_article_urls()
        raw_pages: list[dict[str, Any]] = []
        page_errors: list[dict[str, str]] = []

        for article_url in article_urls:
            try:
                raw_pages.append(
                    self._fetch_single_page(article_url)
                )

            except CollectorFetchError as error:
                page_errors.append(
                    {
                        "url": article_url,
                        "error": str(error),
                    }
                )

                LOGGER.warning(
                    "Webpage fetch failed | source=%s | url=%s | error=%s",
                    self.source.name,
                    article_url,
                    error,
                )

        self._last_page_metadata = {
            "configured_page_count": len(article_urls),
            "downloaded_page_count": len(raw_pages),
            "failed_page_count": len(page_errors),
            "page_errors": page_errors,
        }

        if not raw_pages:
            if page_errors:
                error_summary = "; ".join(
                    f"{item['url']}: {item['error']}"
                    for item in page_errors[:3]
                )

                raise CollectorFetchError(
                    "Unable to download any configured webpage. "
                    f"{error_summary}"
                )

            raise CollectorFetchError(
                "No webpage URLs were configured."
            )

        LOGGER.info(
            "Webpages downloaded | source=%s | requested=%s | "
            "downloaded=%s | failed=%s",
            self.source.name,
            len(article_urls),
            len(raw_pages),
            len(page_errors),
        )

        return raw_pages

    def _fetch_single_page(
        self,
        article_url: str,
    ) -> dict[str, Any]:
        """Download and parse one webpage."""

        if self._session is None:
            raise CollectorConnectionError(
                "Web HTTP session is unavailable."
            )

        started_at = time.perf_counter()

        try:
            response = self._session.get(
                article_url,
                timeout=self.source.request_timeout_seconds,
                allow_redirects=True,
                verify=self._verify_ssl,
            )

            response_time = time.perf_counter() - started_at
            self._last_response_time = response_time
            self._last_response_status = response.status_code
            self._last_response_url = response.url
            self._last_content_type = response.headers.get(
                "Content-Type",
                "",
            )

            response.raise_for_status()

        except requests.Timeout as error:
            raise CollectorFetchError(
                "Webpage request timed out after "
                f"{self.source.request_timeout_seconds} seconds."
            ) from error

        except requests.ConnectionError as error:
            raise CollectorFetchError(
                f"Unable to connect to webpage: {error}"
            ) from error

        except requests.HTTPError as error:
            status_code = (
                error.response.status_code
                if error.response is not None
                else self._last_response_status
            )

            raise CollectorFetchError(
                f"Webpage returned HTTP status {status_code}."
            ) from error

        except requests.RequestException as error:
            raise CollectorFetchError(
                f"Webpage request failed: {error}"
            ) from error

        content_type = self._last_content_type.casefold()

        if (
            not self._allow_non_html
            and content_type
            and "html" not in content_type
            and "xhtml" not in content_type
        ):
            raise CollectorFetchError(
                "Webpage did not return HTML content. "
                f"Content-Type: {self._last_content_type}."
            )

        try:
            response.encoding = (
                response.encoding
                or response.apparent_encoding
                or "utf-8"
            )

            html_text = response.text

            if not html_text.strip():
                raise CollectorFetchError(
                    "Webpage returned an empty response body."
                )

            soup = BeautifulSoup(
                html_text,
                "html.parser",
            )

        except CollectorFetchError:
            raise

        except Exception as error:
            raise CollectorFetchError(
                f"Unable to parse webpage HTML: {error}"
            ) from error

        return {
            "requested_url": article_url,
            "resolved_url": response.url,
            "http_status": response.status_code,
            "response_time_seconds": response_time,
            "content_type": self._last_content_type,
            "html": html_text,
            "soup": soup,
            "response_headers": dict(response.headers),
        }

    # ======================================================
    # RAW ITEM VALIDATION
    # ======================================================

    def validate_item(self, raw_item: Any) -> bool:
        """
        Validate a downloaded webpage before normalization.

        A valid page must contain a BeautifulSoup document, a resolved
        HTTP/HTTPS URL, and an extractable non-empty title.
        """

        if not isinstance(raw_item, Mapping):
            return False

        soup = raw_item.get("soup")

        if not isinstance(soup, BeautifulSoup):
            return False

        resolved_url = normalize_url(
            self.source.url,
            raw_item.get("resolved_url")
            or raw_item.get("requested_url"),
        )

        if not resolved_url:
            return False

        title = self._extract_title(
            soup,
            self._extract_json_ld_article(soup),
        )

        return bool(title)

    # ======================================================
    # ARTICLE NORMALIZATION
    # ======================================================

    def normalize_item(self, raw_item: Any) -> NewsArticle:
        """Convert one downloaded webpage into a NewsArticle."""

        if not isinstance(raw_item, Mapping):
            raise CollectorNormalizationError(
                "Webpage item must be a mapping."
            )

        soup = raw_item.get("soup")

        if not isinstance(soup, BeautifulSoup):
            raise CollectorNormalizationError(
                "Webpage item does not contain parsed HTML."
            )

        requested_url = normalize_url(
            self.source.url,
            raw_item.get("requested_url"),
        )
        resolved_url = normalize_url(
            requested_url or self.source.url,
            raw_item.get("resolved_url")
            or requested_url,
        )

        if not resolved_url:
            raise CollectorNormalizationError(
                "Webpage article URL is empty or invalid."
            )

        json_ld_article = self._extract_json_ld_article(soup)

        title = self._extract_title(
            soup,
            json_ld_article,
        )

        if not title:
            raise CollectorNormalizationError(
                "Unable to extract webpage article title."
            )

        canonical_url = self._extract_canonical_url(
            soup,
            json_ld_article,
            resolved_url,
        )

        description = self._extract_description(
            soup,
            json_ld_article,
        )
        author = self._extract_author(
            soup,
            json_ld_article,
        )
        publisher = self._extract_publisher(
            soup,
            json_ld_article,
        )
        published_at = self._extract_published_datetime(
            soup,
            json_ld_article,
        )
        image_url = self._extract_image_url(
            soup,
            json_ld_article,
            resolved_url,
        )
        raw_text = self._extract_article_body(
            soup,
            json_ld_article,
        )

        if not raw_text:
            raw_text = description

        keywords = self._extract_keywords(
            soup,
            json_ld_article,
        )
        tags = self._extract_tags(
            soup,
            json_ld_article,
        )

        metadata = {
            "collector": self.__class__.__name__,
            "requested_url": requested_url,
            "resolved_url": resolved_url,
            "http_status": raw_item.get("http_status"),
            "response_time_seconds": raw_item.get(
                "response_time_seconds"
            ),
            "content_type": raw_item.get("content_type", ""),
            "json_ld_type": sorted(
                json_ld_types(json_ld_article)
            ),
            "body_character_count": len(raw_text),
        }

        response_headers = raw_item.get("response_headers")

        if isinstance(response_headers, Mapping):
            metadata["etag"] = clean_web_text(
                response_headers.get("ETag")
            )
            metadata["last_modified"] = clean_web_text(
                response_headers.get("Last-Modified")
            )

        article = NewsArticle(
            title=title,
            url=resolved_url,
            canonical_url=canonical_url or resolved_url,
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

    # ======================================================
    # METADATA EXTRACTION
    # ======================================================

    def _extract_title(
        self,
        soup: BeautifulSoup,
        json_ld_article: Mapping[str, Any],
    ) -> str:
        """Extract the best article headline."""

        selector_value = self._selector_text(
            soup,
            "title_selector",
        )

        candidates = [
            selector_value,
            json_ld_article.get("headline"),
            json_ld_article.get("name"),
            self._meta_content(
                soup,
                property_name="og:title",
            ),
            self._meta_content(
                soup,
                name="twitter:title",
            ),
        ]

        for selector in TITLE_SELECTORS:
            candidate = soup.select_one(selector)

            if candidate is not None:
                candidates.append(candidate.get_text(" ", strip=True))

        if soup.title is not None:
            candidates.append(
                soup.title.get_text(" ", strip=True)
            )

        for candidate in candidates:
            cleaned = clean_web_text(candidate)

            if cleaned:
                return cleaned

        return ""

    def _extract_description(
        self,
        soup: BeautifulSoup,
        json_ld_article: Mapping[str, Any],
    ) -> str:
        """Extract the best article summary or description."""

        candidates = [
            self._selector_text(
                soup,
                "description_selector",
            ),
            json_ld_article.get("description"),
            self._meta_content(
                soup,
                property_name="og:description",
            ),
            self._meta_content(
                soup,
                name="twitter:description",
            ),
            self._meta_content(
                soup,
                name="description",
            ),
        ]

        for selector in DESCRIPTION_SELECTORS:
            element = soup.select_one(selector)

            if element is not None:
                candidates.append(
                    element.get_text(" ", strip=True)
                )

        for candidate in candidates:
            cleaned = clean_web_text(candidate)

            if cleaned:
                return cleaned

        return ""

    def _extract_author(
        self,
        soup: BeautifulSoup,
        json_ld_article: Mapping[str, Any],
    ) -> str:
        """Extract article author information."""

        candidates = [
            self._selector_text(
                soup,
                "author_selector",
            ),
            json_ld_person_name(
                json_ld_article.get("author")
            ),
            self._meta_content(
                soup,
                name="author",
            ),
            self._meta_content(
                soup,
                property_name="article:author",
            ),
        ]

        for selector in AUTHOR_SELECTORS:
            element = soup.select_one(selector)

            if element is None:
                continue

            if element.has_attr("content"):
                candidates.append(
                    element.get("content")
                )
            else:
                candidates.append(
                    element.get_text(" ", strip=True)
                )

        for candidate in candidates:
            cleaned = clean_web_text(candidate)

            if cleaned:
                cleaned = re.sub(
                    r"^\s*(by|written by|reported by)\s*:?\s*",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                )

                return cleaned.strip()

        return ""

    def _extract_publisher(
        self,
        soup: BeautifulSoup,
        json_ld_article: Mapping[str, Any],
    ) -> str:
        """Extract article publisher or site name."""

        publisher_value = json_ld_article.get("publisher")

        candidates = [
            self._selector_text(
                soup,
                "publisher_selector",
            ),
            json_ld_person_name(publisher_value),
            self._meta_content(
                soup,
                property_name="og:site_name",
            ),
            self._meta_content(
                soup,
                name="application-name",
            ),
            self.source.publisher,
            self.source.name,
        ]

        for candidate in candidates:
            cleaned = clean_web_text(candidate)

            if cleaned:
                return cleaned

        return ""

    def _extract_published_datetime(
        self,
        soup: BeautifulSoup,
        json_ld_article: Mapping[str, Any],
    ) -> datetime | None:
        """Extract the article publication datetime."""

        configured_selector = self._metadata_text(
            "date_selector"
        )

        candidates: list[Any] = []

        if configured_selector:
            selected = soup.select_one(configured_selector)

            if selected is not None:
                candidates.extend(
                    [
                        selected.get("datetime"),
                        selected.get("content"),
                        selected.get_text(" ", strip=True),
                    ]
                )

        candidates.extend(
            [
                json_ld_article.get("datePublished"),
                json_ld_article.get("dateCreated"),
                json_ld_article.get("dateModified"),
                self._meta_content(
                    soup,
                    property_name="article:published_time",
                ),
                self._meta_content(
                    soup,
                    property_name="article:modified_time",
                ),
                self._meta_content(
                    soup,
                    name="pubdate",
                ),
                self._meta_content(
                    soup,
                    name="publish-date",
                ),
                self._meta_content(
                    soup,
                    name="date",
                ),
                self._meta_content(
                    soup,
                    itemprop="datePublished",
                ),
            ]
        )

        for selector in DATE_SELECTORS:
            element = soup.select_one(selector)

            if element is None:
                continue

            candidates.extend(
                [
                    element.get("datetime"),
                    element.get("content"),
                    element.get_text(" ", strip=True),
                ]
            )

        for candidate in candidates:
            parsed = parse_web_datetime(candidate)

            if parsed is not None:
                return parsed

        return None

    def _extract_image_url(
        self,
        soup: BeautifulSoup,
        json_ld_article: Mapping[str, Any],
        base_url: str,
    ) -> str:
        """Extract the best representative article image URL."""

        configured_selector = self._metadata_text(
            "image_selector"
        )

        candidates: list[Any] = []

        if configured_selector:
            selected = soup.select_one(configured_selector)

            if selected is not None:
                candidates.extend(
                    self._image_element_candidates(selected)
                )

        candidates.extend(
            [
                json_ld_image_url(
                    json_ld_article.get("image")
                ),
                json_ld_image_url(
                    json_ld_article.get("thumbnailUrl")
                ),
                self._meta_content(
                    soup,
                    property_name="og:image",
                ),
                self._meta_content(
                    soup,
                    property_name="og:image:url",
                ),
                self._meta_content(
                    soup,
                    property_name="og:image:secure_url",
                ),
                self._meta_content(
                    soup,
                    name="twitter:image",
                ),
                self._meta_content(
                    soup,
                    name="twitter:image:src",
                ),
            ]
        )

        for selector in IMAGE_SELECTORS:
            element = soup.select_one(selector)

            if element is not None:
                candidates.extend(
                    self._image_element_candidates(element)
                )

        for candidate in candidates:
            image_url = normalize_url(
                base_url,
                candidate,
            )

            if image_url:
                return image_url

        return ""

    def _extract_canonical_url(
        self,
        soup: BeautifulSoup,
        json_ld_article: Mapping[str, Any],
        resolved_url: str,
    ) -> str:
        """Extract and normalize the preferred canonical article URL."""

        configured_selector = self._metadata_text(
            "canonical_selector"
        )

        candidates: list[Any] = []

        if configured_selector:
            selected = soup.select_one(configured_selector)

            if selected is not None:
                candidates.extend(
                    [
                        selected.get("href"),
                        selected.get("content"),
                        selected.get_text(" ", strip=True),
                    ]
                )

        main_entity = json_ld_article.get("mainEntityOfPage")

        if isinstance(main_entity, Mapping):
            main_entity = (
                main_entity.get("@id")
                or main_entity.get("url")
            )

        candidates.extend(
            [
                json_ld_article.get("url"),
                main_entity,
                self._link_href(
                    soup,
                    rel="canonical",
                ),
                self._meta_content(
                    soup,
                    property_name="og:url",
                ),
                resolved_url,
            ]
        )

        for candidate in candidates:
            canonical_url = normalize_url(
                resolved_url,
                candidate,
            )

            if canonical_url:
                return canonical_url

        return resolved_url

    def _extract_keywords(
        self,
        soup: BeautifulSoup,
        json_ld_article: Mapping[str, Any],
    ) -> list[str]:
        """Extract article keywords."""

        values: list[Any] = [
            json_ld_article.get("keywords"),
            self._meta_content(
                soup,
                name="keywords",
            ),
            self._meta_content(
                soup,
                name="news_keywords",
            ),
        ]

        results: list[str] = []

        for value in values:
            results.extend(
                normalize_keyword_list(value)
            )

        return unique_strings(results)

    def _extract_tags(
        self,
        soup: BeautifulSoup,
        json_ld_article: Mapping[str, Any],
    ) -> list[str]:
        """Extract article sections and tag labels."""

        values: list[Any] = [
            json_ld_article.get("articleSection"),
            self._meta_content(
                soup,
                property_name="article:section",
            ),
        ]

        for element in soup.select(
            "[rel='tag'], .article-tags a, .story-tags a, "
            ".post-tags a, [class*='tag-list'] a"
        ):
            values.append(
                element.get_text(" ", strip=True)
            )

        results: list[str] = []

        for value in values:
            results.extend(
                normalize_keyword_list(value)
            )

        return unique_strings(results)

    # ======================================================
    # ARTICLE BODY EXTRACTION
    # ======================================================

    def _extract_article_body(
        self,
        soup: BeautifulSoup,
        json_ld_article: Mapping[str, Any],
    ) -> str:
        """Extract cleaned article-body text."""

        json_ld_body = clean_web_text(
            json_ld_article.get("articleBody")
        )

        working_soup = BeautifulSoup(
            str(soup),
            "html.parser",
        )

        self._remove_noise(working_soup)

        configured_selector = self._metadata_text(
            "article_body_selector"
        )

        body_candidates: list[str] = []

        if configured_selector:
            selected_elements = working_soup.select(
                configured_selector
            )

            for element in selected_elements:
                candidate = self._extract_paragraph_text(
                    element
                )

                if candidate:
                    body_candidates.append(candidate)

        for selector in ARTICLE_BODY_SELECTORS:
            for element in working_soup.select(selector):
                candidate = self._extract_paragraph_text(
                    element
                )

                if candidate:
                    body_candidates.append(candidate)

        if json_ld_body:
            body_candidates.append(json_ld_body)

        if not body_candidates:
            fallback_container = (
                working_soup.body
                or working_soup
            )

            fallback_text = self._extract_paragraph_text(
                fallback_container
            )

            if fallback_text:
                body_candidates.append(fallback_text)

        if not body_candidates:
            return ""

        best_body = max(
            body_candidates,
            key=self._body_quality_score,
        )

        best_body = clean_web_text(best_body)

        if len(best_body) > self._maximum_body_characters:
            best_body = best_body[
                :self._maximum_body_characters
            ].rstrip()

        return best_body

    def _extract_paragraph_text(
        self,
        container: Tag | BeautifulSoup,
    ) -> str:
        """Extract readable text from paragraph-like descendants."""

        paragraphs = container.select(
            "p, h2, h3, blockquote, li"
        )

        paragraph_texts: list[str] = []

        for paragraph in paragraphs:
            text = clean_web_text(
                paragraph.get_text(" ", strip=True)
            )

            if not text:
                continue

            if len(text) < 20:
                continue

            if self._looks_like_noise_text(text):
                continue

            paragraph_texts.append(text)

        paragraph_texts = unique_strings(
            paragraph_texts
        )

        if paragraph_texts:
            return "\n\n".join(paragraph_texts)

        direct_text = clean_web_text(
            container.get_text(" ", strip=True)
        )

        if self._looks_like_noise_text(direct_text):
            return ""

        return direct_text

    def _remove_noise(
        self,
        soup: BeautifulSoup,
    ) -> None:
        """Remove scripts, navigation, advertising, and other noise."""

        selectors = list(NOISE_SELECTORS)

        additional_selectors = self.source.metadata.get(
            "remove_selectors"
        ) or []

        if isinstance(additional_selectors, str):
            additional_selectors = [
                additional_selectors
            ]

        if isinstance(additional_selectors, Iterable):
            selectors.extend(
                clean_web_text(item)
                for item in additional_selectors
                if clean_web_text(item)
            )

        for selector in selectors:
            try:
                for element in soup.select(selector):
                    element.decompose()
            except Exception:
                LOGGER.debug(
                    "Unable to apply removal selector | selector=%s",
                    selector,
                )

    def _body_quality_score(
        self,
        text: str,
    ) -> tuple[int, int, int]:
        """
        Score a body candidate.

        Preference is given to text meeting the configured minimum length,
        containing more paragraph boundaries, and containing more text.
        """

        cleaned = clean_web_text(text)
        reaches_minimum = int(
            len(cleaned)
            >= self._minimum_body_characters
        )
        paragraph_count = text.count("\n\n") + 1

        return (
            reaches_minimum,
            paragraph_count,
            len(cleaned),
        )

    @staticmethod
    def _looks_like_noise_text(text: str) -> bool:
        """Return whether text resembles common webpage boilerplate."""

        cleaned = clean_web_text(text)

        if not cleaned:
            return True

        lowered = cleaned.casefold()

        exact_noise = {
            "advertisement",
            "advertisement - scroll to continue",
            "read more",
            "also read",
            "recommended",
            "related stories",
            "sign up",
            "subscribe",
            "share",
            "comments",
        }

        if lowered in exact_noise:
            return True

        if lowered.startswith(
            (
                "cookie policy",
                "accept cookies",
                "subscribe to",
                "sign up for",
                "follow us on",
            )
        ):
            return True

        return False

    # ======================================================
    # JSON-LD EXTRACTION
    # ======================================================

    def _extract_json_ld_article(
        self,
        soup: BeautifulSoup,
    ) -> Mapping[str, Any]:
        """Return the best Schema.org article object found in the page."""

        article_nodes: list[Mapping[str, Any]] = []

        for script in soup.find_all(
            "script",
            attrs={"type": "application/ld+json"},
        ):
            script_text = script.string or script.get_text()

            if not script_text:
                continue

            parsed_values = self._parse_json_ld_text(
                script_text
            )

            for parsed_value in parsed_values:
                for node in iter_json_ld_nodes(
                    parsed_value
                ):
                    node_types = json_ld_types(node)

                    if (
                        node_types
                        & JSON_LD_ARTICLE_TYPES
                    ):
                        article_nodes.append(node)

        if not article_nodes:
            return {}

        return max(
            article_nodes,
            key=self._json_ld_article_score,
        )

    @staticmethod
    def _parse_json_ld_text(
        script_text: str,
    ) -> list[Any]:
        """Parse a JSON-LD script with conservative cleanup."""

        cleaned = script_text.strip()

        if not cleaned:
            return []

        cleaned = re.sub(
            r"^\s*<!--",
            "",
            cleaned,
        )
        cleaned = re.sub(
            r"-->\s*$",
            "",
            cleaned,
        )
        cleaned = cleaned.rstrip(";").strip()

        try:
            return [json.loads(cleaned)]
        except json.JSONDecodeError:
            pass

        results: list[Any] = []

        decoder = json.JSONDecoder()
        index = 0

        while index < len(cleaned):
            while (
                index < len(cleaned)
                and cleaned[index].isspace()
            ):
                index += 1

            if index >= len(cleaned):
                break

            try:
                value, next_index = decoder.raw_decode(
                    cleaned,
                    index,
                )
            except json.JSONDecodeError:
                break

            results.append(value)
            index = next_index

        return results

    @staticmethod
    def _json_ld_article_score(
        node: Mapping[str, Any],
    ) -> tuple[int, int]:
        """Score a JSON-LD article object by useful field coverage."""

        useful_fields = (
            "headline",
            "description",
            "articleBody",
            "datePublished",
            "author",
            "publisher",
            "image",
            "url",
            "mainEntityOfPage",
        )

        field_count = sum(
            1
            for field_name in useful_fields
            if node.get(field_name)
        )

        body_length = len(
            clean_web_text(
                node.get("articleBody")
            )
        )

        return field_count, body_length

    # ======================================================
    # HTML HELPERS
    # ======================================================

    @staticmethod
    def _meta_content(
        soup: BeautifulSoup,
        *,
        name: str | None = None,
        property_name: str | None = None,
        itemprop: str | None = None,
    ) -> str:
        """Read the content value of a meta element."""

        attributes: dict[str, str] = {}

        if name:
            attributes["name"] = name

        if property_name:
            attributes["property"] = property_name

        if itemprop:
            attributes["itemprop"] = itemprop

        if not attributes:
            return ""

        element = soup.find(
            "meta",
            attrs=attributes,
        )

        if element is None:
            return ""

        return clean_web_text(
            element.get("content")
        )

    @staticmethod
    def _link_href(
        soup: BeautifulSoup,
        *,
        rel: str,
    ) -> str:
        """Read an href from a link element with a rel value."""

        element = soup.find(
            "link",
            rel=lambda value: (
                value
                and rel.casefold()
                in {
                    clean_web_text(item).casefold()
                    for item in (
                        value
                        if isinstance(value, list)
                        else [value]
                    )
                }
            ),
        )

        if element is None:
            return ""

        return clean_web_text(
            element.get("href")
        )

    def _selector_text(
        self,
        soup: BeautifulSoup,
        metadata_name: str,
    ) -> str:
        """Extract text using a configured CSS selector."""

        selector = self._metadata_text(
            metadata_name
        )

        if not selector:
            return ""

        try:
            element = soup.select_one(selector)
        except Exception as error:
            raise CollectorNormalizationError(
                f"Invalid CSS selector in metadata "
                f"'{metadata_name}': {selector}"
            ) from error

        if element is None:
            return ""

        return clean_web_text(
            element.get("content")
            or element.get_text(" ", strip=True)
        )

    @staticmethod
    def _image_element_candidates(
        element: Tag,
    ) -> list[str]:
        """Return possible image URLs from an HTML element."""

        candidates = [
            element.get("src"),
            element.get("data-src"),
            element.get("data-lazy-src"),
            element.get("data-original"),
            element.get("content"),
            element.get("href"),
        ]

        srcset = clean_web_text(
            element.get("srcset")
            or element.get("data-srcset")
        )

        if srcset:
            srcset_candidates = []

            for part in srcset.split(","):
                candidate = clean_web_text(
                    part.split()[0]
                )

                if candidate:
                    srcset_candidates.append(candidate)

            if srcset_candidates:
                candidates.append(
                    srcset_candidates[-1]
                )

        return [
            clean_web_text(candidate)
            for candidate in candidates
            if clean_web_text(candidate)
        ]

    # ======================================================
    # CONFIGURATION HELPERS
    # ======================================================

    def _configured_article_urls(self) -> list[str]:
        """Return validated article URLs configured for this source."""

        raw_urls = self.source.metadata.get(
            "article_urls"
        )

        if raw_urls is None:
            raw_urls = [self.source.url]

        elif isinstance(raw_urls, str):
            raw_urls = [raw_urls]

        elif not isinstance(raw_urls, Iterable):
            raise CollectorFetchError(
                "Web metadata article_urls must be a list or string."
            )

        normalized_urls = unique_strings(
            normalize_url(
                self.source.url,
                item,
            )
            for item in raw_urls
        )

        if not normalized_urls:
            raise CollectorFetchError(
                "No valid HTTP or HTTPS article URLs were configured."
            )

        return normalized_urls

    def _metadata_text(
        self,
        metadata_name: str,
    ) -> str:
        """Return a normalized string from source metadata."""

        return clean_web_text(
            self.source.metadata.get(metadata_name)
        )

    def _positive_integer_metadata(
        self,
        metadata_name: str,
        *,
        default: int,
    ) -> int:
        """Read and validate a positive integer metadata value."""

        raw_value = self.source.metadata.get(
            metadata_name,
            default,
        )

        try:
            value = int(raw_value)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"{metadata_name} must be an integer."
            ) from error

        if value <= 0:
            raise ValueError(
                f"{metadata_name} must be greater than zero."
            )

        return value

    # ======================================================
    # HEALTH CHECK
    # ======================================================

    def health_check(self) -> SourceHealth:
        """
        Check whether the configured webpage source is reachable.

        GET is used instead of HEAD because many news websites block or
        incorrectly implement HEAD requests.
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
                    "Web HTTP session is unavailable."
                )

            response = self._session.get(
                self.source.url,
                timeout=self.source.request_timeout_seconds,
                allow_redirects=True,
                verify=self._verify_ssl,
                stream=True,
            )

            response_time = (
                time.perf_counter() - started_at
            )
            status_code = response.status_code
            content_type = response.headers.get(
                "Content-Type",
                "",
            )

            response.raise_for_status()

            return SourceHealth(
                source_id=self.source.source_id,
                source_name=self.source.name,
                status=self.source.status,
                healthy=True,
                message=(
                    f"Web source returned HTTP {status_code}."
                ),
                response_time_seconds=response_time,
                metadata={
                    "http_status": status_code,
                    "resolved_url": response.url,
                    "content_type": content_type,
                },
            )

        except Exception as error:
            response_time = (
                time.perf_counter() - started_at
            )
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
    Run deterministic, network-free webpage extraction tests.

    No external website or internet connection is required.
    """

    from news.models import (
        NewsCategory,
        NewsSource,
    )

    sample_source = NewsSource(
        name="Bahuvu Web Test",
        source_type=SourceType.WEBSITE,
        url="https://example.com/news/test-story",
        publisher="Bahuvu Test Publisher",
        default_category=NewsCategory.NATIONAL,
        language=LanguageCode.ENGLISH,
        reliability_score=85.0,
        metadata={
            "minimum_body_characters": 100,
            "maximum_body_characters": 5000,
        },
    )

    sample_html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <title>Fallback Page Title</title>

        <link
            rel="canonical"
            href="/news/canonical-test-story"
        >

        <meta
            property="og:title"
            content="Bahuvu Web Collector Test Headline"
        >
        <meta
            property="og:description"
            content="A verified summary for the web collector test."
        >
        <meta
            property="og:image"
            content="/images/test-story.jpg"
        >
        <meta
            property="og:site_name"
            content="Bahuvu Test Publisher"
        >
        <meta
            property="article:published_time"
            content="2026-07-11T08:30:00+05:30"
        >
        <meta
            name="keywords"
            content="India, National, Testing"
        >

        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "NewsArticle",
            "headline": "Bahuvu Web Collector Test Headline",
            "description": "A verified summary for the web collector test.",
            "datePublished": "2026-07-11T08:30:00+05:30",
            "author": {
                "@type": "Person",
                "name": "Test Reporter"
            },
            "publisher": {
                "@type": "Organization",
                "name": "Bahuvu Test Publisher"
            },
            "image": {
                "@type": "ImageObject",
                "url": "/images/test-story.jpg"
            },
            "articleSection": [
                "National",
                "Technology"
            ],
            "keywords": [
                "India",
                "Testing"
            ],
            "mainEntityOfPage": {
                "@type": "WebPage",
                "@id": "/news/canonical-test-story"
            }
        }
        </script>
    </head>

    <body>
        <nav>
            Navigation content that must not become article text.
        </nav>

        <main>
            <article>
                <h1>Bahuvu Web Collector Test Headline</h1>

                <p>
                    This is the first substantial paragraph of the sample
                    article. It verifies that the collector can identify
                    and preserve meaningful news content.
                </p>

                <p>
                    This is the second substantial paragraph. It confirms
                    that multiple paragraphs are combined into the final
                    canonical raw article text.
                </p>

                <div class="advertisement">
                    Advertisement
                </div>
            </article>
        </main>

        <footer>
            Footer content that must be removed.
        </footer>
    </body>
    </html>
    """

    collector = WebCollector(sample_source)

    sample_soup = BeautifulSoup(
        sample_html,
        "html.parser",
    )

    sample_item = {
        "requested_url": sample_source.url,
        "resolved_url": sample_source.url,
        "http_status": 200,
        "response_time_seconds": 0.05,
        "content_type": "text/html; charset=utf-8",
        "html": sample_html,
        "soup": sample_soup,
        "response_headers": {
            "ETag": '"test-etag"',
            "Last-Modified": (
                "Sat, 11 Jul 2026 03:00:00 GMT"
            ),
        },
    }

    assert collector.validate_item(sample_item) is True

    article = collector.normalize_item(sample_item)

    assert article.title == (
        "Bahuvu Web Collector Test Headline"
    )
    assert article.url == (
        "https://example.com/news/test-story"
    )
    assert article.canonical_url == (
        "https://example.com/news/canonical-test-story"
    )
    assert article.source_id == sample_source.source_id
    assert article.source_name == sample_source.name
    assert article.publisher == (
        "Bahuvu Test Publisher"
    )
    assert article.author == "Test Reporter"
    assert article.description == (
        "A verified summary for the web collector test."
    )
    assert article.image_url == (
        "https://example.com/images/test-story.jpg"
    )
    assert "first substantial paragraph" in article.raw_text
    assert "second substantial paragraph" in article.raw_text
    assert "Navigation content" not in article.raw_text
    assert "Footer content" not in article.raw_text
    assert "Advertisement" not in article.raw_text
    assert article.reliability_score == 85.0
    assert article.category == NewsCategory.NATIONAL
    assert article.language == LanguageCode.ENGLISH
    assert article.published_at is not None
    assert article.published_at.tzinfo is not None
    assert "India" in article.keywords
    assert "Testing" in article.keywords
    assert "National" in article.tags
    assert "Technology" in article.tags
    assert article.metadata["http_status"] == 200
    assert article.metadata["collector"] == "WebCollector"

    collector.close()

    print("Web collector initialized successfully.")
    print(f"Article title: {article.title}")
    print(f"Article source: {article.source_name}")
    print(f"Article author: {article.author}")
    print(f"Article publisher: {article.publisher}")
    print(f"Canonical URL: {article.canonical_url}")
    print(f"Image URL: {article.image_url}")
    print(
        "Published at: "
        f"{article.published_at.isoformat()}"
    )
    print(
        "Body characters: "
        f"{len(article.raw_text)}"
    )
    print(
        "Keywords: "
        f"{', '.join(article.keywords)}"
    )
    print(
        "Tags: "
        f"{', '.join(article.tags)}"
    )
    print("Web collector self-test passed.")


if __name__ == "__main__":
    _run_self_test()
