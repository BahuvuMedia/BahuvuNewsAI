# news/editorial_validator.py

"""
BahuvuNewsAI - Editorial Validation Engine
==========================================

This module acts as the newsroom gatekeeper between article scoring and
downstream production.

The article scorer answers:

    "How strong is this article?"

The editorial validator answers:

    "May this article proceed into the BahuvuNewsAI production pipeline?"

The validator performs hard editorial checks, policy checks, metadata checks,
quality checks, duplicate checks and readiness checks.

Supported article inputs:

- dictionaries,
- dataclass instances,
- Pydantic-style objects,
- regular Python objects with attributes.

Supported scorer inputs:

- ArticleScoreResult from news.article_scorer,
- dictionaries containing score information,
- numeric scores,
- or automatic scoring through ArticleScorer.

Possible final decisions:

- ACCEPT: article may enter the production pipeline.
- REVIEW: article requires human editorial review.
- REJECT: article must not proceed.

Run the built-in self-test with:

    python -m news.editorial_validator
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import urlparse

try:
    from news.article_scorer import (
        ArticleScoreResult,
        ArticleScorer,
        EditorialDecision,
    )
except ImportError:
    ArticleScoreResult = Any  # type: ignore[misc,assignment]
    ArticleScorer = None  # type: ignore[assignment]

    class EditorialDecision(str, Enum):
        PUBLISH = "publish"
        REVIEW = "review"
        REJECT = "reject"


# =============================================================================
# CONSTANTS
# =============================================================================

MINIMUM_SCORE = 0.0
MAXIMUM_SCORE = 100.0

DEFAULT_ACCEPT_SCORE = 72.0
DEFAULT_REVIEW_SCORE = 48.0

DEFAULT_MINIMUM_HEADLINE_WORDS = 4
DEFAULT_MAXIMUM_HEADLINE_WORDS = 30
DEFAULT_MINIMUM_SUMMARY_WORDS = 8
DEFAULT_MINIMUM_BODY_WORDS = 60
DEFAULT_PREFERRED_BODY_WORDS = 120

DEFAULT_MAXIMUM_ARTICLE_AGE_DAYS = 30
DEFAULT_MAXIMUM_FUTURE_MINUTES = 30

WORD_PATTERN = re.compile(r"\b[\w'-]+\b", flags=re.UNICODE)
HTML_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")
CONTROL_CHARACTER_PATTERN = re.compile(
    r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]"
)

CLICKBAIT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, flags=re.IGNORECASE)
    for pattern in (
        r"\byou won'?t believe\b",
        r"\bshocking\b",
        r"\bwhat happened next\b",
        r"\bmust see\b",
        r"\bsecret revealed\b",
        r"\bclick here\b",
        r"\bviral\b",
        r"\bshare immediately\b",
        r"\b100% confirmed\b",
        r"\bbreaking(?:\s+news)?!{2,}\b",
    )
)

SUSPICIOUS_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, flags=re.IGNORECASE)
    for pattern in (
        r"\bguaranteed profit\b",
        r"\bget rich quick\b",
        r"\bfree money\b",
        r"\bmiracle cure\b",
        r"\bforward this message\b",
        r"\bno evidence needed\b",
        r"\bsecret government cure\b",
        r"\bunnamed sources confirm everything\b",
    )
)

DEFAULT_ALLOWED_LANGUAGES = (
    "en",
    "english",
    "te",
    "telugu",
)

DEFAULT_ALLOWED_CATEGORIES = (
    "breaking news",
    "national",
    "state",
    "regional",
    "politics",
    "government",
    "world",
    "international",
    "business",
    "economy",
    "technology",
    "science",
    "health",
    "education",
    "agriculture",
    "weather",
    "environment",
    "sports",
    "crime",
    "law",
    "culture",
    "entertainment",
    "general",
)

DEFAULT_BLOCKED_CATEGORIES = (
    "spam",
    "advertisement",
    "promotional",
    "horoscope",
    "astrology",
    "rumour",
    "rumors",
    "celebrity gossip",
)

DEFAULT_BLOCKED_DOMAINS = (
    "example.com",
    "unknown.invalid",
)

DEFAULT_TRUSTED_DOMAINS = (
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
)


# =============================================================================
# ENUMS
# =============================================================================


class ValidationDecision(str, Enum):
    """Final newsroom validation outcome."""

    ACCEPT = "accept"
    REVIEW = "review"
    REJECT = "reject"


class ValidationSeverity(str, Enum):
    """Severity of an individual validation rule."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ValidationStatus(str, Enum):
    """Pass/fail state of one validation rule."""

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


class RuleCategory(str, Enum):
    """Logical category for validation rules."""

    METADATA = "metadata"
    EDITORIAL = "editorial"
    QUALITY = "quality"
    POLICY = "policy"
    DUPLICATE = "duplicate"
    READINESS = "readiness"


# =============================================================================
# CONFIGURATION
# =============================================================================


@dataclass(frozen=True)
class EditorialValidationConfig:
    """Complete configuration for the editorial validator."""

    accept_score: float = DEFAULT_ACCEPT_SCORE
    review_score: float = DEFAULT_REVIEW_SCORE

    minimum_headline_words: int = DEFAULT_MINIMUM_HEADLINE_WORDS
    maximum_headline_words: int = DEFAULT_MAXIMUM_HEADLINE_WORDS
    minimum_summary_words: int = DEFAULT_MINIMUM_SUMMARY_WORDS
    minimum_body_words: int = DEFAULT_MINIMUM_BODY_WORDS
    preferred_body_words: int = DEFAULT_PREFERRED_BODY_WORDS

    maximum_article_age_days: int = DEFAULT_MAXIMUM_ARTICLE_AGE_DAYS
    maximum_future_minutes: int = DEFAULT_MAXIMUM_FUTURE_MINUTES

    require_title: bool = True
    require_url: bool = True
    require_source: bool = True
    require_publication_date: bool = True
    require_category: bool = True
    require_summary: bool = False
    require_body: bool = True
    require_image_for_acceptance: bool = False

    reject_confirmed_duplicates: bool = True
    reject_blocked_domains: bool = True
    reject_blocked_categories: bool = True
    reject_suspicious_content: bool = True
    reject_future_dates: bool = True

    review_unknown_language: bool = True
    review_unknown_category: bool = True
    review_missing_image: bool = True
    review_untrusted_source: bool = False
    review_clickbait: bool = True

    allowed_languages: tuple[str, ...] = DEFAULT_ALLOWED_LANGUAGES
    allowed_categories: tuple[str, ...] = DEFAULT_ALLOWED_CATEGORIES
    blocked_categories: tuple[str, ...] = DEFAULT_BLOCKED_CATEGORIES
    blocked_domains: tuple[str, ...] = DEFAULT_BLOCKED_DOMAINS
    trusted_domains: tuple[str, ...] = DEFAULT_TRUSTED_DOMAINS

    minimum_source_score: float = 40.0
    minimum_confidence_for_acceptance: float = 55.0
    duplicate_similarity_reject_threshold: float = 95.0
    duplicate_similarity_review_threshold: float = 80.0

    def __post_init__(self) -> None:
        if not 0 <= self.review_score < self.accept_score <= 100:
            raise ValueError(
                "Validation score thresholds must satisfy "
                "0 <= review_score < accept_score <= 100."
            )

        if self.minimum_headline_words < 1:
            raise ValueError(
                "Minimum headline words must be at least 1."
            )

        if (
            self.maximum_headline_words
            < self.minimum_headline_words
        ):
            raise ValueError(
                "Maximum headline words cannot be lower than minimum."
            )

        if self.minimum_body_words < 0:
            raise ValueError(
                "Minimum body words cannot be negative."
            )

        if self.maximum_article_age_days < 1:
            raise ValueError(
                "Maximum article age must be at least one day."
            )


# =============================================================================
# VALIDATION MODELS
# =============================================================================


@dataclass
class ValidationRuleResult:
    """Result produced by one editorial validation rule."""

    rule_id: str
    name: str
    category: RuleCategory
    status: ValidationStatus
    severity: ValidationSeverity
    message: str
    field_name: Optional[str] = None
    observed_value: Any = None
    expected_value: Any = None
    blocking: bool = False

    @property
    def passed(self) -> bool:
        return self.status == ValidationStatus.PASS

    @property
    def failed(self) -> bool:
        return self.status == ValidationStatus.FAIL

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "category": self.category.value,
            "status": self.status.value,
            "severity": self.severity.value,
            "message": self.message,
            "field_name": self.field_name,
            "observed_value": self.observed_value,
            "expected_value": self.expected_value,
            "blocking": self.blocking,
        }


@dataclass
class EditorialValidationResult:
    """Complete editorial validation outcome for one article."""

    article_id: str
    decision: ValidationDecision
    score: float
    confidence: float
    valid: bool
    production_ready: bool

    rules: list[ValidationRuleResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    scorer_decision: Optional[str] = None
    validated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def passed_rules(self) -> list[ValidationRuleResult]:
        return [rule for rule in self.rules if rule.passed]

    @property
    def failed_rules(self) -> list[ValidationRuleResult]:
        return [rule for rule in self.rules if rule.failed]

    @property
    def blocking_failures(self) -> list[ValidationRuleResult]:
        return [
            rule
            for rule in self.failed_rules
            if rule.blocking
        ]

    @property
    def passed_count(self) -> int:
        return len(self.passed_rules)

    @property
    def failed_count(self) -> int:
        return len(self.failed_rules)

    @property
    def blocking_failure_count(self) -> int:
        return len(self.blocking_failures)

    def to_dict(self) -> dict[str, Any]:
        return {
            "article_id": self.article_id,
            "decision": self.decision.value,
            "score": round(self.score, 2),
            "confidence": round(self.confidence, 2),
            "valid": self.valid,
            "production_ready": self.production_ready,
            "scorer_decision": self.scorer_decision,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "blocking_failure_count": self.blocking_failure_count,
            "rules": [rule.to_dict() for rule in self.rules],
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "reasons": list(self.reasons),
            "recommendations": list(self.recommendations),
            "validated_at": self.validated_at.isoformat(),
        }


@dataclass
class ValidationStatistics:
    """Aggregate statistics for a validation batch."""

    articles_validated: int
    accepted: int
    review_required: int
    rejected: int
    production_ready: int
    average_score: float
    average_confidence: float
    total_failed_rules: int
    total_blocking_failures: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# =============================================================================
# ARTICLE ACCESS
# =============================================================================


class ArticleView:
    """Normalized read-only access to article fields."""

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
            "cleaned_text",
            "raw_text",
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
        "author": (
            "author",
            "byline",
            "creator",
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
            "Article must be a mapping, dataclass or object "
            "with accessible attributes."
        )

    def get(self, field_name: str, default: Any = None) -> Any:
        aliases = self.FIELD_ALIASES.get(
            field_name,
            (field_name,),
        )

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

        if isinstance(value, Mapping):
            for key in ("name", "title", "label", "value"):
                nested = value.get(key)

                if nested:
                    return clean_text(str(nested))

        if isinstance(value, (list, tuple, set)):
            return clean_text(
                " ".join(
                    str(item)
                    for item in value
                    if item is not None
                )
            )

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
# HELPERS
# =============================================================================


def clamp(
    value: float,
    minimum: float = MINIMUM_SCORE,
    maximum: float = MAXIMUM_SCORE,
) -> float:
    return max(minimum, min(maximum, value))


def clean_text(value: str) -> str:
    text = value or ""
    text = CONTROL_CHARACTER_PATTERN.sub(" ", text)
    text = HTML_PATTERN.sub(" ", text)
    text = text.replace("\u200b", " ")
    text = text.replace("\xa0", " ")
    text = WHITESPACE_PATTERN.sub(" ", text)
    return text.strip()


def tokenize(value: str) -> list[str]:
    return [
        token.lower()
        for token in WORD_PATTERN.findall(value or "")
        if token.strip()
    ]


def word_count(value: str) -> int:
    return len(tokenize(value))


def parse_datetime(value: Any) -> Optional[datetime]:
    """Parse common publication date values into UTC."""

    if value in (None, ""):
        return None

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        timestamp = float(value)

        if timestamp > 10_000_000_000:
            timestamp /= 1000.0

        try:
            parsed = datetime.fromtimestamp(
                timestamp,
                tz=timezone.utc,
            )
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
            parsed = None

            date_formats = (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%d",
                "%d-%m-%Y %H:%M:%S",
                "%d-%m-%Y",
                "%a, %d %b %Y %H:%M:%S %z",
                "%a, %d %b %Y %H:%M:%S GMT",
                "%d %b %Y %H:%M:%S %z",
            )

            for date_format in date_formats:
                try:
                    parsed = datetime.strptime(
                        text,
                        date_format,
                    )
                    break
                except ValueError:
                    continue

            if parsed is None:
                return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def safe_domain(value: str) -> str:
    raw = (value or "").strip().lower()

    if not raw:
        return ""

    if "://" not in raw:
        raw = f"https://{raw}"

    try:
        parsed = urlparse(raw)
    except ValueError:
        return ""

    domain = parsed.netloc.lower()

    if domain.startswith("www."):
        domain = domain[4:]

    if ":" in domain:
        domain = domain.split(":", 1)[0]

    return domain


def valid_http_url(value: str) -> bool:
    if not value:
        return False

    try:
        parsed = urlparse(value)
    except ValueError:
        return False

    return (
        parsed.scheme.lower() in {"http", "https"}
        and bool(parsed.netloc)
    )


def domain_matches(
    domain: str,
    candidates: Iterable[str],
) -> bool:
    normalized_domain = domain.lower().strip(".")

    for candidate in candidates:
        normalized_candidate = candidate.lower().strip(".")

        if (
            normalized_domain == normalized_candidate
            or normalized_domain.endswith(
                f".{normalized_candidate}"
            )
        ):
            return True

    return False


def normalized_percentage(value: float) -> float:
    if value <= 1.0:
        return clamp(value * 100.0)

    return clamp(value)


def find_pattern_matches(
    value: str,
    patterns: Iterable[re.Pattern[str]],
) -> list[str]:
    matches: list[str] = []

    for pattern in patterns:
        match = pattern.search(value or "")

        if match:
            matches.append(match.group(0))

    return matches


def uppercase_ratio(value: str) -> float:
    letters = [
        character
        for character in value
        if character.isalpha()
    ]

    if not letters:
        return 0.0

    uppercase_letters = sum(
        character.isupper()
        for character in letters
    )

    return uppercase_letters / len(letters)


# =============================================================================
# EDITORIAL VALIDATOR
# =============================================================================


class EditorialValidator:
    """
    BahuvuNewsAI newsroom gatekeeper.

    The validator combines:

    - hard validation rules,
    - editorial policy rules,
    - article scorer output,
    - confidence checks,
    - and production-readiness checks.
    """

    def __init__(
        self,
        config: Optional[EditorialValidationConfig] = None,
        scorer: Optional[Any] = None,
    ) -> None:
        self.config = config or EditorialValidationConfig()

        if scorer is not None:
            self.scorer = scorer
        elif ArticleScorer is not None:
            self.scorer = ArticleScorer()
        else:
            self.scorer = None

    def validate(
        self,
        article: Any,
        *,
        score_result: Optional[Any] = None,
        now: Optional[datetime] = None,
    ) -> EditorialValidationResult:
        """Validate one article and return a complete decision."""

        view = ArticleView(article)
        now_utc = self._normalize_now(now)

        score_data = self._resolve_score_result(
            article=article,
            score_result=score_result,
            now=now_utc,
        )

        rules: list[ValidationRuleResult] = []

        rules.extend(self._metadata_rules(view))
        rules.extend(self._publication_rules(view, now_utc))
        rules.extend(self._language_and_category_rules(view))
        rules.extend(self._source_rules(view, score_data))
        rules.extend(self._quality_rules(view))
        rules.extend(self._duplicate_rules(view))
        rules.extend(self._policy_rules(view))
        rules.extend(self._readiness_rules(view, score_data))

        score = score_data["score"]
        confidence = score_data["confidence"]
        scorer_decision = score_data["decision"]

        decision = self._make_decision(
            rules=rules,
            score=score,
            confidence=confidence,
            scorer_decision=scorer_decision,
        )

        errors = self._collect_errors(rules)
        warnings = self._collect_warnings(rules)
        reasons = self._build_reasons(
            rules=rules,
            score=score,
            confidence=confidence,
            decision=decision,
        )
        recommendations = self._build_recommendations(
            view=view,
            rules=rules,
            decision=decision,
        )

        blocking_failures = [
            rule
            for rule in rules
            if rule.failed and rule.blocking
        ]

        valid = not blocking_failures
        production_ready = (
            decision == ValidationDecision.ACCEPT
            and valid
        )

        return EditorialValidationResult(
            article_id=view.article_id,
            decision=decision,
            score=round(score, 2),
            confidence=round(confidence, 2),
            valid=valid,
            production_ready=production_ready,
            rules=rules,
            errors=errors,
            warnings=warnings,
            reasons=reasons,
            recommendations=recommendations,
            scorer_decision=scorer_decision,
            validated_at=now_utc,
        )

    def validate_many(
        self,
        articles: Iterable[Any],
        *,
        score_results: Optional[
            Mapping[str, Any] | Iterable[Any]
        ] = None,
        now: Optional[datetime] = None,
        sort_by_score: bool = True,
    ) -> list[EditorialValidationResult]:
        """Validate a collection of articles."""

        now_utc = self._normalize_now(now)
        score_lookup = self._prepare_score_lookup(score_results)

        results: list[EditorialValidationResult] = []

        for article in articles:
            view = ArticleView(article)
            score_result = score_lookup.get(view.article_id)

            results.append(
                self.validate(
                    article,
                    score_result=score_result,
                    now=now_utc,
                )
            )

        if sort_by_score:
            decision_order = {
                ValidationDecision.ACCEPT: 3,
                ValidationDecision.REVIEW: 2,
                ValidationDecision.REJECT: 1,
            }

            results.sort(
                key=lambda item: (
                    decision_order[item.decision],
                    item.score,
                    item.confidence,
                ),
                reverse=True,
            )

        return results

    def statistics(
        self,
        results: Iterable[EditorialValidationResult],
    ) -> ValidationStatistics:
        """Calculate validation statistics for a batch."""

        result_list = list(results)

        if not result_list:
            return ValidationStatistics(
                articles_validated=0,
                accepted=0,
                review_required=0,
                rejected=0,
                production_ready=0,
                average_score=0.0,
                average_confidence=0.0,
                total_failed_rules=0,
                total_blocking_failures=0,
            )

        decisions = Counter(
            result.decision
            for result in result_list
        )

        count = len(result_list)

        return ValidationStatistics(
            articles_validated=count,
            accepted=decisions[ValidationDecision.ACCEPT],
            review_required=decisions[
                ValidationDecision.REVIEW
            ],
            rejected=decisions[ValidationDecision.REJECT],
            production_ready=sum(
                result.production_ready
                for result in result_list
            ),
            average_score=round(
                sum(result.score for result in result_list)
                / count,
                2,
            ),
            average_confidence=round(
                sum(
                    result.confidence
                    for result in result_list
                )
                / count,
                2,
            ),
            total_failed_rules=sum(
                result.failed_count
                for result in result_list
            ),
            total_blocking_failures=sum(
                result.blocking_failure_count
                for result in result_list
            ),
        )

    @staticmethod
    def _normalize_now(
        now: Optional[datetime],
    ) -> datetime:
        current = now or datetime.now(timezone.utc)

        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)

        return current.astimezone(timezone.utc)

    # =========================================================================
    # SCORE INTEGRATION
    # =========================================================================

    def _resolve_score_result(
        self,
        *,
        article: Any,
        score_result: Optional[Any],
        now: datetime,
    ) -> dict[str, Any]:
        result = score_result

        if result is None and self.scorer is not None:
            result = self.scorer.score(article, now=now)

        if result is None:
            return {
                "score": 0.0,
                "confidence": 0.0,
                "decision": None,
                "raw": None,
            }

        if isinstance(result, (int, float)):
            score = clamp(float(result))

            return {
                "score": score,
                "confidence": 50.0,
                "decision": None,
                "raw": result,
            }

        if isinstance(result, Mapping):
            score = result.get(
                "final_score",
                result.get("score", 0.0),
            )
            confidence = result.get("confidence", 0.0)
            decision = result.get("decision")

            if isinstance(decision, Enum):
                decision = decision.value

            return {
                "score": clamp(float(score or 0.0)),
                "confidence": clamp(
                    float(confidence or 0.0)
                ),
                "decision": (
                    str(decision).lower()
                    if decision is not None
                    else None
                ),
                "raw": result,
            }

        score = getattr(
            result,
            "final_score",
            getattr(result, "score", 0.0),
        )
        confidence = getattr(result, "confidence", 0.0)
        decision = getattr(result, "decision", None)

        if isinstance(decision, Enum):
            decision = decision.value

        return {
            "score": clamp(float(score or 0.0)),
            "confidence": clamp(
                float(confidence or 0.0)
            ),
            "decision": (
                str(decision).lower()
                if decision is not None
                else None
            ),
            "raw": result,
        }

    @staticmethod
    def _prepare_score_lookup(
        score_results: Optional[
            Mapping[str, Any] | Iterable[Any]
        ],
    ) -> dict[str, Any]:
        if score_results is None:
            return {}

        if isinstance(score_results, Mapping):
            return dict(score_results)

        lookup: dict[str, Any] = {}

        for result in score_results:
            if isinstance(result, Mapping):
                article_id = result.get("article_id")
            else:
                article_id = getattr(
                    result,
                    "article_id",
                    None,
                )

            if article_id:
                lookup[str(article_id)] = result

        return lookup

    # =========================================================================
    # RULE FACTORIES
    # =========================================================================

    @staticmethod
    def _pass(
        *,
        rule_id: str,
        name: str,
        category: RuleCategory,
        message: str,
        field_name: Optional[str] = None,
        observed_value: Any = None,
        expected_value: Any = None,
        severity: ValidationSeverity = ValidationSeverity.INFO,
    ) -> ValidationRuleResult:
        return ValidationRuleResult(
            rule_id=rule_id,
            name=name,
            category=category,
            status=ValidationStatus.PASS,
            severity=severity,
            message=message,
            field_name=field_name,
            observed_value=observed_value,
            expected_value=expected_value,
            blocking=False,
        )

    @staticmethod
    def _fail(
        *,
        rule_id: str,
        name: str,
        category: RuleCategory,
        severity: ValidationSeverity,
        message: str,
        field_name: Optional[str] = None,
        observed_value: Any = None,
        expected_value: Any = None,
        blocking: bool = False,
    ) -> ValidationRuleResult:
        return ValidationRuleResult(
            rule_id=rule_id,
            name=name,
            category=category,
            status=ValidationStatus.FAIL,
            severity=severity,
            message=message,
            field_name=field_name,
            observed_value=observed_value,
            expected_value=expected_value,
            blocking=blocking,
        )

    # =========================================================================
    # METADATA RULES
    # =========================================================================

    def _metadata_rules(
        self,
        view: ArticleView,
    ) -> list[ValidationRuleResult]:
        rules: list[ValidationRuleResult] = []

        required_fields = (
            (
                "title",
                self.config.require_title,
                "Headline",
            ),
            (
                "url",
                self.config.require_url,
                "Article URL",
            ),
            (
                "source",
                self.config.require_source,
                "Source",
            ),
            (
                "category",
                self.config.require_category,
                "Category",
            ),
            (
                "summary",
                self.config.require_summary,
                "Summary",
            ),
            (
                "content",
                self.config.require_body,
                "Article body",
            ),
        )

        for field_name, required, display_name in required_fields:
            value = view.text(field_name)

            if value:
                rules.append(
                    self._pass(
                        rule_id=f"metadata_{field_name}_present",
                        name=f"{display_name} present",
                        category=RuleCategory.METADATA,
                        message=f"{display_name} is available.",
                        field_name=field_name,
                        observed_value=value[:120],
                    )
                )
            elif required:
                rules.append(
                    self._fail(
                        rule_id=f"metadata_{field_name}_required",
                        name=f"{display_name} required",
                        category=RuleCategory.METADATA,
                        severity=ValidationSeverity.CRITICAL,
                        message=f"{display_name} is required but missing.",
                        field_name=field_name,
                        expected_value="non-empty value",
                        blocking=True,
                    )
                )
            else:
                rules.append(
                    self._fail(
                        rule_id=f"metadata_{field_name}_optional_missing",
                        name=f"{display_name} unavailable",
                        category=RuleCategory.METADATA,
                        severity=ValidationSeverity.WARNING,
                        message=f"{display_name} is unavailable.",
                        field_name=field_name,
                        blocking=False,
                    )
                )

        url = view.text("url")

        if url and valid_http_url(url):
            rules.append(
                self._pass(
                    rule_id="metadata_url_valid",
                    name="URL format valid",
                    category=RuleCategory.METADATA,
                    message="Article URL is a valid HTTP or HTTPS URL.",
                    field_name="url",
                    observed_value=url,
                )
            )
        elif url:
            rules.append(
                self._fail(
                    rule_id="metadata_url_invalid",
                    name="URL format invalid",
                    category=RuleCategory.METADATA,
                    severity=ValidationSeverity.ERROR,
                    message="Article URL is malformed.",
                    field_name="url",
                    observed_value=url,
                    expected_value="valid HTTP or HTTPS URL",
                    blocking=self.config.require_url,
                )
            )

        return rules

    # =========================================================================
    # PUBLICATION DATE RULES
    # =========================================================================

    def _publication_rules(
        self,
        view: ArticleView,
        now: datetime,
    ) -> list[ValidationRuleResult]:
        rules: list[ValidationRuleResult] = []

        raw_date = view.get("published_at")
        published_at = parse_datetime(raw_date)

        if published_at is None:
            if self.config.require_publication_date:
                rules.append(
                    self._fail(
                        rule_id="publication_date_required",
                        name="Publication date required",
                        category=RuleCategory.METADATA,
                        severity=ValidationSeverity.CRITICAL,
                        message=(
                            "Publication date is missing or invalid."
                        ),
                        field_name="published_at",
                        observed_value=raw_date,
                        expected_value="valid publication datetime",
                        blocking=True,
                    )
                )
            else:
                rules.append(
                    self._fail(
                        rule_id="publication_date_missing",
                        name="Publication date unavailable",
                        category=RuleCategory.METADATA,
                        severity=ValidationSeverity.WARNING,
                        message=(
                            "Publication date is unavailable."
                        ),
                        field_name="published_at",
                        blocking=False,
                    )
                )

            return rules

        rules.append(
            self._pass(
                rule_id="publication_date_valid",
                name="Publication date valid",
                category=RuleCategory.METADATA,
                message="Publication date was parsed successfully.",
                field_name="published_at",
                observed_value=published_at.isoformat(),
            )
        )

        age_seconds = (now - published_at).total_seconds()
        future_seconds = -age_seconds
        future_limit_seconds = (
            self.config.maximum_future_minutes * 60
        )

        if future_seconds > future_limit_seconds:
            rules.append(
                self._fail(
                    rule_id="publication_date_future",
                    name="Publication date in future",
                    category=RuleCategory.POLICY,
                    severity=ValidationSeverity.CRITICAL,
                    message=(
                        "Publication date is unexpectedly in the future."
                    ),
                    field_name="published_at",
                    observed_value=published_at.isoformat(),
                    expected_value=(
                        f"not more than "
                        f"{self.config.maximum_future_minutes} "
                        "minutes ahead"
                    ),
                    blocking=self.config.reject_future_dates,
                )
            )
            return rules

        age_days = max(age_seconds, 0.0) / 86400.0

        if age_days > self.config.maximum_article_age_days:
            rules.append(
                self._fail(
                    rule_id="publication_article_stale",
                    name="Article too old",
                    category=RuleCategory.EDITORIAL,
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"Article is {age_days:.1f} days old, "
                        "which exceeds the permitted age."
                    ),
                    field_name="published_at",
                    observed_value=round(age_days, 2),
                    expected_value=(
                        f"not older than "
                        f"{self.config.maximum_article_age_days} days"
                    ),
                    blocking=True,
                )
            )
        else:
            rules.append(
                self._pass(
                    rule_id="publication_article_current",
                    name="Article sufficiently current",
                    category=RuleCategory.EDITORIAL,
                    message=(
                        f"Article age is approximately "
                        f"{age_days:.1f} days."
                    ),
                    field_name="published_at",
                    observed_value=round(age_days, 2),
                )
            )

        return rules

    # =========================================================================
    # LANGUAGE AND CATEGORY RULES
    # =========================================================================

    def _language_and_category_rules(
        self,
        view: ArticleView,
    ) -> list[ValidationRuleResult]:
        rules: list[ValidationRuleResult] = []

        language = view.text("language").lower()

        if not language:
            rules.append(
                self._fail(
                    rule_id="language_unknown",
                    name="Language unavailable",
                    category=RuleCategory.EDITORIAL,
                    severity=ValidationSeverity.WARNING,
                    message=(
                        "Article language is not explicitly identified."
                    ),
                    field_name="language",
                    blocking=False,
                )
            )
        elif language in {
            item.lower()
            for item in self.config.allowed_languages
        }:
            rules.append(
                self._pass(
                    rule_id="language_allowed",
                    name="Language allowed",
                    category=RuleCategory.EDITORIAL,
                    message=f"Article language is allowed: {language}.",
                    field_name="language",
                    observed_value=language,
                )
            )
        else:
            rules.append(
                self._fail(
                    rule_id="language_unsupported",
                    name="Language unsupported",
                    category=RuleCategory.EDITORIAL,
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"Article language is not currently supported: "
                        f"{language}."
                    ),
                    field_name="language",
                    observed_value=language,
                    expected_value=list(
                        self.config.allowed_languages
                    ),
                    blocking=False,
                )
            )

        category = view.text("category").lower()

        if category in {
            item.lower()
            for item in self.config.blocked_categories
        }:
            rules.append(
                self._fail(
                    rule_id="category_blocked",
                    name="Category blocked",
                    category=RuleCategory.POLICY,
                    severity=ValidationSeverity.CRITICAL,
                    message=(
                        f"Article category is blocked: {category}."
                    ),
                    field_name="category",
                    observed_value=category,
                    blocking=self.config.reject_blocked_categories,
                )
            )
        elif category and category in {
            item.lower()
            for item in self.config.allowed_categories
        }:
            rules.append(
                self._pass(
                    rule_id="category_allowed",
                    name="Category allowed",
                    category=RuleCategory.EDITORIAL,
                    message=f"Article category is allowed: {category}.",
                    field_name="category",
                    observed_value=category,
                )
            )
        elif category:
            rules.append(
                self._fail(
                    rule_id="category_unknown",
                    name="Category unrecognized",
                    category=RuleCategory.EDITORIAL,
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"Article category is not in the configured "
                        f"category list: {category}."
                    ),
                    field_name="category",
                    observed_value=category,
                    blocking=False,
                )
            )

        return rules

    # =========================================================================
    # SOURCE RULES
    # =========================================================================

    def _source_rules(
        self,
        view: ArticleView,
        score_data: Mapping[str, Any],
    ) -> list[ValidationRuleResult]:
        rules: list[ValidationRuleResult] = []

        domain = view.text("source_domain")

        if not domain:
            domain = safe_domain(view.text("url"))

        if domain and domain_matches(
            domain,
            self.config.blocked_domains,
        ):
            rules.append(
                self._fail(
                    rule_id="source_domain_blocked",
                    name="Source domain blocked",
                    category=RuleCategory.POLICY,
                    severity=ValidationSeverity.CRITICAL,
                    message=f"Source domain is blocked: {domain}.",
                    field_name="source_domain",
                    observed_value=domain,
                    blocking=self.config.reject_blocked_domains,
                )
            )
        elif domain and domain_matches(
            domain,
            self.config.trusted_domains,
        ):
            rules.append(
                self._pass(
                    rule_id="source_domain_trusted",
                    name="Source domain trusted",
                    category=RuleCategory.EDITORIAL,
                    message=f"Source domain is trusted: {domain}.",
                    field_name="source_domain",
                    observed_value=domain,
                )
            )
        elif domain:
            rules.append(
                self._fail(
                    rule_id="source_domain_unverified",
                    name="Source domain unverified",
                    category=RuleCategory.EDITORIAL,
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"Source domain is not in the trusted list: "
                        f"{domain}."
                    ),
                    field_name="source_domain",
                    observed_value=domain,
                    blocking=False,
                )
            )

        source_score = view.number("source_score")

        raw_score_result = score_data.get("raw")

        if source_score is None and raw_score_result is not None:
            components = getattr(
                raw_score_result,
                "components",
                None,
            )

            if isinstance(components, Mapping):
                source_component = components.get(
                    "source_credibility"
                )

                if source_component is not None:
                    source_score = getattr(
                        source_component,
                        "raw_score",
                        None,
                    )

                    if source_score is None and isinstance(
                        source_component,
                        Mapping,
                    ):
                        source_score = source_component.get(
                            "raw_score"
                        )

        if source_score is not None:
            source_score = normalized_percentage(source_score)

            if source_score < self.config.minimum_source_score:
                rules.append(
                    self._fail(
                        rule_id="source_score_low",
                        name="Source credibility low",
                        category=RuleCategory.EDITORIAL,
                        severity=ValidationSeverity.ERROR,
                        message=(
                            f"Source credibility score is "
                            f"{source_score:.1f}, below the minimum."
                        ),
                        field_name="source_score",
                        observed_value=round(source_score, 2),
                        expected_value=(
                            f">= "
                            f"{self.config.minimum_source_score}"
                        ),
                        blocking=False,
                    )
                )
            else:
                rules.append(
                    self._pass(
                        rule_id="source_score_acceptable",
                        name="Source credibility acceptable",
                        category=RuleCategory.EDITORIAL,
                        message=(
                            f"Source credibility score is "
                            f"{source_score:.1f}."
                        ),
                        field_name="source_score",
                        observed_value=round(source_score, 2),
                    )
                )

        return rules

    # =========================================================================
    # QUALITY RULES
    # =========================================================================

    def _quality_rules(
        self,
        view: ArticleView,
    ) -> list[ValidationRuleResult]:
        rules: list[ValidationRuleResult] = []

        title = view.text("title")
        summary = view.text("summary")
        content = view.text("content")

        title_words = word_count(title)

        if title:
            if (
                title_words
                < self.config.minimum_headline_words
            ):
                rules.append(
                    self._fail(
                        rule_id="headline_too_short",
                        name="Headline too short",
                        category=RuleCategory.QUALITY,
                        severity=ValidationSeverity.ERROR,
                        message=(
                            f"Headline contains only "
                            f"{title_words} words."
                        ),
                        field_name="title",
                        observed_value=title_words,
                        expected_value=(
                            f">= "
                            f"{self.config.minimum_headline_words}"
                        ),
                        blocking=False,
                    )
                )
            elif (
                title_words
                > self.config.maximum_headline_words
            ):
                rules.append(
                    self._fail(
                        rule_id="headline_too_long",
                        name="Headline too long",
                        category=RuleCategory.QUALITY,
                        severity=ValidationSeverity.WARNING,
                        message=(
                            f"Headline contains "
                            f"{title_words} words."
                        ),
                        field_name="title",
                        observed_value=title_words,
                        expected_value=(
                            f"<= "
                            f"{self.config.maximum_headline_words}"
                        ),
                        blocking=False,
                    )
                )
            else:
                rules.append(
                    self._pass(
                        rule_id="headline_length_valid",
                        name="Headline length valid",
                        category=RuleCategory.QUALITY,
                        message=(
                            f"Headline contains "
                            f"{title_words} words."
                        ),
                        field_name="title",
                        observed_value=title_words,
                    )
                )

            clickbait_matches = find_pattern_matches(
                title,
                CLICKBAIT_PATTERNS,
            )

            if clickbait_matches:
                rules.append(
                    self._fail(
                        rule_id="headline_clickbait",
                        name="Clickbait headline detected",
                        category=RuleCategory.QUALITY,
                        severity=ValidationSeverity.WARNING,
                        message=(
                            "Headline contains clickbait language: "
                            + ", ".join(clickbait_matches)
                            + "."
                        ),
                        field_name="title",
                        observed_value=clickbait_matches,
                        blocking=False,
                    )
                )
            else:
                rules.append(
                    self._pass(
                        rule_id="headline_neutral",
                        name="Headline language neutral",
                        category=RuleCategory.QUALITY,
                        message=(
                            "No configured clickbait language "
                            "was detected."
                        ),
                        field_name="title",
                    )
                )

            if uppercase_ratio(title) > 0.80 and len(title) > 12:
                rules.append(
                    self._fail(
                        rule_id="headline_excessive_caps",
                        name="Headline uses excessive capitals",
                        category=RuleCategory.QUALITY,
                        severity=ValidationSeverity.WARNING,
                        message=(
                            "Headline contains excessive uppercase "
                            "lettering."
                        ),
                        field_name="title",
                        blocking=False,
                    )
                )

        summary_words = word_count(summary)

        if summary:
            if (
                summary_words
                < self.config.minimum_summary_words
            ):
                rules.append(
                    self._fail(
                        rule_id="summary_too_short",
                        name="Summary too short",
                        category=RuleCategory.QUALITY,
                        severity=ValidationSeverity.WARNING,
                        message=(
                            f"Summary contains only "
                            f"{summary_words} words."
                        ),
                        field_name="summary",
                        observed_value=summary_words,
                        expected_value=(
                            f">= "
                            f"{self.config.minimum_summary_words}"
                        ),
                        blocking=False,
                    )
                )
            else:
                rules.append(
                    self._pass(
                        rule_id="summary_length_valid",
                        name="Summary length valid",
                        category=RuleCategory.QUALITY,
                        message=(
                            f"Summary contains "
                            f"{summary_words} words."
                        ),
                        field_name="summary",
                        observed_value=summary_words,
                    )
                )

        body_words = word_count(content)

        if content:
            if body_words < self.config.minimum_body_words:
                rules.append(
                    self._fail(
                        rule_id="body_too_short",
                        name="Article body too short",
                        category=RuleCategory.QUALITY,
                        severity=ValidationSeverity.ERROR,
                        message=(
                            f"Article body contains only "
                            f"{body_words} words."
                        ),
                        field_name="content",
                        observed_value=body_words,
                        expected_value=(
                            f">= "
                            f"{self.config.minimum_body_words}"
                        ),
                        blocking=False,
                    )
                )
            elif (
                body_words
                < self.config.preferred_body_words
            ):
                rules.append(
                    self._fail(
                        rule_id="body_below_preferred_length",
                        name="Article body below preferred length",
                        category=RuleCategory.QUALITY,
                        severity=ValidationSeverity.WARNING,
                        message=(
                            f"Article body contains "
                            f"{body_words} words."
                        ),
                        field_name="content",
                        observed_value=body_words,
                        expected_value=(
                            f">= "
                            f"{self.config.preferred_body_words}"
                        ),
                        blocking=False,
                    )
                )
            else:
                rules.append(
                    self._pass(
                        rule_id="body_length_valid",
                        name="Article body sufficiently detailed",
                        category=RuleCategory.QUALITY,
                        message=(
                            f"Article body contains "
                            f"{body_words} words."
                        ),
                        field_name="content",
                        observed_value=body_words,
                    )
                )

        return rules

    # =========================================================================
    # DUPLICATE RULES
    # =========================================================================

    def _duplicate_rules(
        self,
        view: ArticleView,
    ) -> list[ValidationRuleResult]:
        rules: list[ValidationRuleResult] = []

        if view.boolean("duplicate"):
            rules.append(
                self._fail(
                    rule_id="duplicate_confirmed",
                    name="Confirmed duplicate",
                    category=RuleCategory.DUPLICATE,
                    severity=ValidationSeverity.CRITICAL,
                    message=(
                        "Article is explicitly marked as a duplicate."
                    ),
                    field_name="duplicate",
                    observed_value=True,
                    blocking=self.config.reject_confirmed_duplicates,
                )
            )
            return rules

        duplicate_score = view.number("duplicate_score")

        if duplicate_score is None:
            rules.append(
                self._pass(
                    rule_id="duplicate_not_confirmed",
                    name="No duplicate flag",
                    category=RuleCategory.DUPLICATE,
                    message=(
                        "Article is not marked as a duplicate."
                    ),
                    field_name="duplicate",
                    observed_value=False,
                )
            )
            return rules

        duplicate_score = normalized_percentage(
            duplicate_score
        )

        if (
            duplicate_score
            >= self.config.duplicate_similarity_reject_threshold
        ):
            rules.append(
                self._fail(
                    rule_id="duplicate_similarity_reject",
                    name="Duplicate similarity extremely high",
                    category=RuleCategory.DUPLICATE,
                    severity=ValidationSeverity.CRITICAL,
                    message=(
                        f"Duplicate similarity is "
                        f"{duplicate_score:.1f}%."
                    ),
                    field_name="duplicate_score",
                    observed_value=round(
                        duplicate_score,
                        2,
                    ),
                    expected_value=(
                        f"< "
                        f"{self.config.duplicate_similarity_reject_threshold}"
                    ),
                    blocking=True,
                )
            )
        elif (
            duplicate_score
            >= self.config.duplicate_similarity_review_threshold
        ):
            rules.append(
                self._fail(
                    rule_id="duplicate_similarity_review",
                    name="Duplicate similarity elevated",
                    category=RuleCategory.DUPLICATE,
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"Duplicate similarity is "
                        f"{duplicate_score:.1f}%."
                    ),
                    field_name="duplicate_score",
                    observed_value=round(
                        duplicate_score,
                        2,
                    ),
                    expected_value=(
                        f"< "
                        f"{self.config.duplicate_similarity_review_threshold}"
                    ),
                    blocking=False,
                )
            )
        else:
            rules.append(
                self._pass(
                    rule_id="duplicate_similarity_acceptable",
                    name="Duplicate similarity acceptable",
                    category=RuleCategory.DUPLICATE,
                    message=(
                        f"Duplicate similarity is "
                        f"{duplicate_score:.1f}%."
                    ),
                    field_name="duplicate_score",
                    observed_value=round(
                        duplicate_score,
                        2,
                    ),
                )
            )

        return rules

    # =========================================================================
    # POLICY RULES
    # =========================================================================

    def _policy_rules(
        self,
        view: ArticleView,
    ) -> list[ValidationRuleResult]:
        rules: list[ValidationRuleResult] = []

        title = view.text("title")
        summary = view.text("summary")
        content = view.text("content")

        combined = f"{title} {summary} {content[:5000]}"

        suspicious_matches = find_pattern_matches(
            combined,
            SUSPICIOUS_PATTERNS,
        )

        if suspicious_matches:
            rules.append(
                self._fail(
                    rule_id="policy_suspicious_content",
                    name="Suspicious content detected",
                    category=RuleCategory.POLICY,
                    severity=ValidationSeverity.CRITICAL,
                    message=(
                        "Suspicious or spam-like language detected: "
                        + ", ".join(suspicious_matches)
                        + "."
                    ),
                    observed_value=suspicious_matches,
                    blocking=self.config.reject_suspicious_content,
                )
            )
        else:
            rules.append(
                self._pass(
                    rule_id="policy_content_clean",
                    name="No suspicious content detected",
                    category=RuleCategory.POLICY,
                    message=(
                        "No configured suspicious-content "
                        "patterns were detected."
                    ),
                )
            )

        return rules

    # =========================================================================
    # READINESS RULES
    # =========================================================================

    def _readiness_rules(
        self,
        view: ArticleView,
        score_data: Mapping[str, Any],
    ) -> list[ValidationRuleResult]:
        rules: list[ValidationRuleResult] = []

        score = float(score_data["score"])
        confidence = float(score_data["confidence"])

        if score >= self.config.accept_score:
            rules.append(
                self._pass(
                    rule_id="readiness_score_accept",
                    name="Editorial score meets acceptance threshold",
                    category=RuleCategory.READINESS,
                    message=(
                        f"Article score is {score:.1f}, meeting "
                        "the acceptance threshold."
                    ),
                    observed_value=round(score, 2),
                    expected_value=(
                        f">= {self.config.accept_score}"
                    ),
                )
            )
        elif score >= self.config.review_score:
            rules.append(
                self._fail(
                    rule_id="readiness_score_review",
                    name="Editorial score requires review",
                    category=RuleCategory.READINESS,
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"Article score is {score:.1f}, which "
                        "requires editorial review."
                    ),
                    observed_value=round(score, 2),
                    expected_value=(
                        f">= {self.config.accept_score} for acceptance"
                    ),
                    blocking=False,
                )
            )
        else:
            rules.append(
                self._fail(
                    rule_id="readiness_score_reject",
                    name="Editorial score below minimum",
                    category=RuleCategory.READINESS,
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"Article score is {score:.1f}, below "
                        "the review threshold."
                    ),
                    observed_value=round(score, 2),
                    expected_value=(
                        f">= {self.config.review_score}"
                    ),
                    blocking=True,
                )
            )

        if (
            confidence
            >= self.config.minimum_confidence_for_acceptance
        ):
            rules.append(
                self._pass(
                    rule_id="readiness_confidence_sufficient",
                    name="Scoring confidence sufficient",
                    category=RuleCategory.READINESS,
                    message=(
                        f"Scoring confidence is "
                        f"{confidence:.1f}%."
                    ),
                    observed_value=round(confidence, 2),
                )
            )
        else:
            rules.append(
                self._fail(
                    rule_id="readiness_confidence_low",
                    name="Scoring confidence insufficient",
                    category=RuleCategory.READINESS,
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"Scoring confidence is only "
                        f"{confidence:.1f}%."
                    ),
                    observed_value=round(confidence, 2),
                    expected_value=(
                        f">= "
                        f"{self.config.minimum_confidence_for_acceptance}"
                    ),
                    blocking=False,
                )
            )

        image_url = view.text("image_url")

        if image_url:
            rules.append(
                self._pass(
                    rule_id="readiness_image_available",
                    name="Lead image available",
                    category=RuleCategory.READINESS,
                    message=(
                        "Article includes lead-image metadata."
                    ),
                    field_name="image_url",
                    observed_value=image_url,
                )
            )
        else:
            rules.append(
                self._fail(
                    rule_id="readiness_image_missing",
                    name="Lead image unavailable",
                    category=RuleCategory.READINESS,
                    severity=ValidationSeverity.WARNING,
                    message=(
                        "Article does not include a lead image."
                    ),
                    field_name="image_url",
                    blocking=(
                        self.config.require_image_for_acceptance
                    ),
                )
            )

        return rules

    # =========================================================================
    # DECISION ENGINE
    # =========================================================================

    def _make_decision(
        self,
        *,
        rules: list[ValidationRuleResult],
        score: float,
        confidence: float,
        scorer_decision: Optional[str],
    ) -> ValidationDecision:
        blocking_failures = [
            rule
            for rule in rules
            if rule.failed and rule.blocking
        ]

        critical_failures = [
            rule
            for rule in rules
            if (
                rule.failed
                and rule.severity
                == ValidationSeverity.CRITICAL
            )
        ]

        if blocking_failures:
            return ValidationDecision.REJECT

        if (
            scorer_decision
            and scorer_decision.lower() == "reject"
        ):
            return ValidationDecision.REJECT

        if score < self.config.review_score:
            return ValidationDecision.REJECT

        warning_or_error_failures = [
            rule
            for rule in rules
            if (
                rule.failed
                and rule.severity
                in {
                    ValidationSeverity.WARNING,
                    ValidationSeverity.ERROR,
                }
            )
        ]

        review_rule_ids = {
            "language_unknown",
            "language_unsupported",
            "category_unknown",
            "source_domain_unverified",
            "headline_clickbait",
            "body_too_short",
            "body_below_preferred_length",
            "duplicate_similarity_review",
            "readiness_image_missing",
            "readiness_score_review",
            "readiness_confidence_low",
        }

        review_failures = [
            rule
            for rule in warning_or_error_failures
            if rule.rule_id in review_rule_ids
        ]

        if critical_failures:
            return ValidationDecision.REVIEW

        if score < self.config.accept_score:
            return ValidationDecision.REVIEW

        if (
            confidence
            < self.config.minimum_confidence_for_acceptance
        ):
            return ValidationDecision.REVIEW

        if review_failures:
            mandatory_review = False

            for rule in review_failures:
                if (
                    rule.rule_id == "language_unknown"
                    and self.config.review_unknown_language
                ):
                    mandatory_review = True
                elif (
                    rule.rule_id == "category_unknown"
                    and self.config.review_unknown_category
                ):
                    mandatory_review = True
                elif (
                    rule.rule_id == "source_domain_unverified"
                    and self.config.review_untrusted_source
                ):
                    mandatory_review = True
                elif (
                    rule.rule_id == "headline_clickbait"
                    and self.config.review_clickbait
                ):
                    mandatory_review = True
                elif (
                    rule.rule_id == "readiness_image_missing"
                    and self.config.review_missing_image
                ):
                    mandatory_review = True
                elif rule.rule_id in {
                    "duplicate_similarity_review",
                    "body_too_short",
                }:
                    mandatory_review = True

            if mandatory_review:
                return ValidationDecision.REVIEW

        return ValidationDecision.ACCEPT

    # =========================================================================
    # RESULT BUILDERS
    # =========================================================================

    @staticmethod
    def _collect_errors(
        rules: Iterable[ValidationRuleResult],
    ) -> list[str]:
        return [
            rule.message
            for rule in rules
            if (
                rule.failed
                and rule.severity
                in {
                    ValidationSeverity.ERROR,
                    ValidationSeverity.CRITICAL,
                }
            )
        ]

    @staticmethod
    def _collect_warnings(
        rules: Iterable[ValidationRuleResult],
    ) -> list[str]:
        return [
            rule.message
            for rule in rules
            if (
                rule.failed
                and rule.severity
                == ValidationSeverity.WARNING
            )
        ]

    @staticmethod
    def _build_reasons(
        *,
        rules: list[ValidationRuleResult],
        score: float,
        confidence: float,
        decision: ValidationDecision,
    ) -> list[str]:
        reasons = [
            (
                f"Final editorial decision: "
                f"{decision.value.upper()}."
            ),
            (
                f"Article score: {score:.1f}/100; "
                f"confidence: {confidence:.1f}%."
            ),
        ]

        blocking = [
            rule
            for rule in rules
            if rule.failed and rule.blocking
        ]

        if blocking:
            reasons.extend(
                rule.message
                for rule in blocking[:4]
            )
        else:
            failed = [
                rule
                for rule in rules
                if rule.failed
            ]

            reasons.extend(
                rule.message
                for rule in failed[:4]
            )

        return reasons[:8]

    @staticmethod
    def _build_recommendations(
        *,
        view: ArticleView,
        rules: list[ValidationRuleResult],
        decision: ValidationDecision,
    ) -> list[str]:
        recommendations: list[str] = []

        if decision == ValidationDecision.ACCEPT:
            recommendations.append(
                "Proceed to script generation and downstream production."
            )
        elif decision == ValidationDecision.REVIEW:
            recommendations.append(
                "Send the article to a human editor before production."
            )
        else:
            recommendations.append(
                "Do not send this article into the production pipeline."
            )

        failed_rule_ids = {
            rule.rule_id
            for rule in rules
            if rule.failed
        }

        if failed_rule_ids.intersection(
            {
                "source_domain_unverified",
                "source_score_low",
            }
        ):
            recommendations.append(
                "Verify the report with an additional trusted source."
            )

        if failed_rule_ids.intersection(
            {
                "headline_too_short",
                "headline_too_long",
                "headline_clickbait",
                "headline_excessive_caps",
            }
        ):
            recommendations.append(
                "Rewrite the headline for clarity, neutrality and accuracy."
            )

        if failed_rule_ids.intersection(
            {
                "body_too_short",
                "body_below_preferred_length",
                "metadata_content_required",
            }
        ):
            recommendations.append(
                "Collect a fuller article body before publication."
            )

        if failed_rule_ids.intersection(
            {
                "duplicate_confirmed",
                "duplicate_similarity_reject",
                "duplicate_similarity_review",
            }
        ):
            recommendations.append(
                "Use the primary article from the duplicate cluster."
            )

        if "readiness_image_missing" in failed_rule_ids:
            recommendations.append(
                "Find a licensed and editorially relevant lead image."
            )

        if "publication_article_stale" in failed_rule_ids:
            recommendations.append(
                "Confirm whether a newer version of the story is available."
            )

        if not view.text("author"):
            recommendations.append(
                "Capture the author or byline when available."
            )

        return recommendations[:6]


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def validate_article(
    article: Any,
    *,
    config: Optional[EditorialValidationConfig] = None,
    score_result: Optional[Any] = None,
    now: Optional[datetime] = None,
) -> EditorialValidationResult:
    """Validate one article using a temporary validator."""

    validator = EditorialValidator(config=config)

    return validator.validate(
        article,
        score_result=score_result,
        now=now,
    )


def validate_articles(
    articles: Iterable[Any],
    *,
    config: Optional[EditorialValidationConfig] = None,
    score_results: Optional[
        Mapping[str, Any] | Iterable[Any]
    ] = None,
    now: Optional[datetime] = None,
    sort_by_score: bool = True,
) -> list[EditorialValidationResult]:
    """Validate multiple articles using a temporary validator."""

    validator = EditorialValidator(config=config)

    return validator.validate_many(
        articles,
        score_results=score_results,
        now=now,
        sort_by_score=sort_by_score,
    )


# =============================================================================
# SELF-TEST
# =============================================================================


def _make_test_articles(
    now: datetime,
) -> list[dict[str, Any]]:
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
            "id": "article_accept",
            "title": (
                "Heavy Rain Alert Issued Across Andhra Pradesh "
                "as Officials Deploy Emergency Teams"
            ),
            "summary": (
                "Authorities placed several districts on alert as "
                "heavy rainfall continued across Andhra Pradesh."
            ),
            "content": strong_content,
            "url": (
                "https://www.thehindu.com/news/national/"
                "andhra-pradesh/weather-alert"
            ),
            "source": "The Hindu",
            "published_at": now.isoformat(),
            "category": "weather",
            "language": "English",
            "location": "Andhra Pradesh, India",
            "image_url": (
                "https://images.example.org/rain-alert.jpg"
            ),
            "author": "Staff Reporter",
            "duplicate": False,
            "duplicate_score": 0.10,
        },
        {
            "id": "article_review",
            "title": (
                "Technology Companies Announce New AI Services"
            ),
            "summary": (
                "Several companies introduced artificial intelligence "
                "services for business users."
            ),
            "content": (
                "Technology companies announced new services during an "
                "industry event. More details are expected from official "
                "sources and company representatives."
            ),
            "url": (
                "https://regionalnews.example.net/"
                "technology/ai-services"
            ),
            "source": "Regional News Network",
            "published_at": now.isoformat(),
            "category": "technology",
            "language": "English",
            "location": "India",
            "duplicate": False,
        },
        {
            "id": "article_reject",
            "title": (
                "SHOCKING!!! YOU WON'T BELIEVE THIS VIRAL NEWS"
            ),
            "summary": (
                "Share immediately. This is 100% confirmed."
            ),
            "content": "",
            "url": "https://example.com/viral/story",
            "source": "Unknown Viral Page",
            "published_at": "2024-01-01T00:00:00+00:00",
            "category": "spam",
            "language": "English",
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

    validator = EditorialValidator()
    articles = _make_test_articles(fixed_now)

    results = validator.validate_many(
        articles,
        now=fixed_now,
    )

    result_by_id = {
        result.article_id: result
        for result in results
    }

    accepted = result_by_id["article_accept"]
    review = result_by_id["article_review"]
    rejected = result_by_id["article_reject"]

    assert accepted.decision == ValidationDecision.ACCEPT
    assert accepted.production_ready is True
    assert accepted.valid is True

    assert review.decision == ValidationDecision.REVIEW
    assert review.production_ready is False

    assert rejected.decision == ValidationDecision.REJECT
    assert rejected.production_ready is False
    assert rejected.valid is False
    assert rejected.blocking_failure_count >= 1

    rejected_rule_ids = {
        rule.rule_id
        for rule in rejected.failed_rules
    }

    assert "duplicate_confirmed" in rejected_rule_ids
    assert "category_blocked" in rejected_rule_ids
    assert "source_domain_blocked" in rejected_rule_ids

    serialized = accepted.to_dict()

    assert serialized["article_id"] == "article_accept"
    assert serialized["decision"] == "accept"
    assert serialized["production_ready"] is True
    assert isinstance(serialized["rules"], list)

    statistics = validator.statistics(results)

    assert statistics.articles_validated == 3
    assert statistics.accepted == 1
    assert statistics.review_required == 1
    assert statistics.rejected == 1
    assert statistics.production_ready == 1

    print("Editorial validator initialized successfully.")
    print(
        f"Articles validated: "
        f"{statistics.articles_validated}"
    )
    print(f"Accepted: {statistics.accepted}")
    print(
        f"Review required: "
        f"{statistics.review_required}"
    )
    print(f"Rejected: {statistics.rejected}")
    print(
        f"Production ready: "
        f"{statistics.production_ready}"
    )
    print(
        f"Average score: "
        f"{statistics.average_score:.2f}"
    )
    print(
        f"Failed rules: "
        f"{statistics.total_failed_rules}"
    )
    print(
        f"Blocking failures: "
        f"{statistics.total_blocking_failures}"
    )
    print()

    for result in results:
        print(
            f"{result.article_id}: "
            f"score={result.score:.2f}, "
            f"confidence={result.confidence:.2f}, "
            f"decision={result.decision.value}, "
            f"valid={result.valid}, "
            f"production_ready={result.production_ready}, "
            f"failed_rules={result.failed_count}"
        )

    print("Editorial validator self-test passed.")


if __name__ == "__main__":
    _run_self_test()