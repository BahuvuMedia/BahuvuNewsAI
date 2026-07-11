# news/article_scorer.py

"""
BahuvuNewsAI - News Article Scoring Engine
==========================================

This module evaluates collected news articles and assigns a transparent
editorial score from 0 to 100.

The scorer is intentionally independent of any single article model.
It accepts:

- dictionaries,
- dataclass instances,
- Pydantic-style objects,
- or normal Python objects with attributes.

Primary scoring dimensions:

1. Source credibility
2. Freshness
3. Headline quality
4. Content completeness
5. Article depth
6. Media availability
7. News significance
8. Geographic relevance
9. Duplicate penalty
10. Content-quality penalties

The output includes:

- final score,
- confidence,
- editorial decision,
- detailed component scores,
- bonuses,
- penalties,
- reasons,
- warnings,
- and recommendations.

Run the built-in self-test with:

    python -m news.article_scorer
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import urlparse


# =============================================================================
# CONSTANTS
# =============================================================================

SCORE_MIN = 0.0
SCORE_MAX = 100.0

WORD_PATTERN = re.compile(r"\b[\w'-]+\b", flags=re.UNICODE)
WHITESPACE_PATTERN = re.compile(r"\s+")
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
MULTIPLE_PUNCTUATION_PATTERN = re.compile(r"([!?.,])\1{1,}")
URL_PATTERN = re.compile(r"https?://\S+", flags=re.IGNORECASE)

DEFAULT_PUBLISH_THRESHOLD = 72.0
DEFAULT_REVIEW_THRESHOLD = 48.0

DEFAULT_SOURCE_SCORE = 55.0
UNKNOWN_CATEGORY_SCORE = 50.0

MAX_HEADLINE_WORDS = 18
MIN_HEADLINE_WORDS = 4

MAX_REASONABLE_ARTICLE_WORDS = 4000
MIN_COMPLETE_ARTICLE_WORDS = 120

DEFAULT_NOW = timezone.utc


# =============================================================================
# ENUMS
# =============================================================================


class EditorialDecision(str, Enum):
    """Editorial outcome produced from the final article score."""

    PUBLISH = "publish"
    REVIEW = "review"
    REJECT = "reject"


class ScoreBand(str, Enum):
    """Human-readable quality band."""

    EXCELLENT = "excellent"
    STRONG = "strong"
    ACCEPTABLE = "acceptable"
    WEAK = "weak"
    POOR = "poor"


# =============================================================================
# CONFIGURATION
# =============================================================================


@dataclass(frozen=True)
class ScoringWeights:
    """
    Relative importance of each positive scoring dimension.

    The weights should total 1.0. They are normalized automatically when the
    scorer is created, so custom configurations do not need to be exact.
    """

    source_credibility: float = 0.20
    freshness: float = 0.16
    headline_quality: float = 0.14
    content_completeness: float = 0.16
    article_depth: float = 0.10
    media_quality: float = 0.06
    significance: float = 0.10
    geographic_relevance: float = 0.08

    def as_dict(self) -> dict[str, float]:
        return {
            "source_credibility": self.source_credibility,
            "freshness": self.freshness,
            "headline_quality": self.headline_quality,
            "content_completeness": self.content_completeness,
            "article_depth": self.article_depth,
            "media_quality": self.media_quality,
            "significance": self.significance,
            "geographic_relevance": self.geographic_relevance,
        }

    def normalized(self) -> dict[str, float]:
        values = self.as_dict()
        total = sum(max(value, 0.0) for value in values.values())

        if total <= 0:
            raise ValueError("At least one scoring weight must be positive.")

        return {
            name: max(value, 0.0) / total
            for name, value in values.items()
        }


@dataclass(frozen=True)
class ScoringThresholds:
    """Editorial decision thresholds."""

    publish: float = DEFAULT_PUBLISH_THRESHOLD
    review: float = DEFAULT_REVIEW_THRESHOLD

    def __post_init__(self) -> None:
        if not 0 <= self.review <= 100:
            raise ValueError("Review threshold must be between 0 and 100.")

        if not 0 <= self.publish <= 100:
            raise ValueError("Publish threshold must be between 0 and 100.")

        if self.review >= self.publish:
            raise ValueError(
                "Review threshold must be lower than publish threshold."
            )


@dataclass(frozen=True)
class ScoringConfig:
    """Complete configuration for the article scorer."""

    weights: ScoringWeights = field(default_factory=ScoringWeights)
    thresholds: ScoringThresholds = field(default_factory=ScoringThresholds)

    preferred_regions: tuple[str, ...] = (
        "india",
        "andhra pradesh",
        "telangana",
        "amaravati",
        "hyderabad",
        "vijayawada",
        "visakhapatnam",
        "tirupati",
        "guntur",
        "nellore",
        "kurnool",
        "warangal",
    )

    priority_categories: tuple[str, ...] = (
        "breaking news",
        "national",
        "politics",
        "economy",
        "business",
        "technology",
        "science",
        "health",
        "world",
        "weather",
        "environment",
        "education",
        "agriculture",
    )

    low_value_categories: tuple[str, ...] = (
        "celebrity gossip",
        "rumours",
        "viral",
        "horoscope",
        "astrology",
    )

    trusted_domains: tuple[str, ...] = (
        "reuters.com",
        "apnews.com",
        "bbc.com",
        "bbc.co.uk",
        "thehindu.com",
        "indianexpress.com",
        "pti.in",
        "pib.gov.in",
        "rbi.org.in",
        "who.int",
        "un.org",
        "nasa.gov",
        "isro.gov.in",
        "eci.gov.in",
        "mospi.gov.in",
    )

    low_trust_domains: tuple[str, ...] = (
        "example.com",
        "unknown.invalid",
    )

    source_overrides: Mapping[str, float] = field(default_factory=dict)

    duplicate_penalty: float = 24.0
    near_duplicate_penalty: float = 12.0
    missing_body_penalty: float = 18.0
    clickbait_penalty: float = 12.0
    excessive_caps_penalty: float = 7.0
    suspicious_content_penalty: float = 18.0
    stale_article_penalty: float = 8.0
    malformed_url_penalty: float = 4.0

    future_date_tolerance_minutes: int = 30
    maximum_age_days: int = 30


# =============================================================================
# RESULT MODELS
# =============================================================================


@dataclass
class ScoreComponent:
    """Detailed score for one scoring dimension."""

    name: str
    raw_score: float
    weight: float
    weighted_score: float
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "raw_score": round(self.raw_score, 2),
            "weight": round(self.weight, 4),
            "weighted_score": round(self.weighted_score, 2),
            "explanation": self.explanation,
        }


@dataclass
class ScoreAdjustment:
    """Bonus or penalty applied after weighted scoring."""

    name: str
    amount: float
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "amount": round(self.amount, 2),
            "explanation": self.explanation,
        }


@dataclass
class ArticleScoreResult:
    """Complete scoring result for one article."""

    article_id: str
    final_score: float
    base_score: float
    confidence: float
    decision: EditorialDecision
    band: ScoreBand

    components: dict[str, ScoreComponent] = field(default_factory=dict)
    bonuses: list[ScoreAdjustment] = field(default_factory=list)
    penalties: list[ScoreAdjustment] = field(default_factory=list)

    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    scored_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def publishable(self) -> bool:
        return self.decision == EditorialDecision.PUBLISH

    @property
    def total_bonus(self) -> float:
        return sum(item.amount for item in self.bonuses)

    @property
    def total_penalty(self) -> float:
        return sum(abs(item.amount) for item in self.penalties)

    def to_dict(self) -> dict[str, Any]:
        return {
            "article_id": self.article_id,
            "final_score": round(self.final_score, 2),
            "base_score": round(self.base_score, 2),
            "confidence": round(self.confidence, 2),
            "decision": self.decision.value,
            "band": self.band.value,
            "publishable": self.publishable,
            "components": {
                name: component.to_dict()
                for name, component in self.components.items()
            },
            "bonuses": [item.to_dict() for item in self.bonuses],
            "penalties": [item.to_dict() for item in self.penalties],
            "total_bonus": round(self.total_bonus, 2),
            "total_penalty": round(self.total_penalty, 2),
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "recommendations": list(self.recommendations),
            "scored_at": self.scored_at.isoformat(),
        }


@dataclass
class ScoringStatistics:
    """Aggregate statistics for a batch of scoring results."""

    articles_scored: int
    average_score: float
    median_score: float
    highest_score: float
    lowest_score: float
    publish_count: int
    review_count: int
    reject_count: int
    average_confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# =============================================================================
# ARTICLE ACCESS
# =============================================================================


class ArticleView:
    """
    Normalized read-only access to article data.

    This class allows the scorer to work with dictionaries, dataclasses,
    Pydantic models and ordinary Python objects.
    """

    FIELD_ALIASES: dict[str, tuple[str, ...]] = {
        "id": (
            "id",
            "article_id",
            "news_id",
            "uid",
            "guid",
        ),
        "title": (
            "title",
            "headline",
            "name",
        ),
        "summary": (
            "summary",
            "description",
            "excerpt",
            "abstract",
            "subtitle",
        ),
        "content": (
            "content",
            "body",
            "article_text",
            "text",
            "full_text",
        ),
        "url": (
            "url",
            "link",
            "canonical_url",
            "source_url",
        ),
        "source": (
            "source",
            "source_name",
            "publisher",
            "publication",
            "provider",
        ),
        "source_domain": (
            "source_domain",
            "domain",
            "publisher_domain",
        ),
        "published_at": (
            "published_at",
            "published",
            "publication_date",
            "published_date",
            "date_published",
            "created_at",
            "timestamp",
        ),
        "category": (
            "category",
            "section",
            "topic",
            "news_category",
        ),
        "language": (
            "language",
            "lang",
            "locale",
        ),
        "location": (
            "location",
            "region",
            "place",
            "geography",
            "country",
            "state",
        ),
        "image_url": (
            "image_url",
            "image",
            "thumbnail",
            "thumbnail_url",
            "lead_image_url",
            "media_url",
        ),
        "video_url": (
            "video_url",
            "video",
        ),
        "author": (
            "author",
            "byline",
            "creator",
        ),
        "tags": (
            "tags",
            "keywords",
            "topics",
        ),
        "duplicate": (
            "duplicate",
            "is_duplicate",
            "duplicate_flag",
        ),
        "duplicate_score": (
            "duplicate_score",
            "similarity_score",
            "duplicate_similarity",
        ),
        "duplicate_of": (
            "duplicate_of",
            "primary_article_id",
            "canonical_article_id",
        ),
        "source_score": (
            "source_score",
            "credibility_score",
            "source_credibility",
            "trust_score",
        ),
        "importance": (
            "importance",
            "importance_score",
            "priority_score",
            "significance_score",
        ),
    }

    def __init__(self, article: Any) -> None:
        if article is None:
            raise ValueError("Article cannot be None.")

        self.original = article
        self.data = self._to_mapping(article)

    @staticmethod
    def _to_mapping(article: Any) -> dict[str, Any]:
        if isinstance(article, Mapping):
            return dict(article)

        if is_dataclass(article):
            return asdict(article)

        model_dump = getattr(article, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump()
            if isinstance(dumped, Mapping):
                return dict(dumped)

        dict_method = getattr(article, "dict", None)
        if callable(dict_method):
            try:
                dumped = dict_method()
                if isinstance(dumped, Mapping):
                    return dict(dumped)
            except TypeError:
                pass

        if hasattr(article, "__dict__"):
            return {
                key: value
                for key, value in vars(article).items()
                if not key.startswith("_")
            }

        raise TypeError(
            "Article must be a mapping, dataclass or object with attributes."
        )

    def get(self, field_name: str, default: Any = None) -> Any:
        aliases = self.FIELD_ALIASES.get(field_name, (field_name,))

        for alias in aliases:
            if alias in self.data:
                value = self.data[alias]
                if value is not None:
                    return value

        return default

    def text(self, field_name: str) -> str:
        value = self.get(field_name, "")

        if value is None:
            return ""

        if isinstance(value, str):
            return clean_text(value)

        if isinstance(value, (list, tuple, set)):
            return clean_text(
                " ".join(str(item) for item in value if item is not None)
            )

        if isinstance(value, Mapping):
            for key in ("name", "title", "label", "value"):
                if key in value and value[key]:
                    return clean_text(str(value[key]))

        return clean_text(str(value))

    def boolean(self, field_name: str) -> bool:
        value = self.get(field_name, False)

        if isinstance(value, bool):
            return value

        if isinstance(value, (int, float)):
            return bool(value)

        if isinstance(value, str):
            return value.strip().lower() in {
                "true",
                "yes",
                "1",
                "duplicate",
                "duplicated",
            }

        return False

    def number(
        self,
        field_name: str,
        default: Optional[float] = None,
    ) -> Optional[float]:
        value = self.get(field_name, default)

        if value is None:
            return default

        if isinstance(value, bool):
            return float(value)

        if isinstance(value, (int, float)):
            return float(value)

        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return default

    @property
    def article_id(self) -> str:
        identifier = self.text("id")

        if identifier:
            return identifier

        url = self.text("url")
        if url:
            return url

        title = self.text("title")
        if title:
            return title[:80]

        return "unknown-article"


# =============================================================================
# GENERAL HELPERS
# =============================================================================


def clamp(
    value: float,
    minimum: float = SCORE_MIN,
    maximum: float = SCORE_MAX,
) -> float:
    return max(minimum, min(maximum, value))


def clean_text(value: str) -> str:
    """Remove HTML, URLs and repeated whitespace from article text."""

    value = HTML_TAG_PATTERN.sub(" ", value or "")
    value = URL_PATTERN.sub(" ", value)
    value = value.replace("\u200b", " ")
    value = value.replace("\xa0", " ")
    value = WHITESPACE_PATTERN.sub(" ", value)
    return value.strip()


def tokenize(value: str) -> list[str]:
    return [
        token.lower()
        for token in WORD_PATTERN.findall(value or "")
        if token.strip()
    ]


def word_count(value: str) -> int:
    return len(tokenize(value))


def safe_domain(url_or_domain: str) -> str:
    value = (url_or_domain or "").strip().lower()

    if not value:
        return ""

    if "://" not in value:
        value = f"https://{value}"

    try:
        parsed = urlparse(value)
        domain = parsed.netloc.lower()
    except ValueError:
        return ""

    if domain.startswith("www."):
        domain = domain[4:]

    if ":" in domain:
        domain = domain.split(":", 1)[0]

    return domain


def domain_matches(domain: str, candidates: Iterable[str]) -> bool:
    domain = domain.lower().strip(".")

    for candidate in candidates:
        candidate = candidate.lower().strip(".")

        if domain == candidate or domain.endswith(f".{candidate}"):
            return True

    return False


def parse_datetime(value: Any) -> Optional[datetime]:
    """Parse common date representations into timezone-aware UTC datetime."""

    if value is None or value == "":
        return None

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        timestamp = float(value)

        if timestamp > 10_000_000_000:
            timestamp /= 1000.0

        try:
            parsed = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        text = str(value).strip()

        if not text:
            return None

        normalized = text.replace("Z", "+00:00")

        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            formats = (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%d",
                "%d-%m-%Y %H:%M:%S",
                "%d-%m-%Y",
                "%a, %d %b %Y %H:%M:%S %z",
                "%a, %d %b %Y %H:%M:%S GMT",
                "%d %b %Y %H:%M:%S %z",
            )

            parsed = None

            for date_format in formats:
                try:
                    parsed = datetime.strptime(text, date_format)
                    break
                except ValueError:
                    continue

            if parsed is None:
                return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def normalized_ratio(value: float) -> float:
    """
    Convert a possible 0-1 or 0-100 value to a 0-100 score.
    """

    if value <= 1.0:
        return clamp(value * 100.0)

    return clamp(value)


def percentage_of_uppercase_letters(value: str) -> float:
    letters = [character for character in value if character.isalpha()]

    if not letters:
        return 0.0

    uppercase_count = sum(character.isupper() for character in letters)
    return uppercase_count / len(letters)


def lexical_diversity(value: str) -> float:
    tokens = tokenize(value)

    if not tokens:
        return 0.0

    return len(set(tokens)) / len(tokens)


def repeated_word_ratio(value: str) -> float:
    tokens = tokenize(value)

    if len(tokens) < 4:
        return 0.0

    counts = Counter(tokens)
    repeated = sum(count - 1 for count in counts.values() if count > 1)

    return repeated / len(tokens)


# =============================================================================
# NEWS LANGUAGE PATTERNS
# =============================================================================


CLICKBAIT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, flags=re.IGNORECASE)
    for pattern in (
        r"\byou won'?t believe\b",
        r"\bshocking\b",
        r"\bmind[- ]blowing\b",
        r"\bwhat happened next\b",
        r"\bthis will change your life\b",
        r"\bsecret revealed\b",
        r"\bmust see\b",
        r"\bbreaking(?:\s+news)?!{2,}\b",
        r"\bviral\b",
        r"\bclick here\b",
        r"\bnumber \d+ will\b",
        r"\bthe truth about\b",
    )
)

SUSPICIOUS_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, flags=re.IGNORECASE)
    for pattern in (
        r"\bguaranteed profit\b",
        r"\bget rich quick\b",
        r"\bfree money\b",
        r"\bmiracle cure\b",
        r"\b100% confirmed\b",
        r"\bforward this message\b",
        r"\bshare immediately\b",
        r"\bunnamed sources confirm everything\b",
        r"\bno evidence needed\b",
    )
)

SIGNIFICANCE_KEYWORDS: Mapping[str, float] = {
    "election": 8.0,
    "government": 4.0,
    "parliament": 7.0,
    "assembly": 5.0,
    "supreme court": 8.0,
    "high court": 5.0,
    "budget": 7.0,
    "inflation": 6.0,
    "economy": 5.0,
    "policy": 5.0,
    "law": 4.0,
    "crime": 4.0,
    "arrest": 4.0,
    "disaster": 8.0,
    "cyclone": 8.0,
    "earthquake": 9.0,
    "flood": 7.0,
    "storm": 5.0,
    "heavy rain": 5.0,
    "warning": 4.0,
    "alert": 4.0,
    "death": 5.0,
    "killed": 6.0,
    "injured": 4.0,
    "war": 9.0,
    "ceasefire": 8.0,
    "attack": 7.0,
    "health": 4.0,
    "outbreak": 7.0,
    "pandemic": 9.0,
    "vaccine": 5.0,
    "research": 4.0,
    "science": 4.0,
    "space": 5.0,
    "isro": 7.0,
    "nasa": 6.0,
    "artificial intelligence": 5.0,
    "technology": 4.0,
    "education": 4.0,
    "students": 3.0,
    "farmers": 4.0,
    "agriculture": 4.0,
}


# =============================================================================
# ARTICLE SCORER
# =============================================================================


class ArticleScorer:
    """
    Production scoring engine for BahuvuNewsAI articles.

    Usage:

        scorer = ArticleScorer()
        result = scorer.score(article)

        print(result.final_score)
        print(result.decision.value)
    """

    def __init__(
        self,
        config: Optional[ScoringConfig] = None,
    ) -> None:
        self.config = config or ScoringConfig()
        self.weights = self.config.weights.normalized()

    def score(
        self,
        article: Any,
        *,
        now: Optional[datetime] = None,
    ) -> ArticleScoreResult:
        """Score one article and return a complete transparent result."""

        view = ArticleView(article)
        now_utc = self._normalize_now(now)

        components = {
            "source_credibility": self._score_source(view),
            "freshness": self._score_freshness(view, now_utc),
            "headline_quality": self._score_headline(view),
            "content_completeness": self._score_completeness(view),
            "article_depth": self._score_depth(view),
            "media_quality": self._score_media(view),
            "significance": self._score_significance(view),
            "geographic_relevance": self._score_geography(view),
        }

        base_score = sum(
            component.weighted_score
            for component in components.values()
        )

        bonuses = self._calculate_bonuses(view)
        penalties = self._calculate_penalties(view, now_utc)

        final_score = base_score
        final_score += sum(item.amount for item in bonuses)
        final_score += sum(item.amount for item in penalties)
        final_score = clamp(final_score)

        confidence = self._calculate_confidence(view, components)
        decision = self._decision_for_score(final_score, confidence)
        band = self._band_for_score(final_score)

        reasons = self._build_reasons(
            components=components,
            bonuses=bonuses,
            penalties=penalties,
            final_score=final_score,
        )

        warnings = self._build_warnings(view, components, penalties)
        recommendations = self._build_recommendations(
            view=view,
            components=components,
            penalties=penalties,
            decision=decision,
        )

        return ArticleScoreResult(
            article_id=view.article_id,
            final_score=round(final_score, 2),
            base_score=round(base_score, 2),
            confidence=round(confidence, 2),
            decision=decision,
            band=band,
            components=components,
            bonuses=bonuses,
            penalties=penalties,
            reasons=reasons,
            warnings=warnings,
            recommendations=recommendations,
            scored_at=now_utc,
        )

    def score_many(
        self,
        articles: Iterable[Any],
        *,
        now: Optional[datetime] = None,
        sort_descending: bool = True,
    ) -> list[ArticleScoreResult]:
        """Score multiple articles."""

        now_utc = self._normalize_now(now)

        results = [
            self.score(article, now=now_utc)
            for article in articles
        ]

        if sort_descending:
            results.sort(
                key=lambda item: (
                    item.final_score,
                    item.confidence,
                ),
                reverse=True,
            )

        return results

    def statistics(
        self,
        results: Iterable[ArticleScoreResult],
    ) -> ScoringStatistics:
        """Calculate aggregate statistics for scoring results."""

        result_list = list(results)

        if not result_list:
            return ScoringStatistics(
                articles_scored=0,
                average_score=0.0,
                median_score=0.0,
                highest_score=0.0,
                lowest_score=0.0,
                publish_count=0,
                review_count=0,
                reject_count=0,
                average_confidence=0.0,
            )

        scores = sorted(item.final_score for item in result_list)
        count = len(scores)

        if count % 2:
            median = scores[count // 2]
        else:
            median = (
                scores[(count // 2) - 1] + scores[count // 2]
            ) / 2.0

        decision_counts = Counter(
            item.decision for item in result_list
        )

        return ScoringStatistics(
            articles_scored=count,
            average_score=round(sum(scores) / count, 2),
            median_score=round(median, 2),
            highest_score=round(max(scores), 2),
            lowest_score=round(min(scores), 2),
            publish_count=decision_counts[EditorialDecision.PUBLISH],
            review_count=decision_counts[EditorialDecision.REVIEW],
            reject_count=decision_counts[EditorialDecision.REJECT],
            average_confidence=round(
                sum(item.confidence for item in result_list) / count,
                2,
            ),
        )

    @staticmethod
    def _normalize_now(now: Optional[datetime]) -> datetime:
        current = now or datetime.now(timezone.utc)

        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)

        return current.astimezone(timezone.utc)

    def _component(
        self,
        name: str,
        raw_score: float,
        explanation: str,
    ) -> ScoreComponent:
        weight = self.weights[name]
        score = clamp(raw_score)

        return ScoreComponent(
            name=name,
            raw_score=round(score, 2),
            weight=weight,
            weighted_score=round(score * weight, 2),
            explanation=explanation,
        )

    # =========================================================================
    # SOURCE CREDIBILITY
    # =========================================================================

    def _score_source(self, view: ArticleView) -> ScoreComponent:
        explicit_score = view.number("source_score")

        if explicit_score is not None:
            score = normalized_ratio(explicit_score)

            return self._component(
                "source_credibility",
                score,
                "Used article-provided source credibility score.",
            )

        source = view.text("source").lower()
        domain = view.text("source_domain")

        if not domain:
            domain = safe_domain(view.text("url"))

        overrides = {
            key.lower(): value
            for key, value in self.config.source_overrides.items()
        }

        override_candidates = [
            source,
            domain,
        ]

        for candidate in override_candidates:
            if candidate and candidate in overrides:
                score = normalized_ratio(overrides[candidate])

                return self._component(
                    "source_credibility",
                    score,
                    f"Applied configured credibility override for {candidate}.",
                )

        if domain and domain_matches(
            domain,
            self.config.trusted_domains,
        ):
            return self._component(
                "source_credibility",
                92.0,
                f"Recognized trusted source domain: {domain}.",
            )

        if domain and domain_matches(
            domain,
            self.config.low_trust_domains,
        ):
            return self._component(
                "source_credibility",
                25.0,
                f"Recognized low-trust source domain: {domain}.",
            )

        score = DEFAULT_SOURCE_SCORE
        evidence: list[str] = []

        if source:
            score += 5.0
            evidence.append("source name available")

        if domain:
            score += 5.0
            evidence.append("source domain available")

        if view.text("author"):
            score += 5.0
            evidence.append("author or byline available")

        url = view.text("url")
        if url.startswith("https://"):
            score += 4.0
            evidence.append("secure article URL")

        explanation = (
            "Estimated source credibility from available metadata"
        )

        if evidence:
            explanation += f": {', '.join(evidence)}."

        return self._component(
            "source_credibility",
            score,
            explanation,
        )

    # =========================================================================
    # FRESHNESS
    # =========================================================================

    def _score_freshness(
        self,
        view: ArticleView,
        now: datetime,
    ) -> ScoreComponent:
        published_at = parse_datetime(view.get("published_at"))

        if published_at is None:
            return self._component(
                "freshness",
                30.0,
                "Publication date is missing or could not be parsed.",
            )

        age_hours = (now - published_at).total_seconds() / 3600.0
        future_tolerance = (
            self.config.future_date_tolerance_minutes / 60.0
        )

        if age_hours < -future_tolerance:
            return self._component(
                "freshness",
                10.0,
                "Publication date is unexpectedly in the future.",
            )

        age_hours = max(age_hours, 0.0)

        if age_hours <= 1:
            score = 100.0
        elif age_hours <= 3:
            score = 97.0
        elif age_hours <= 6:
            score = 93.0
        elif age_hours <= 12:
            score = 88.0
        elif age_hours <= 24:
            score = 82.0
        elif age_hours <= 48:
            score = 72.0
        elif age_hours <= 72:
            score = 64.0
        elif age_hours <= 168:
            score = 52.0
        elif age_hours <= 336:
            score = 38.0
        elif age_hours <= 720:
            score = 24.0
        else:
            score = 10.0

        if age_hours < 24:
            age_description = f"{age_hours:.1f} hours old"
        else:
            age_description = f"{age_hours / 24.0:.1f} days old"

        return self._component(
            "freshness",
            score,
            f"Article is approximately {age_description}.",
        )

    # =========================================================================
    # HEADLINE QUALITY
    # =========================================================================

    def _score_headline(self, view: ArticleView) -> ScoreComponent:
        title = view.text("title")

        if not title:
            return self._component(
                "headline_quality",
                0.0,
                "Headline is missing.",
            )

        tokens = tokenize(title)
        count = len(tokens)
        score = 100.0
        issues: list[str] = []

        if count < 3:
            score -= 45.0
            issues.append("too short")
        elif count < MIN_HEADLINE_WORDS:
            score -= 20.0
            issues.append("slightly short")
        elif count > 30:
            score -= 35.0
            issues.append("far too long")
        elif count > MAX_HEADLINE_WORDS:
            score -= min((count - MAX_HEADLINE_WORDS) * 2.5, 25.0)
            issues.append("long")

        if len(title) < 20:
            score -= 15.0
            issues.append("limited detail")
        elif len(title) > 180:
            score -= 20.0
            issues.append("excessive character length")

        uppercase_ratio = percentage_of_uppercase_letters(title)

        if uppercase_ratio > 0.80 and len(title) > 12:
            score -= 22.0
            issues.append("excessive uppercase")
        elif uppercase_ratio > 0.55 and len(title) > 12:
            score -= 10.0
            issues.append("high uppercase usage")

        clickbait_matches = self._find_patterns(title, CLICKBAIT_PATTERNS)

        if clickbait_matches:
            score -= min(25.0, 10.0 * len(clickbait_matches))
            issues.append("clickbait language")

        if MULTIPLE_PUNCTUATION_PATTERN.search(title):
            score -= 10.0
            issues.append("repeated punctuation")

        if title.count("!") > 1:
            score -= 8.0
            issues.append("excessive exclamation marks")

        if repeated_word_ratio(title) > 0.25:
            score -= 8.0
            issues.append("repeated words")

        diversity = lexical_diversity(title)

        if count >= 7 and diversity < 0.65:
            score -= 8.0
            issues.append("low lexical variety")

        if title[-1:] in {".", ",", ";", ":"}:
            score -= 3.0
            issues.append("unnecessary trailing punctuation")

        if not issues:
            explanation = (
                f"Headline is clear and appropriately sized at {count} words."
            )
        else:
            explanation = (
                f"Headline contains {count} words; issues: "
                f"{', '.join(issues)}."
            )

        return self._component(
            "headline_quality",
            score,
            explanation,
        )

    # =========================================================================
    # CONTENT COMPLETENESS
    # =========================================================================

    def _score_completeness(self, view: ArticleView) -> ScoreComponent:
        title = view.text("title")
        summary = view.text("summary")
        content = view.text("content")
        url = view.text("url")
        source = view.text("source")
        category = view.text("category")
        published_at = parse_datetime(view.get("published_at"))

        score = 0.0
        available: list[str] = []
        missing: list[str] = []

        fields = (
            ("headline", title, 20.0),
            ("summary", summary, 14.0),
            ("content", content, 30.0),
            ("URL", url, 10.0),
            ("source", source, 9.0),
            ("publication date", published_at, 9.0),
            ("category", category, 8.0),
        )

        for field_name, value, points in fields:
            if value:
                score += points
                available.append(field_name)
            else:
                missing.append(field_name)

        summary_words = word_count(summary)
        content_words = word_count(content)

        if summary and summary_words < 8:
            score -= 5.0
            missing.append("substantive summary")

        if content and content_words < 50:
            score -= 12.0
            missing.append("substantive body content")
        elif content_words >= 150:
            score += 4.0

        explanation = (
            f"Available fields: {', '.join(available) or 'none'}."
        )

        if missing:
            explanation += f" Missing or weak: {', '.join(missing)}"

        return self._component(
            "content_completeness",
            score,
            explanation,
        )

    # =========================================================================
    # ARTICLE DEPTH
    # =========================================================================

    def _score_depth(self, view: ArticleView) -> ScoreComponent:
        content = view.text("content")
        summary = view.text("summary")

        body_words = word_count(content)
        summary_words = word_count(summary)
        effective_words = body_words or summary_words

        if effective_words == 0:
            score = 0.0
        elif effective_words < 30:
            score = 15.0
        elif effective_words < 60:
            score = 30.0
        elif effective_words < 120:
            score = 48.0
        elif effective_words < 200:
            score = 65.0
        elif effective_words < 350:
            score = 82.0
        elif effective_words <= 1200:
            score = 95.0
        elif effective_words <= MAX_REASONABLE_ARTICLE_WORDS:
            score = 90.0
        else:
            score = 75.0

        if content:
            diversity = lexical_diversity(content)

            if body_words >= 150 and diversity < 0.30:
                score -= 12.0
            elif body_words >= 150 and diversity > 0.55:
                score += 3.0

        return self._component(
            "article_depth",
            score,
            (
                f"Article contains {body_words} body words and "
                f"{summary_words} summary words."
            ),
        )

    # =========================================================================
    # MEDIA QUALITY
    # =========================================================================

    def _score_media(self, view: ArticleView) -> ScoreComponent:
        image_url = view.text("image_url")
        video_url = view.text("video_url")

        score = 15.0
        evidence: list[str] = []

        if image_url:
            score += 65.0
            evidence.append("lead image available")

            if image_url.startswith("https://"):
                score += 8.0
                evidence.append("secure image URL")

            image_lower = image_url.lower()

            if image_lower.endswith(
                (".jpg", ".jpeg", ".png", ".webp", ".avif")
            ):
                score += 7.0
                evidence.append("recognized image format")

        if video_url:
            score += 10.0
            evidence.append("video media available")

        if not evidence:
            explanation = "No usable image or video metadata was found."
        else:
            explanation = ", ".join(evidence).capitalize() + "."

        return self._component(
            "media_quality",
            score,
            explanation,
        )

    # =========================================================================
    # SIGNIFICANCE
    # =========================================================================

    def _score_significance(self, view: ArticleView) -> ScoreComponent:
        explicit = view.number("importance")

        if explicit is not None:
            score = normalized_ratio(explicit)

            return self._component(
                "significance",
                score,
                "Used article-provided importance score.",
            )

        title = view.text("title")
        summary = view.text("summary")
        content = view.text("content")
        category = view.text("category").lower()

        combined = f"{title} {summary} {content[:3000]}".lower()

        score = 42.0
        matches: list[str] = []

        for keyword, points in SIGNIFICANCE_KEYWORDS.items():
            if keyword in combined:
                score += points
                matches.append(keyword)

        if category in self.config.priority_categories:
            score += 12.0

        if category in self.config.low_value_categories:
            score -= 25.0

        if any(
            marker in combined
            for marker in (
                "official",
                "ministry",
                "government announced",
                "court ruled",
                "police said",
                "report released",
                "according to",
            )
        ):
            score += 5.0

        score = clamp(score)

        if matches:
            explanation = (
                "Detected significant news indicators: "
                + ", ".join(matches[:6])
                + "."
            )
        else:
            explanation = (
                "No strong significance indicators were detected."
            )

        return self._component(
            "significance",
            score,
            explanation,
        )

    # =========================================================================
    # GEOGRAPHIC RELEVANCE
    # =========================================================================

    def _score_geography(self, view: ArticleView) -> ScoreComponent:
        title = view.text("title")
        summary = view.text("summary")
        location = view.text("location")
        tags = view.text("tags")

        combined = f"{title} {summary} {location} {tags}".lower()

        matched_regions = [
            region
            for region in self.config.preferred_regions
            if region.lower() in combined
        ]

        if matched_regions:
            score = min(100.0, 78.0 + (len(matched_regions) * 6.0))

            return self._component(
                "geographic_relevance",
                score,
                (
                    "Matched preferred regions: "
                    + ", ".join(matched_regions[:5])
                    + "."
                ),
            )

        if location:
            return self._component(
                "geographic_relevance",
                58.0,
                f"Location metadata is available: {location}.",
            )

        return self._component(
            "geographic_relevance",
            42.0,
            "No preferred-region match or clear location was found.",
        )

    # =========================================================================
    # BONUSES
    # =========================================================================

    def _calculate_bonuses(
        self,
        view: ArticleView,
    ) -> list[ScoreAdjustment]:
        bonuses: list[ScoreAdjustment] = []

        title = view.text("title")
        content = view.text("content")
        source = view.text("source")
        author = view.text("author")
        category = view.text("category").lower()
        url = view.text("url")

        if title and content and source and url:
            bonuses.append(
                ScoreAdjustment(
                    name="core_metadata_complete",
                    amount=2.0,
                    explanation=(
                        "Headline, content, source and URL are all present."
                    ),
                )
            )

        if author:
            bonuses.append(
                ScoreAdjustment(
                    name="author_available",
                    amount=1.0,
                    explanation="Article includes an author or byline.",
                )
            )

        if category in self.config.priority_categories:
            bonuses.append(
                ScoreAdjustment(
                    name="priority_category",
                    amount=2.0,
                    explanation=(
                        f"Article belongs to priority category: {category}."
                    ),
                )
            )

        if word_count(content) >= 350:
            bonuses.append(
                ScoreAdjustment(
                    name="substantive_reporting",
                    amount=2.0,
                    explanation=(
                        "Article contains substantial body content."
                    ),
                )
            )

        return bonuses

    # =========================================================================
    # PENALTIES
    # =========================================================================

    def _calculate_penalties(
        self,
        view: ArticleView,
        now: datetime,
    ) -> list[ScoreAdjustment]:
        penalties: list[ScoreAdjustment] = []

        title = view.text("title")
        summary = view.text("summary")
        content = view.text("content")
        combined = f"{title} {summary} {content[:5000]}"

        if view.boolean("duplicate"):
            penalties.append(
                ScoreAdjustment(
                    name="confirmed_duplicate",
                    amount=-abs(self.config.duplicate_penalty),
                    explanation=(
                        "Article is explicitly marked as a duplicate."
                    ),
                )
            )
        else:
            duplicate_score = view.number("duplicate_score")

            if duplicate_score is not None:
                duplicate_score = normalized_ratio(duplicate_score)

                if duplicate_score >= 90:
                    penalties.append(
                        ScoreAdjustment(
                            name="probable_duplicate",
                            amount=-abs(
                                self.config.near_duplicate_penalty
                            ),
                            explanation=(
                                "Article has a very high duplicate "
                                f"similarity score of {duplicate_score:.1f}."
                            ),
                        )
                    )
                elif duplicate_score >= 80:
                    penalties.append(
                        ScoreAdjustment(
                            name="possible_duplicate",
                            amount=-abs(
                                self.config.near_duplicate_penalty / 2.0
                            ),
                            explanation=(
                                "Article has an elevated duplicate "
                                f"similarity score of {duplicate_score:.1f}."
                            ),
                        )
                    )

        if not content and word_count(summary) < 20:
            penalties.append(
                ScoreAdjustment(
                    name="missing_body",
                    amount=-abs(self.config.missing_body_penalty),
                    explanation=(
                        "Article body is missing and summary is too short."
                    ),
                )
            )

        clickbait_matches = self._find_patterns(
            title,
            CLICKBAIT_PATTERNS,
        )

        if clickbait_matches:
            penalties.append(
                ScoreAdjustment(
                    name="clickbait",
                    amount=-abs(self.config.clickbait_penalty),
                    explanation=(
                        "Headline contains clickbait language."
                    ),
                )
            )

        if percentage_of_uppercase_letters(title) > 0.80 and len(title) > 12:
            penalties.append(
                ScoreAdjustment(
                    name="excessive_caps",
                    amount=-abs(self.config.excessive_caps_penalty),
                    explanation=(
                        "Headline uses excessive uppercase lettering."
                    ),
                )
            )

        suspicious_matches = self._find_patterns(
            combined,
            SUSPICIOUS_PATTERNS,
        )

        if suspicious_matches:
            penalties.append(
                ScoreAdjustment(
                    name="suspicious_content",
                    amount=-abs(
                        self.config.suspicious_content_penalty
                    ),
                    explanation=(
                        "Article contains suspicious or spam-like claims."
                    ),
                )
            )

        published_at = parse_datetime(view.get("published_at"))

        if published_at is not None:
            age_days = (now - published_at).total_seconds() / 86400.0

            if age_days > self.config.maximum_age_days:
                penalties.append(
                    ScoreAdjustment(
                        name="stale_article",
                        amount=-abs(
                            self.config.stale_article_penalty
                        ),
                        explanation=(
                            f"Article is older than "
                            f"{self.config.maximum_age_days} days."
                        ),
                    )
                )

        url = view.text("url")

        if url and not safe_domain(url):
            penalties.append(
                ScoreAdjustment(
                    name="malformed_url",
                    amount=-abs(
                        self.config.malformed_url_penalty
                    ),
                    explanation="Article URL could not be parsed.",
                )
            )

        category = view.text("category").lower()

        if category in self.config.low_value_categories:
            penalties.append(
                ScoreAdjustment(
                    name="low_value_category",
                    amount=-8.0,
                    explanation=(
                        f"Category has low editorial priority: {category}."
                    ),
                )
            )

        return penalties

    # =========================================================================
    # CONFIDENCE
    # =========================================================================

    def _calculate_confidence(
        self,
        view: ArticleView,
        components: Mapping[str, ScoreComponent],
    ) -> float:
        """
        Confidence measures how complete and dependable the input evidence is.

        It is distinct from the article's editorial quality score.
        """

        evidence_fields = (
            "title",
            "summary",
            "content",
            "url",
            "source",
            "published_at",
            "category",
            "location",
            "image_url",
            "author",
        )

        present = 0

        for field_name in evidence_fields:
            value = view.get(field_name)

            if value not in (None, "", [], (), {}):
                present += 1

        field_coverage = present / len(evidence_fields)
        confidence = 40.0 + (field_coverage * 50.0)

        if components["source_credibility"].raw_score >= 80:
            confidence += 5.0

        if parse_datetime(view.get("published_at")) is not None:
            confidence += 3.0

        if word_count(view.text("content")) >= 120:
            confidence += 2.0

        return clamp(confidence)

    # =========================================================================
    # DECISION AND OUTPUT
    # =========================================================================

    def _decision_for_score(
        self,
        score: float,
        confidence: float,
    ) -> EditorialDecision:
        thresholds = self.config.thresholds

        if score >= thresholds.publish and confidence >= 55.0:
            return EditorialDecision.PUBLISH

        if score >= thresholds.review:
            return EditorialDecision.REVIEW

        return EditorialDecision.REJECT

    @staticmethod
    def _band_for_score(score: float) -> ScoreBand:
        if score >= 85:
            return ScoreBand.EXCELLENT
        if score >= 72:
            return ScoreBand.STRONG
        if score >= 55:
            return ScoreBand.ACCEPTABLE
        if score >= 35:
            return ScoreBand.WEAK
        return ScoreBand.POOR

    @staticmethod
    def _build_reasons(
        *,
        components: Mapping[str, ScoreComponent],
        bonuses: list[ScoreAdjustment],
        penalties: list[ScoreAdjustment],
        final_score: float,
    ) -> list[str]:
        reasons: list[str] = []

        ranked = sorted(
            components.values(),
            key=lambda item: item.raw_score,
            reverse=True,
        )

        for component in ranked[:3]:
            if component.raw_score >= 70:
                readable = component.name.replace("_", " ")
                reasons.append(
                    f"Strong {readable}: {component.raw_score:.1f}/100."
                )

        for component in reversed(ranked):
            if component.raw_score < 45:
                readable = component.name.replace("_", " ")
                reasons.append(
                    f"Weak {readable}: {component.raw_score:.1f}/100."
                )

            if len(reasons) >= 5:
                break

        for adjustment in bonuses[:2]:
            reasons.append(adjustment.explanation)

        for adjustment in penalties[:3]:
            reasons.append(adjustment.explanation)

        if not reasons:
            reasons.append(
                f"Article received a balanced final score of "
                f"{final_score:.1f}/100."
            )

        return reasons[:8]

    @staticmethod
    def _build_warnings(
        view: ArticleView,
        components: Mapping[str, ScoreComponent],
        penalties: list[ScoreAdjustment],
    ) -> list[str]:
        warnings: list[str] = []

        if not view.text("title"):
            warnings.append("Headline is missing.")

        if not view.text("content"):
            warnings.append("Full article body is unavailable.")

        if not view.text("source"):
            warnings.append("Source name is unavailable.")

        if parse_datetime(view.get("published_at")) is None:
            warnings.append(
                "Publication time is missing or invalid."
            )

        if components["source_credibility"].raw_score < 40:
            warnings.append(
                "Source credibility is below the acceptable range."
            )

        penalty_names = {item.name for item in penalties}

        if "confirmed_duplicate" in penalty_names:
            warnings.append(
                "Article is marked as a confirmed duplicate."
            )

        if "suspicious_content" in penalty_names:
            warnings.append(
                "Suspicious promotional or unsupported claims detected."
            )

        return warnings

    @staticmethod
    def _build_recommendations(
        *,
        view: ArticleView,
        components: Mapping[str, ScoreComponent],
        penalties: list[ScoreAdjustment],
        decision: EditorialDecision,
    ) -> list[str]:
        recommendations: list[str] = []

        if decision == EditorialDecision.PUBLISH:
            recommendations.append(
                "Article is suitable for the downstream editorial pipeline."
            )
        elif decision == EditorialDecision.REVIEW:
            recommendations.append(
                "Send the article for human editorial review."
            )
        else:
            recommendations.append(
                "Do not publish without substantial verification or revision."
            )

        if components["source_credibility"].raw_score < 60:
            recommendations.append(
                "Verify the story with an additional trusted source."
            )

        if components["freshness"].raw_score < 50:
            recommendations.append(
                "Confirm that the story is still timely and relevant."
            )

        if components["headline_quality"].raw_score < 60:
            recommendations.append(
                "Rewrite the headline for clarity and neutrality."
            )

        if components["content_completeness"].raw_score < 60:
            recommendations.append(
                "Collect the full article body and missing metadata."
            )

        if not view.text("image_url"):
            recommendations.append(
                "Find a licensed and editorially relevant lead image."
            )

        penalty_names = {item.name for item in penalties}

        if penalty_names.intersection(
            {"confirmed_duplicate", "probable_duplicate"}
        ):
            recommendations.append(
                "Use the primary article from the duplicate cluster."
            )

        return recommendations[:6]

    @staticmethod
    def _find_patterns(
        value: str,
        patterns: Iterable[re.Pattern[str]],
    ) -> list[str]:
        matches: list[str] = []

        for pattern in patterns:
            match = pattern.search(value or "")

            if match:
                matches.append(match.group(0))

        return matches


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def score_article(
    article: Any,
    *,
    config: Optional[ScoringConfig] = None,
    now: Optional[datetime] = None,
) -> ArticleScoreResult:
    """Score one article using a temporary scorer instance."""

    scorer = ArticleScorer(config=config)
    return scorer.score(article, now=now)


def score_articles(
    articles: Iterable[Any],
    *,
    config: Optional[ScoringConfig] = None,
    now: Optional[datetime] = None,
    sort_descending: bool = True,
) -> list[ArticleScoreResult]:
    """Score multiple articles using a temporary scorer instance."""

    scorer = ArticleScorer(config=config)

    return scorer.score_many(
        articles,
        now=now,
        sort_descending=sort_descending,
    )


# =============================================================================
# SELF-TEST
# =============================================================================


def _make_test_articles(now: datetime) -> list[dict[str, Any]]:
    strong_content = """
    The Andhra Pradesh government issued a weather alert after heavy rain
    affected several districts. Officials said emergency teams were deployed
    and local administrations were instructed to monitor reservoirs, roads
    and low-lying areas. The India Meteorological Department forecast further
    rainfall during the next twenty-four hours.

    District authorities advised residents to avoid flooded roads and remain
    alert for official warnings. Control rooms were opened in affected areas,
    while electricity and municipal teams began responding to local reports.
    Farmers were also advised to protect harvested crops and agricultural
    equipment from continuing rain.

    Officials said the situation remained under observation and confirmed
    that additional response teams would be deployed if conditions worsened.
    """

    return [
        {
            "id": "article_strong",
            "title": (
                "Heavy Rain Alert Issued Across Andhra Pradesh "
                "as Officials Deploy Emergency Teams"
            ),
            "summary": (
                "Authorities have placed several districts on alert as "
                "heavy rainfall continues across Andhra Pradesh."
            ),
            "content": strong_content,
            "url": (
                "https://www.thehindu.com/news/national/"
                "andhra-pradesh/weather-alert-example"
            ),
            "source": "The Hindu",
            "published_at": now.isoformat(),
            "category": "weather",
            "location": "Andhra Pradesh, India",
            "image_url": (
                "https://images.example.org/andhra-rain.jpg"
            ),
            "author": "Staff Reporter",
            "tags": ["weather", "Andhra Pradesh", "heavy rain"],
            "duplicate": False,
        },
        {
            "id": "article_review",
            "title": "Technology Companies Announce New AI Services",
            "summary": (
                "Several companies introduced new artificial intelligence "
                "services for business users."
            ),
            "content": (
                "Technology companies announced new services during an "
                "industry event. More details are expected from official "
                "sources."
            ),
            "url": "https://regionalnews.example.net/technology/ai-services",
            "source": "Regional News Network",
            "published_at": now.isoformat(),
            "category": "technology",
            "location": "India",
            "duplicate": False,
        },
        {
            "id": "article_duplicate",
            "title": "SHOCKING!!! YOU WON'T BELIEVE THIS VIRAL NEWS",
            "summary": "Share immediately. This is 100% confirmed.",
            "content": "",
            "url": "https://example.com/viral/story",
            "source": "Unknown Viral Page",
            "published_at": "2024-01-01T00:00:00+00:00",
            "category": "viral",
            "duplicate": True,
            "duplicate_score": 0.99,
        },
    ]


def _run_self_test() -> None:
    fixed_now = datetime(
        2026,
        7,
        11,
        6,
        0,
        0,
        tzinfo=timezone.utc,
    )

    scorer = ArticleScorer()
    articles = _make_test_articles(fixed_now)
    results = scorer.score_many(articles, now=fixed_now)

    result_by_id = {
        result.article_id: result
        for result in results
    }

    strong = result_by_id["article_strong"]
    review = result_by_id["article_review"]
    duplicate = result_by_id["article_duplicate"]

    assert 0.0 <= strong.final_score <= 100.0
    assert 0.0 <= review.final_score <= 100.0
    assert 0.0 <= duplicate.final_score <= 100.0

    assert strong.final_score > review.final_score
    assert review.final_score > duplicate.final_score

    assert strong.decision == EditorialDecision.PUBLISH
    assert duplicate.decision == EditorialDecision.REJECT

    assert "source_credibility" in strong.components
    assert "freshness" in strong.components
    assert "headline_quality" in strong.components
    assert "content_completeness" in strong.components

    duplicate_penalty_names = {
        item.name for item in duplicate.penalties
    }

    assert "confirmed_duplicate" in duplicate_penalty_names
    assert "clickbait" in duplicate_penalty_names
    assert duplicate.publishable is False

    serialized = strong.to_dict()
    assert serialized["article_id"] == "article_strong"
    assert serialized["decision"] == "publish"
    assert isinstance(serialized["components"], dict)

    statistics = scorer.statistics(results)

    assert statistics.articles_scored == 3
    assert statistics.publish_count >= 1
    assert statistics.reject_count >= 1
    assert statistics.highest_score == strong.final_score
    assert statistics.lowest_score == duplicate.final_score

    print("News article scorer initialized successfully.")
    print(f"Articles scored: {statistics.articles_scored}")
    print(f"Average score: {statistics.average_score:.2f}")
    print(f"Highest score: {statistics.highest_score:.2f}")
    print(f"Lowest score: {statistics.lowest_score:.2f}")
    print(f"Publish decisions: {statistics.publish_count}")
    print(f"Review decisions: {statistics.review_count}")
    print(f"Reject decisions: {statistics.reject_count}")
    print()

    for result in results:
        print(
            f"{result.article_id}: "
            f"score={result.final_score:.2f}, "
            f"confidence={result.confidence:.2f}, "
            f"decision={result.decision.value}, "
            f"band={result.band.value}"
        )

    print("News article scorer self-test passed.")


if __name__ == "__main__":
    _run_self_test()