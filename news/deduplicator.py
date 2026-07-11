# news/deduplicator.py

"""
BahuvuNewsAI - News Article Deduplicator
Version: 1.0.0

This module detects duplicate and near-duplicate news articles after the
collection stage.

Detection methods:

- Identical canonical URLs
- Identical normalized article URLs
- Identical normalized headlines
- Identical content fingerprints
- Highly similar headlines
- Highly similar article bodies
- Syndicated stories published by different sources
- Duplicate clusters containing more than two related articles

For every duplicate cluster, the strongest article is retained as the
primary article. Other members are marked with:

    ArticleStatus.DUPLICATE
    duplicate_of=<primary article ID>

The primary article is selected using deterministic quality signals such
as source reliability, article completeness, text length, image presence,
publication date, and editorial scores.

The module contains no network calls and includes a deterministic self-test.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import hashlib
import logging
import re
import unicodedata
from typing import Any, Iterable, Mapping
from urllib.parse import (
    parse_qsl,
    urlencode,
    urlparse,
    urlunparse,
)

from news.models import (
    ArticleStatus,
    NewsArticle,
)


LOGGER = logging.getLogger("BahuvuNewsAI.news.deduplicator")


# ==========================================================
# CONSTANTS
# ==========================================================

_WHITESPACE_PATTERN = re.compile(r"\s+")
_NON_WORD_PATTERN = re.compile(r"[^\w\s]", flags=re.UNICODE)
_TOKEN_PATTERN = re.compile(r"\w+", flags=re.UNICODE)

DEFAULT_TRACKING_PARAMETERS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "utm_name",
        "gclid",
        "fbclid",
        "dclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "ref",
        "source",
        "campaign",
        "campaignid",
        "igshid",
    }
)

DEFAULT_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "but",
        "by",
        "for",
        "from",
        "had",
        "has",
        "have",
        "he",
        "her",
        "his",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "she",
        "that",
        "the",
        "their",
        "they",
        "this",
        "to",
        "was",
        "were",
        "will",
        "with",
    }
)


# ==========================================================
# TIME HELPERS
# ==========================================================

def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""

    return datetime.now(timezone.utc)


def ensure_utc(value: datetime | None) -> datetime | None:
    """Normalize an optional datetime to timezone-aware UTC."""

    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


# ==========================================================
# TEXT AND URL NORMALIZATION
# ==========================================================

def normalize_text(value: Any) -> str:
    """
    Normalize text for duplicate comparison.

    Unicode is normalized, text is case-folded, punctuation is removed,
    and repeated whitespace is collapsed.
    """

    if value is None:
        return ""

    text = unicodedata.normalize(
        "NFKC",
        str(value),
    )
    text = text.casefold()
    text = text.replace("\u200b", "")
    text = text.replace("\u200c", "")
    text = text.replace("\u200d", "")
    text = text.replace("\ufeff", "")
    text = _NON_WORD_PATTERN.sub(" ", text)
    text = _WHITESPACE_PATTERN.sub(" ", text)

    return text.strip()


def normalize_url(
    value: str,
    *,
    ignored_query_parameters: Iterable[str] = (
        DEFAULT_TRACKING_PARAMETERS
    ),
    remove_query_string: bool = False,
) -> str:
    """
    Normalize an HTTP or HTTPS URL for duplicate comparison.

    Normalization includes:

    - Lowercasing scheme and host
    - Removing fragments
    - Removing default ports
    - Removing common tracking parameters
    - Sorting remaining query parameters
    - Removing unnecessary trailing slashes
    """

    raw_url = str(value or "").strip()

    if not raw_url:
        return ""

    try:
        parsed = urlparse(raw_url)
    except (TypeError, ValueError):
        return ""

    scheme = parsed.scheme.casefold()

    if scheme not in {"http", "https"}:
        return ""

    hostname = (
        parsed.hostname.casefold()
        if parsed.hostname
        else ""
    )

    if not hostname:
        return ""

    port = parsed.port

    if (
        port is None
        or scheme == "http"
        and port == 80
        or scheme == "https"
        and port == 443
    ):
        netloc = hostname
    else:
        netloc = f"{hostname}:{port}"

    path = re.sub(
        r"/{2,}",
        "/",
        parsed.path or "/",
    )

    if path != "/":
        path = path.rstrip("/")

    ignored_parameters = {
        str(parameter).casefold()
        for parameter in ignored_query_parameters
    }

    if remove_query_string:
        query = ""
    else:
        query_items = []

        for key, item_value in parse_qsl(
            parsed.query,
            keep_blank_values=True,
        ):
            if key.casefold() in ignored_parameters:
                continue

            query_items.append((key, item_value))

        query_items.sort(
            key=lambda item: (
                item[0].casefold(),
                item[1],
            )
        )
        query = urlencode(
            query_items,
            doseq=True,
        )

    normalized = urlunparse(
        (
            scheme,
            netloc,
            path,
            "",
            query,
            "",
        )
    )

    return normalized


def normalized_article_url(
    article: NewsArticle,
    *,
    ignored_query_parameters: Iterable[str] = (
        DEFAULT_TRACKING_PARAMETERS
    ),
) -> str:
    """Return the best normalized URL for an article."""

    preferred_url = (
        article.canonical_url
        or article.url
    )

    return normalize_url(
        preferred_url,
        ignored_query_parameters=(
            ignored_query_parameters
        ),
    )


def tokenize(
    value: str,
    *,
    stop_words: Iterable[str] = DEFAULT_STOP_WORDS,
) -> set[str]:
    """Return meaningful normalized tokens for similarity comparison."""

    normalized = normalize_text(value)

    if not normalized:
        return set()

    ignored_words = {
        normalize_text(word)
        for word in stop_words
    }

    return {
        token
        for token in _TOKEN_PATTERN.findall(normalized)
        if len(token) > 1
        and token not in ignored_words
    }


def stable_hash(value: str) -> str:
    """Return a deterministic SHA-256 fingerprint."""

    normalized = normalize_text(value)

    if not normalized:
        return ""

    return hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()


def article_content_fingerprint(
    article: NewsArticle,
) -> str:
    """
    Return a stable fingerprint of the best available article content.

    The article body is preferred. The description is used when no body
    is available.
    """

    content = (
        article.cleaned_text
        or article.raw_text
        or article.description
    )

    return stable_hash(content)


# ==========================================================
# SIMILARITY HELPERS
# ==========================================================

def sequence_similarity(
    left: str,
    right: str,
) -> float:
    """Return normalized character-sequence similarity from 0 to 1."""

    normalized_left = normalize_text(left)
    normalized_right = normalize_text(right)

    if not normalized_left or not normalized_right:
        return 0.0

    if normalized_left == normalized_right:
        return 1.0

    return SequenceMatcher(
        None,
        normalized_left,
        normalized_right,
        autojunk=False,
    ).ratio()


def jaccard_similarity(
    left_tokens: set[str],
    right_tokens: set[str],
) -> float:
    """Return token-set Jaccard similarity from 0 to 1."""

    if not left_tokens or not right_tokens:
        return 0.0

    intersection = left_tokens & right_tokens
    union = left_tokens | right_tokens

    if not union:
        return 0.0

    return len(intersection) / len(union)


def combined_text_similarity(
    left: str,
    right: str,
    *,
    stop_words: Iterable[str] = DEFAULT_STOP_WORDS,
) -> float:
    """
    Combine token overlap and character sequence similarity.

    Token overlap carries more weight because syndicated stories often
    contain minor punctuation, formatting, or word-order differences.
    """

    token_score = jaccard_similarity(
        tokenize(
            left,
            stop_words=stop_words,
        ),
        tokenize(
            right,
            stop_words=stop_words,
        ),
    )
    sequence_score = sequence_similarity(
        left,
        right,
    )

    return (
        token_score * 0.65
        + sequence_score * 0.35
    )


# ==========================================================
# CONFIGURATION
# ==========================================================

@dataclass(slots=True)
class DeduplicatorConfig:
    """Runtime configuration for article deduplication."""

    title_similarity_threshold: float = 0.88
    content_similarity_threshold: float = 0.90
    combined_similarity_threshold: float = 0.86

    title_weight: float = 0.60
    content_weight: float = 0.40

    minimum_title_characters: int = 20
    minimum_content_characters: int = 120
    maximum_content_characters: int = 15_000

    publication_window_hours: float = 168.0
    require_publication_window: bool = False

    compare_within_category_only: bool = False
    compare_within_language_only: bool = True

    remove_url_query_string: bool = False
    ignored_query_parameters: frozenset[str] = field(
        default_factory=lambda: DEFAULT_TRACKING_PARAMETERS
    )
    stop_words: frozenset[str] = field(
        default_factory=lambda: DEFAULT_STOP_WORDS
    )

    mark_duplicate_status: bool = True
    preserve_existing_terminal_statuses: bool = True

    def __post_init__(self) -> None:
        self.title_similarity_threshold = float(
            self.title_similarity_threshold
        )
        self.content_similarity_threshold = float(
            self.content_similarity_threshold
        )
        self.combined_similarity_threshold = float(
            self.combined_similarity_threshold
        )
        self.title_weight = float(
            self.title_weight
        )
        self.content_weight = float(
            self.content_weight
        )

        self.minimum_title_characters = int(
            self.minimum_title_characters
        )
        self.minimum_content_characters = int(
            self.minimum_content_characters
        )
        self.maximum_content_characters = int(
            self.maximum_content_characters
        )
        self.publication_window_hours = float(
            self.publication_window_hours
        )

        thresholds = {
            "title_similarity_threshold": (
                self.title_similarity_threshold
            ),
            "content_similarity_threshold": (
                self.content_similarity_threshold
            ),
            "combined_similarity_threshold": (
                self.combined_similarity_threshold
            ),
        }

        for name, threshold in thresholds.items():
            if not 0.0 <= threshold <= 1.0:
                raise ValueError(
                    f"{name} must be between 0 and 1."
                )

        if self.title_weight < 0:
            raise ValueError(
                "title_weight cannot be negative."
            )

        if self.content_weight < 0:
            raise ValueError(
                "content_weight cannot be negative."
            )

        if (
            self.title_weight
            + self.content_weight
            <= 0
        ):
            raise ValueError(
                "At least one similarity weight must be positive."
            )

        if self.minimum_title_characters < 1:
            raise ValueError(
                "minimum_title_characters must be at least 1."
            )

        if self.minimum_content_characters < 1:
            raise ValueError(
                "minimum_content_characters must be at least 1."
            )

        if (
            self.maximum_content_characters
            < self.minimum_content_characters
        ):
            raise ValueError(
                "maximum_content_characters cannot be smaller than "
                "minimum_content_characters."
            )

        if self.publication_window_hours < 0:
            raise ValueError(
                "publication_window_hours cannot be negative."
            )

        self.ignored_query_parameters = frozenset(
            str(parameter).casefold()
            for parameter
            in self.ignored_query_parameters
            if str(parameter).strip()
        )
        self.stop_words = frozenset(
            normalize_text(word)
            for word in self.stop_words
            if normalize_text(word)
        )

    @property
    def normalized_title_weight(self) -> float:
        """Return title weight normalized against total weight."""

        total = (
            self.title_weight
            + self.content_weight
        )

        return self.title_weight / total

    @property
    def normalized_content_weight(self) -> float:
        """Return content weight normalized against total weight."""

        total = (
            self.title_weight
            + self.content_weight
        )

        return self.content_weight / total

    def to_dict(self) -> dict[str, Any]:
        """Serialize configuration into JSON-compatible data."""

        return {
            "title_similarity_threshold": (
                self.title_similarity_threshold
            ),
            "content_similarity_threshold": (
                self.content_similarity_threshold
            ),
            "combined_similarity_threshold": (
                self.combined_similarity_threshold
            ),
            "title_weight": self.title_weight,
            "content_weight": self.content_weight,
            "minimum_title_characters": (
                self.minimum_title_characters
            ),
            "minimum_content_characters": (
                self.minimum_content_characters
            ),
            "maximum_content_characters": (
                self.maximum_content_characters
            ),
            "publication_window_hours": (
                self.publication_window_hours
            ),
            "require_publication_window": (
                self.require_publication_window
            ),
            "compare_within_category_only": (
                self.compare_within_category_only
            ),
            "compare_within_language_only": (
                self.compare_within_language_only
            ),
            "remove_url_query_string": (
                self.remove_url_query_string
            ),
            "mark_duplicate_status": (
                self.mark_duplicate_status
            ),
            "preserve_existing_terminal_statuses": (
                self.preserve_existing_terminal_statuses
            ),
        }


# ==========================================================
# COMPARISON RECORDS
# ==========================================================

@dataclass(slots=True)
class DuplicateComparison:
    """Detailed comparison between two articles."""

    left_article_id: str
    right_article_id: str

    duplicate: bool
    reason: str = ""

    url_match: bool = False
    title_exact_match: bool = False
    content_exact_match: bool = False

    title_similarity: float = 0.0
    content_similarity: float = 0.0
    combined_similarity: float = 0.0

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize this comparison."""

        return {
            "left_article_id": self.left_article_id,
            "right_article_id": self.right_article_id,
            "duplicate": self.duplicate,
            "reason": self.reason,
            "url_match": self.url_match,
            "title_exact_match": self.title_exact_match,
            "content_exact_match": self.content_exact_match,
            "title_similarity": self.title_similarity,
            "content_similarity": self.content_similarity,
            "combined_similarity": self.combined_similarity,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class DuplicateCluster:
    """One group of equivalent or highly similar articles."""

    cluster_id: str
    primary_article_id: str
    article_ids: list[str]
    reasons: list[str] = field(default_factory=list)

    @property
    def duplicate_article_ids(self) -> list[str]:
        """Return every cluster member except the primary article."""

        return [
            article_id
            for article_id in self.article_ids
            if article_id != self.primary_article_id
        ]

    @property
    def article_count(self) -> int:
        """Return cluster size."""

        return len(self.article_ids)

    @property
    def duplicate_count(self) -> int:
        """Return duplicate member count."""

        return len(self.duplicate_article_ids)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the duplicate cluster."""

        return {
            "cluster_id": self.cluster_id,
            "primary_article_id": self.primary_article_id,
            "article_ids": list(self.article_ids),
            "duplicate_article_ids": (
                self.duplicate_article_ids
            ),
            "article_count": self.article_count,
            "duplicate_count": self.duplicate_count,
            "reasons": list(self.reasons),
        }


@dataclass(slots=True)
class DeduplicationResult:
    """Complete result of one deduplication run."""

    articles: list[NewsArticle]
    clusters: list[DuplicateCluster]
    comparisons: list[DuplicateComparison]

    started_at: datetime = field(
        default_factory=utc_now
    )
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        self.articles = list(self.articles or [])
        self.clusters = list(self.clusters or [])
        self.comparisons = list(
            self.comparisons or []
        )
        self.started_at = (
            ensure_utc(self.started_at)
            or utc_now()
        )
        self.completed_at = ensure_utc(
            self.completed_at
        )
        self.metadata = dict(self.metadata or {})

    @property
    def total_articles(self) -> int:
        """Return all input articles."""

        return len(self.articles)

    @property
    def duplicate_articles(self) -> list[NewsArticle]:
        """Return articles marked as duplicates."""

        return [
            article
            for article in self.articles
            if article.status
            == ArticleStatus.DUPLICATE
        ]

    @property
    def unique_articles(self) -> list[NewsArticle]:
        """Return articles not marked as duplicates."""

        return [
            article
            for article in self.articles
            if article.status
            != ArticleStatus.DUPLICATE
        ]

    @property
    def duplicate_count(self) -> int:
        """Return duplicate article count."""

        return len(self.duplicate_articles)

    @property
    def unique_count(self) -> int:
        """Return unique article count."""

        return len(self.unique_articles)

    @property
    def cluster_count(self) -> int:
        """Return duplicate cluster count."""

        return len(self.clusters)

    @property
    def comparison_count(self) -> int:
        """Return pair comparison count."""

        return len(self.comparisons)

    @property
    def duration_seconds(self) -> float | None:
        """Return total processing duration."""

        if self.completed_at is None:
            return None

        return max(
            0.0,
            (
                self.completed_at
                - self.started_at
            ).total_seconds(),
        )

    def complete(self) -> None:
        """Mark the result as complete."""

        self.completed_at = utc_now()

    def summary(self) -> dict[str, Any]:
        """Return compact deduplication statistics."""

        return {
            "total_articles": self.total_articles,
            "unique_articles": self.unique_count,
            "duplicate_articles": self.duplicate_count,
            "duplicate_clusters": self.cluster_count,
            "pair_comparisons": self.comparison_count,
            "started_at": self.started_at.isoformat(),
            "completed_at": (
                self.completed_at.isoformat()
                if self.completed_at
                else None
            ),
            "duration_seconds": self.duration_seconds,
        }

    def to_dict(
        self,
        *,
        include_articles: bool = False,
        include_comparisons: bool = True,
    ) -> dict[str, Any]:
        """Serialize the complete deduplication result."""

        data: dict[str, Any] = {
            **self.summary(),
            "clusters": [
                cluster.to_dict()
                for cluster in self.clusters
            ],
            "metadata": dict(self.metadata),
        }

        if include_comparisons:
            data["comparisons"] = [
                comparison.to_dict()
                for comparison in self.comparisons
            ]

        if include_articles:
            data["articles"] = [
                article.to_dict()
                for article in self.articles
            ]

        return data


# ==========================================================
# UNION-FIND
# ==========================================================

class _DisjointSet:
    """Small union-find structure used for duplicate clustering."""

    def __init__(self, article_ids: Iterable[str]) -> None:
        self._parent = {
            article_id: article_id
            for article_id in article_ids
        }
        self._rank = {
            article_id: 0
            for article_id in article_ids
        }

    def find(self, article_id: str) -> str:
        """Return the representative ID for one member."""

        parent = self._parent[article_id]

        if parent != article_id:
            self._parent[article_id] = self.find(
                parent
            )

        return self._parent[article_id]

    def union(
        self,
        left_article_id: str,
        right_article_id: str,
    ) -> None:
        """Join two article groups."""

        left_root = self.find(left_article_id)
        right_root = self.find(right_article_id)

        if left_root == right_root:
            return

        left_rank = self._rank[left_root]
        right_rank = self._rank[right_root]

        if left_rank < right_rank:
            self._parent[left_root] = right_root

        elif left_rank > right_rank:
            self._parent[right_root] = left_root

        else:
            self._parent[right_root] = left_root
            self._rank[left_root] += 1

    def groups(self) -> list[list[str]]:
        """Return all groups containing two or more members."""

        grouped: dict[str, list[str]] = defaultdict(list)

        for article_id in self._parent:
            grouped[self.find(article_id)].append(
                article_id
            )

        return [
            members
            for members in grouped.values()
            if len(members) > 1
        ]


# ==========================================================
# DEDUPLICATOR
# ==========================================================

class NewsDeduplicator:
    """Detect and mark duplicate NewsArticle objects."""

    def __init__(
        self,
        config: DeduplicatorConfig | None = None,
    ) -> None:
        self.config = (
            config
            if config is not None
            else DeduplicatorConfig()
        )

        if not isinstance(
            self.config,
            DeduplicatorConfig,
        ):
            raise TypeError(
                "config must be a DeduplicatorConfig instance."
            )

    # ======================================================
    # PUBLIC API
    # ======================================================

    def deduplicate(
        self,
        articles: Iterable[NewsArticle],
    ) -> DeduplicationResult:
        """
        Detect duplicate clusters and mark duplicate articles.

        The supplied article objects are updated in place when
        mark_duplicate_status is enabled.
        """

        article_list = self._normalize_articles(
            articles
        )

        result = DeduplicationResult(
            articles=article_list,
            clusters=[],
            comparisons=[],
            metadata={
                "config": self.config.to_dict(),
            },
        )

        if len(article_list) < 2:
            result.complete()
            return result

        article_by_id = {
            article.article_id: article
            for article in article_list
        }

        disjoint_set = _DisjointSet(
            article_by_id.keys()
        )

        duplicate_reasons: dict[
            frozenset[str],
            str,
        ] = {}

        for left_index, left_article in enumerate(
            article_list[:-1]
        ):
            for right_article in article_list[
                left_index + 1:
            ]:
                comparison = self.compare_articles(
                    left_article,
                    right_article,
                )
                result.comparisons.append(comparison)

                if comparison.duplicate:
                    disjoint_set.union(
                        left_article.article_id,
                        right_article.article_id,
                    )
                    duplicate_reasons[
                        frozenset(
                            {
                                left_article.article_id,
                                right_article.article_id,
                            }
                        )
                    ] = comparison.reason

        groups = disjoint_set.groups()

        for cluster_number, article_ids in enumerate(
            groups,
            start=1,
        ):
            cluster_articles = [
                article_by_id[article_id]
                for article_id in article_ids
            ]

            primary = self.select_primary_article(
                cluster_articles
            )

            ordered_articles = sorted(
                cluster_articles,
                key=lambda article: (
                    article.article_id
                    != primary.article_id,
                    article.article_id,
                ),
            )

            reasons = self._cluster_reasons(
                article_ids,
                duplicate_reasons,
            )

            cluster = DuplicateCluster(
                cluster_id=(
                    f"duplicate_cluster_"
                    f"{cluster_number:04d}"
                ),
                primary_article_id=(
                    primary.article_id
                ),
                article_ids=[
                    article.article_id
                    for article in ordered_articles
                ],
                reasons=reasons,
            )
            result.clusters.append(cluster)

            if self.config.mark_duplicate_status:
                self._mark_cluster_duplicates(
                    cluster_articles,
                    primary,
                    cluster,
                )

        result.metadata["duplicate_reason_counts"] = (
            self._reason_counts(
                result.comparisons
            )
        )
        result.complete()

        LOGGER.info(
            "Deduplication completed | total=%s | unique=%s | "
            "duplicates=%s | clusters=%s | comparisons=%s",
            result.total_articles,
            result.unique_count,
            result.duplicate_count,
            result.cluster_count,
            result.comparison_count,
        )

        return result

    def compare_articles(
        self,
        left: NewsArticle,
        right: NewsArticle,
    ) -> DuplicateComparison:
        """Compare two articles using exact and fuzzy signals."""

        self._validate_article(left)
        self._validate_article(right)

        comparison = DuplicateComparison(
            left_article_id=left.article_id,
            right_article_id=right.article_id,
            duplicate=False,
        )

        if left.article_id == right.article_id:
            comparison.duplicate = True
            comparison.reason = "identical_article_id"
            return comparison

        if not self._comparison_scope_matches(
            left,
            right,
        ):
            comparison.reason = "comparison_scope_mismatch"
            return comparison

        if not self._within_publication_window(
            left,
            right,
        ):
            comparison.reason = "outside_publication_window"
            return comparison

        left_url = self._article_url(left)
        right_url = self._article_url(right)

        comparison.metadata["left_url"] = left_url
        comparison.metadata["right_url"] = right_url

        if (
            left_url
            and right_url
            and left_url == right_url
        ):
            comparison.duplicate = True
            comparison.url_match = True
            comparison.reason = "identical_url"
            return comparison

        left_title = normalize_text(left.title)
        right_title = normalize_text(right.title)

        if (
            left_title
            and right_title
            and left_title == right_title
        ):
            comparison.duplicate = True
            comparison.title_exact_match = True
            comparison.title_similarity = 1.0
            comparison.reason = "identical_title"
            return comparison

        left_content = self._comparison_content(
            left
        )
        right_content = self._comparison_content(
            right
        )

        left_fingerprint = stable_hash(left_content)
        right_fingerprint = stable_hash(right_content)

        if (
            left_fingerprint
            and right_fingerprint
            and left_fingerprint
            == right_fingerprint
        ):
            comparison.duplicate = True
            comparison.content_exact_match = True
            comparison.content_similarity = 1.0
            comparison.reason = "identical_content"
            return comparison

        title_eligible = (
            len(left_title)
            >= self.config.minimum_title_characters
            and len(right_title)
            >= self.config.minimum_title_characters
        )

        content_eligible = (
            len(left_content)
            >= self.config.minimum_content_characters
            and len(right_content)
            >= self.config.minimum_content_characters
        )

        if title_eligible:
            comparison.title_similarity = (
                combined_text_similarity(
                    left_title,
                    right_title,
                    stop_words=self.config.stop_words,
                )
            )

        if content_eligible:
            comparison.content_similarity = (
                combined_text_similarity(
                    left_content,
                    right_content,
                    stop_words=self.config.stop_words,
                )
            )

        if (
            title_eligible
            and comparison.title_similarity
            >= self.config.title_similarity_threshold
        ):
            comparison.duplicate = True
            comparison.reason = "similar_title"
            return comparison

        if (
            content_eligible
            and comparison.content_similarity
            >= self.config.content_similarity_threshold
        ):
            comparison.duplicate = True
            comparison.reason = "similar_content"
            return comparison

        if title_eligible and content_eligible:
            comparison.combined_similarity = (
                comparison.title_similarity
                * self.config.normalized_title_weight
                + comparison.content_similarity
                * self.config.normalized_content_weight
            )

            if (
                comparison.combined_similarity
                >= self.config.combined_similarity_threshold
            ):
                comparison.duplicate = True
                comparison.reason = "combined_similarity"
                return comparison

        comparison.reason = "not_duplicate"

        return comparison

    def select_primary_article(
        self,
        articles: Iterable[NewsArticle],
    ) -> NewsArticle:
        """Choose the strongest primary article in a cluster."""

        article_list = list(articles)

        if not article_list:
            raise ValueError(
                "Cannot select a primary article from an empty collection."
            )

        for article in article_list:
            self._validate_article(article)

        return max(
            article_list,
            key=self.primary_quality_score,
        )

    def primary_quality_score(
        self,
        article: NewsArticle,
    ) -> tuple[Any, ...]:
        """
        Return deterministic quality ordering for primary selection.

        Higher values are preferred, except the final article ID is used
        only as a deterministic tie-breaker.
        """

        self._validate_article(article)

        content = (
            article.cleaned_text
            or article.raw_text
            or article.description
        )

        published_timestamp = (
            ensure_utc(article.published_at)
            or ensure_utc(article.collected_at)
            or datetime.min.replace(
                tzinfo=timezone.utc
            )
        ).timestamp()

        completeness = sum(
            1
            for value in (
                article.publisher,
                article.author,
                article.description,
                article.raw_text,
                article.image_url,
                article.published_at,
                article.canonical_url,
            )
            if value
        )

        non_terminal_status = int(
            article.status
            not in {
                ArticleStatus.REJECTED,
                ArticleStatus.FAILED,
                ArticleStatus.DUPLICATE,
            }
        )

        return (
            non_terminal_status,
            float(article.reliability_score),
            float(article.editorial_score),
            float(article.importance_score),
            float(article.relevance_score),
            completeness,
            int(bool(article.image_url)),
            min(len(content), 100_000),
            len(article.description),
            published_timestamp,
            article.article_id,
        )

    # ======================================================
    # MARKING
    # ======================================================

    def _mark_cluster_duplicates(
        self,
        cluster_articles: list[NewsArticle],
        primary: NewsArticle,
        cluster: DuplicateCluster,
    ) -> None:
        """Mark every non-primary cluster member as duplicate."""

        primary.metadata["duplicate_cluster_id"] = (
            cluster.cluster_id
        )
        primary.metadata["duplicate_cluster_size"] = (
            cluster.article_count
        )
        primary.metadata["duplicate_primary"] = True
        primary.metadata["duplicate_member_ids"] = (
            cluster.duplicate_article_ids
        )
        primary.updated_at = utc_now()

        for article in cluster_articles:
            if article.article_id == primary.article_id:
                continue

            if (
                self.config.preserve_existing_terminal_statuses
                and article.status
                in {
                    ArticleStatus.REJECTED,
                    ArticleStatus.FAILED,
                }
            ):
                article.metadata[
                    "detected_duplicate_of"
                ] = primary.article_id
                article.metadata[
                    "duplicate_cluster_id"
                ] = cluster.cluster_id
                article.updated_at = utc_now()
                continue

            article.metadata["previous_status"] = (
                article.status.value
            )
            article.metadata["duplicate_cluster_id"] = (
                cluster.cluster_id
            )
            article.metadata["duplicate_primary"] = False
            article.metadata["duplicate_reasons"] = list(
                cluster.reasons
            )

            article.update_status(
                ArticleStatus.DUPLICATE,
                duplicate_of=primary.article_id,
            )

    # ======================================================
    # COMPARISON HELPERS
    # ======================================================

    def _article_url(
        self,
        article: NewsArticle,
    ) -> str:
        """Return normalized article URL."""

        return normalize_url(
            article.canonical_url
            or article.url,
            ignored_query_parameters=(
                self.config.ignored_query_parameters
            ),
            remove_query_string=(
                self.config.remove_url_query_string
            ),
        )

    def _comparison_content(
        self,
        article: NewsArticle,
    ) -> str:
        """Return normalized bounded text used for content comparison."""

        content = (
            article.cleaned_text
            or article.raw_text
            or article.description
        )

        normalized = normalize_text(content)

        return normalized[
            :self.config.maximum_content_characters
        ]

    def _comparison_scope_matches(
        self,
        left: NewsArticle,
        right: NewsArticle,
    ) -> bool:
        """Return whether configured comparison scope permits the pair."""

        if (
            self.config.compare_within_language_only
            and left.language != right.language
        ):
            return False

        if (
            self.config.compare_within_category_only
            and left.category != right.category
        ):
            return False

        return True

    def _within_publication_window(
        self,
        left: NewsArticle,
        right: NewsArticle,
    ) -> bool:
        """Return whether two articles fall inside the configured window."""

        if not self.config.require_publication_window:
            return True

        left_time = ensure_utc(
            left.published_at
        )
        right_time = ensure_utc(
            right.published_at
        )

        if left_time is None or right_time is None:
            return True

        maximum_difference = timedelta(
            hours=self.config.publication_window_hours
        )

        return abs(left_time - right_time) <= maximum_difference

    # ======================================================
    # RESULT HELPERS
    # ======================================================

    @staticmethod
    def _cluster_reasons(
        article_ids: list[str],
        duplicate_reasons: Mapping[
            frozenset[str],
            str,
        ],
    ) -> list[str]:
        """Return deduplicated reasons associated with a cluster."""

        article_id_set = set(article_ids)
        reasons: list[str] = []

        for pair, reason in duplicate_reasons.items():
            if pair.issubset(article_id_set):
                if reason and reason not in reasons:
                    reasons.append(reason)

        return reasons

    @staticmethod
    def _reason_counts(
        comparisons: Iterable[DuplicateComparison],
    ) -> dict[str, int]:
        """Count duplicate reasons."""

        counts: dict[str, int] = defaultdict(int)

        for comparison in comparisons:
            if comparison.duplicate:
                counts[comparison.reason] += 1

        return dict(
            sorted(counts.items())
        )

    @staticmethod
    def _validate_article(
        article: NewsArticle,
    ) -> None:
        """Validate one article object."""

        if not isinstance(article, NewsArticle):
            raise TypeError(
                "Every item must be a NewsArticle instance."
            )

    def _normalize_articles(
        self,
        articles: Iterable[NewsArticle],
    ) -> list[NewsArticle]:
        """Validate and deduplicate article objects by article ID."""

        article_list: list[NewsArticle] = []
        seen_article_ids: set[str] = set()

        for article in articles:
            self._validate_article(article)

            if article.article_id in seen_article_ids:
                continue

            seen_article_ids.add(
                article.article_id
            )
            article_list.append(article)

        return article_list


# ==========================================================
# CONVENIENCE FUNCTION
# ==========================================================

def deduplicate_articles(
    articles: Iterable[NewsArticle],
    *,
    config: DeduplicatorConfig | None = None,
) -> DeduplicationResult:
    """Deduplicate articles using a temporary NewsDeduplicator."""

    return NewsDeduplicator(
        config=config
    ).deduplicate(articles)


# ==========================================================
# MODULE SELF-TEST
# ==========================================================

def _run_self_test() -> None:
    """Run deterministic duplicate-detection tests."""

    from news.models import (
        LanguageCode,
        NewsCategory,
    )

    published_at = datetime(
        2026,
        7,
        11,
        3,
        0,
        tzinfo=timezone.utc,
    )

    primary_article = NewsArticle(
        article_id="article_primary",
        title=(
            "Heavy rain continues across Andhra Pradesh "
            "as officials issue alerts"
        ),
        url=(
            "https://example.com/news/heavy-rain"
            "?utm_source=test"
        ),
        canonical_url=(
            "https://example.com/news/heavy-rain"
        ),
        source_id="source_reliable",
        source_name="Reliable News",
        publisher="Reliable News",
        author="Test Reporter",
        description=(
            "Officials issued alerts as heavy rainfall "
            "continued across several districts."
        ),
        raw_text=(
            "Heavy rainfall continued across several districts "
            "of Andhra Pradesh on Saturday. Officials issued "
            "alerts and advised residents in low-lying areas to "
            "remain cautious. Emergency response teams were placed "
            "on standby while authorities monitored reservoirs "
            "and road conditions throughout the state."
        ),
        image_url=(
            "https://example.com/images/heavy-rain.jpg"
        ),
        published_at=published_at,
        category=NewsCategory.WEATHER,
        language=LanguageCode.ENGLISH,
        reliability_score=92.0,
        importance_score=80.0,
        editorial_score=85.0,
    )

    same_url_article = NewsArticle(
        article_id="article_same_url",
        title=(
            "Andhra Pradesh receives heavy rain; "
            "authorities issue warning"
        ),
        url=(
            "https://example.com/news/heavy-rain"
            "?utm_campaign=social"
        ),
        source_id="source_copy",
        source_name="Copy News",
        description=(
            "Authorities advised residents to remain alert."
        ),
        raw_text=(
            "A shorter version of the same weather report."
        ),
        published_at=published_at,
        category=NewsCategory.WEATHER,
        language=LanguageCode.ENGLISH,
        reliability_score=65.0,
    )

    same_title_article = NewsArticle(
        article_id="article_same_title",
        title=(
            "Heavy rain continues across Andhra Pradesh "
            "as officials issue alerts"
        ),
        url=(
            "https://another.example.org/weather/"
            "andhra-rain-alert"
        ),
        source_id="source_syndicated",
        source_name="Syndicated News",
        description=(
            "The same report was carried by another publisher."
        ),
        raw_text=(
            "This article contains a shorter syndicated version "
            "of the weather report."
        ),
        published_at=published_at,
        category=NewsCategory.WEATHER,
        language=LanguageCode.ENGLISH,
        reliability_score=75.0,
    )

    similar_article = NewsArticle(
        article_id="article_similar",
        title=(
            "Officials issue alerts as heavy rain continues "
            "across Andhra Pradesh"
        ),
        url=(
            "https://third.example.net/news/"
            "ap-heavy-rain-warning"
        ),
        source_id="source_similar",
        source_name="Regional News",
        description=(
            "Heavy rain continued and officials issued alerts."
        ),
        raw_text=(
            "Heavy rainfall continued across several districts "
            "of Andhra Pradesh on Saturday. Officials issued "
            "alerts and advised residents in low lying areas to "
            "remain cautious. Emergency response teams were put "
            "on standby as authorities monitored reservoirs and "
            "road conditions across the state."
        ),
        published_at=published_at + timedelta(minutes=15),
        category=NewsCategory.WEATHER,
        language=LanguageCode.ENGLISH,
        reliability_score=78.0,
    )

    unique_article = NewsArticle(
        article_id="article_unique",
        title=(
            "Technology companies announce new semiconductor "
            "research programme"
        ),
        url=(
            "https://technology.example.com/news/"
            "semiconductor-research"
        ),
        source_id="source_technology",
        source_name="Technology Daily",
        description=(
            "Several companies announced a semiconductor "
            "research programme."
        ),
        raw_text=(
            "Technology companies announced a new collaborative "
            "research programme focused on semiconductor design, "
            "advanced manufacturing, and workforce development."
        ),
        published_at=published_at,
        category=NewsCategory.TECHNOLOGY,
        language=LanguageCode.ENGLISH,
        reliability_score=88.0,
    )

    config = DeduplicatorConfig(
        title_similarity_threshold=0.82,
        content_similarity_threshold=0.82,
        combined_similarity_threshold=0.78,
        minimum_title_characters=15,
        minimum_content_characters=80,
        compare_within_language_only=True,
        mark_duplicate_status=True,
    )

    deduplicator = NewsDeduplicator(
        config=config
    )

    result = deduplicator.deduplicate(
        [
            same_url_article,
            unique_article,
            similar_article,
            primary_article,
            same_title_article,
        ]
    )

    assert result.total_articles == 5
    assert result.cluster_count == 1
    assert result.unique_count == 2
    assert result.duplicate_count == 3
    assert result.comparison_count == 10

    cluster = result.clusters[0]

    assert cluster.primary_article_id == (
        primary_article.article_id
    )
    assert cluster.article_count == 4
    assert cluster.duplicate_count == 3

    assert primary_article.status != (
        ArticleStatus.DUPLICATE
    )
    assert primary_article.metadata[
        "duplicate_primary"
    ] is True
    assert primary_article.metadata[
        "duplicate_cluster_size"
    ] == 4

    for duplicate_article in (
        same_url_article,
        same_title_article,
        similar_article,
    ):
        assert duplicate_article.status == (
            ArticleStatus.DUPLICATE
        )
        assert duplicate_article.duplicate_of == (
            primary_article.article_id
        )

    assert unique_article.status != (
        ArticleStatus.DUPLICATE
    )
    assert unique_article.duplicate_of == ""

    url_comparison = deduplicator.compare_articles(
        primary_article,
        same_url_article,
    )
    assert url_comparison.duplicate
    assert url_comparison.url_match
    assert url_comparison.reason == "identical_url"

    title_comparison = deduplicator.compare_articles(
        primary_article,
        same_title_article,
    )
    assert title_comparison.duplicate
    assert title_comparison.title_exact_match
    assert title_comparison.reason == "identical_title"

    similar_comparison = deduplicator.compare_articles(
        primary_article,
        similar_article,
    )
    assert similar_comparison.duplicate
    assert similar_comparison.reason in {
        "similar_title",
        "similar_content",
        "combined_similarity",
    }

    unique_comparison = deduplicator.compare_articles(
        primary_article,
        unique_article,
    )
    assert not unique_comparison.duplicate

    serialized = result.to_dict(
        include_articles=True,
        include_comparisons=True,
    )

    assert serialized["total_articles"] == 5
    assert serialized["unique_articles"] == 2
    assert serialized["duplicate_articles"] == 3
    assert len(serialized["clusters"]) == 1
    assert len(serialized["comparisons"]) == 10
    assert len(serialized["articles"]) == 5

    print("News deduplicator initialized successfully.")
    print(
        f"Articles processed: {result.total_articles}"
    )
    print(
        f"Unique articles: {result.unique_count}"
    )
    print(
        f"Duplicate articles: {result.duplicate_count}"
    )
    print(
        f"Duplicate clusters: {result.cluster_count}"
    )
    print(
        f"Pair comparisons: {result.comparison_count}"
    )
    print(
        "Primary article: "
        f"{cluster.primary_article_id}"
    )
    print(
        "Duplicate members: "
        f"{', '.join(cluster.duplicate_article_ids)}"
    )
    print(
        "Detection reasons: "
        f"{', '.join(cluster.reasons)}"
    )
    print("News deduplicator self-test passed.")


if __name__ == "__main__":
    _run_self_test()