# news/story_ranker.py

"""
BahuvuNewsAI - Editorial Story Ranker
=====================================

Ranks editorially validated NewsArticle objects and selects the strongest
stories for bulletin production.

Pipeline position
-----------------
Article Scorer
    ↓
Editorial Validator
    ↓
Story Ranker
    ↓
Script Generator

Responsibilities
----------------
1. Accept validated NewsArticle objects.
2. Exclude rejected, duplicate, failed, or unusable stories.
3. Calculate a final ranking score from canonical article score fields.
4. Apply editorial bonuses and penalties.
5. Promote category diversity.
6. Select bulletin stories.
7. Mark selected stories with ArticleStatus.SELECTED.
8. Return ranking statistics and selection reasons.
9. Provide a deterministic self-test.

This module does not:
- collect news,
- deduplicate articles,
- validate factual accuracy,
- generate scripts,
- translate content,
- generate voice or video.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

try:
    from news.models import (
        ArticleStatus,
        LanguageCode,
        NewsArticle,
        NewsCategory,
    )
except ImportError as exc:
    raise ImportError(
        "Unable to import news models. Run from the project root with: "
        "python -m news.story_ranker"
    ) from exc


MODULE_NAME = "BahuvuNewsAI Editorial Story Ranker"
MODULE_VERSION = "1.0.0"

DEFAULT_MAX_STORIES = 12
DEFAULT_MINIMUM_SCORE = 50.0
DEFAULT_MAX_PER_CATEGORY = 3
DEFAULT_CATEGORY_DIVERSITY_BONUS = 4.0
DEFAULT_RECENCY_BONUS = 3.0
DEFAULT_BREAKING_BONUS = 5.0
DEFAULT_LOW_CONFIDENCE_PENALTY = 8.0
DEFAULT_DUPLICATE_PENALTY = 100.0


class RankingDecision(str, Enum):
    """Final ranking decision for an article."""

    SELECT = "select"
    RESERVE = "reserve"
    REJECT = "reject"


class RankingBand(str, Enum):
    """Human-readable ranking strength."""

    LEAD = "lead"
    STRONG = "strong"
    USABLE = "usable"
    WEAK = "weak"
    REJECTED = "rejected"


@dataclass(slots=True)
class StoryRankerConfig:
    """Configuration for ranking and bulletin selection."""

    max_stories: int = DEFAULT_MAX_STORIES
    minimum_score: float = DEFAULT_MINIMUM_SCORE
    max_per_category: int = DEFAULT_MAX_PER_CATEGORY
    max_per_source: int = 3

    # Editorial slot order used to build a balanced television bulletin.
    # Each inner tuple represents interchangeable preferred categories.
    editorial_slots: tuple[tuple[str, ...], ...] = (
        ("national", "politics", "governance", "law"),
        ("state", "local", "andhra_pradesh", "telangana"),
        ("international", "world"),
        ("business", "economy", "agriculture"),
        ("technology", "science", "education", "health"),
        ("sports",),
        ("weather", "disaster", "environment"),
        ("culture", "entertainment"),
    )

    category_diversity_bonus: float = DEFAULT_CATEGORY_DIVERSITY_BONUS
    recency_bonus: float = DEFAULT_RECENCY_BONUS
    breaking_bonus: float = DEFAULT_BREAKING_BONUS
    low_confidence_penalty: float = DEFAULT_LOW_CONFIDENCE_PENALTY
    duplicate_penalty: float = DEFAULT_DUPLICATE_PENALTY

    minimum_confidence: float = 50.0
    prefer_english_source: bool = True
    require_validated_status: bool = False

    def validate(self) -> None:
        if self.max_stories < 1:
            raise ValueError("max_stories must be at least 1.")

        if self.minimum_score < 0:
            raise ValueError("minimum_score cannot be negative.")

        if self.max_per_category < 1:
            raise ValueError("max_per_category must be at least 1.")

        if self.max_per_source < 1:
            raise ValueError("max_per_source must be at least 1.")

        if not self.editorial_slots:
            raise ValueError("editorial_slots cannot be empty.")

        for slot in self.editorial_slots:
            if not slot:
                raise ValueError(
                    "Every editorial slot must contain a category."
                )

        if self.minimum_confidence < 0:
            raise ValueError("minimum_confidence cannot be negative.")


@dataclass(slots=True)
class RankedStory:
    """Ranking result for one story."""

    article: NewsArticle
    article_id: str
    title: str
    category: str
    source_name: str

    base_score: float
    final_score: float
    confidence: float

    rank: int = 0
    decision: RankingDecision = RankingDecision.RESERVE
    band: RankingBand = RankingBand.USABLE

    bonuses: dict[str, float] = field(default_factory=dict)
    penalties: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    selected: bool = False


@dataclass(slots=True)
class StoryRankingStatistics:
    """Summary statistics for a ranking run."""

    input_articles: int = 0
    eligible_articles: int = 0
    ranked_articles: int = 0
    selected_articles: int = 0
    reserve_articles: int = 0
    rejected_articles: int = 0

    highest_score: float = 0.0
    lowest_score: float = 0.0
    average_score: float = 0.0

    category_counts: dict[str, int] = field(default_factory=dict)
    selected_category_counts: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class StoryRankingResult:
    """Complete ranker output."""

    ranked_stories: list[RankedStory]
    selected_stories: list[NewsArticle]
    reserve_stories: list[NewsArticle]
    rejected_stories: list[NewsArticle]
    statistics: StoryRankingStatistics
    generated_at: str
    module_version: str = MODULE_VERSION


def utc_now() -> datetime:
    """Return the current timezone-aware UTC time."""

    return datetime.now(timezone.utc)


def enum_value(value: Any) -> str:
    """Return enum value or normalized string."""

    if isinstance(value, Enum):
        return str(value.value)

    if value is None:
        return ""

    return str(value)


def normalize_text(value: Any) -> str:
    """Normalize text safely."""

    if value is None:
        return ""

    return " ".join(str(value).split()).strip()


def safe_float(value: Any, default: float = 0.0) -> float:
    """Convert a value to float safely."""

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def article_id(article: NewsArticle | Mapping[str, Any]) -> str:
    """Return the canonical article identifier."""

    if isinstance(article, Mapping):
        return normalize_text(
            article.get("article_id")
            or article.get("id")
            or ""
        )

    return normalize_text(
        getattr(article, "article_id", "")
        or getattr(article, "id", "")
    )


def article_title(article: NewsArticle | Mapping[str, Any]) -> str:
    """Return the best available title."""

    if isinstance(article, Mapping):
        return normalize_text(
            article.get("generated_headline")
            or article.get("title")
            or ""
        )

    return normalize_text(
        getattr(article, "generated_headline", "")
        or getattr(article, "title", "")
    )


def article_category(article: NewsArticle | Mapping[str, Any]) -> str:
    """Return normalized category."""

    value = (
        article.get("category")
        if isinstance(article, Mapping)
        else getattr(article, "category", NewsCategory.OTHER)
    )

    return enum_value(value).lower() or "other"


def article_status(article: NewsArticle | Mapping[str, Any]) -> str:
    """Return normalized status."""

    value = (
        article.get("status")
        if isinstance(article, Mapping)
        else getattr(article, "status", "")
    )

    return enum_value(value).lower()


def article_language(article: NewsArticle | Mapping[str, Any]) -> str:
    """Return normalized language."""

    value = (
        article.get("language")
        if isinstance(article, Mapping)
        else getattr(article, "language", "")
    )

    return enum_value(value).lower()


def article_metadata(
    article: NewsArticle | Mapping[str, Any],
) -> Mapping[str, Any]:
    """Return article metadata mapping."""

    metadata = (
        article.get("metadata", {})
        if isinstance(article, Mapping)
        else getattr(article, "metadata", {})
    )

    return metadata if isinstance(metadata, Mapping) else {}


def article_published_at(
    article: NewsArticle | Mapping[str, Any],
) -> datetime | None:
    """Return article publication datetime where possible."""

    value = (
        article.get("published_at")
        if isinstance(article, Mapping)
        else getattr(article, "published_at", None)
    )

    if isinstance(value, datetime):
        return value

    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    return None


def article_source_name(
    article: NewsArticle | Mapping[str, Any],
) -> str:
    """Return source or publisher name."""

    if isinstance(article, Mapping):
        return normalize_text(
            article.get("source_name")
            or article.get("publisher")
            or ""
        )

    return normalize_text(
        getattr(article, "source_name", "")
        or getattr(article, "publisher", "")
    )

def calculate_base_score(
    article: NewsArticle | Mapping[str, Any],
) -> float:
    """
    Calculate the ranking base score.

    Live production articles are scored by article_scorer before reaching
    this module. Prefer that audited scorer result when it is available.

    Canonical component scores remain the fallback for standalone use and
    deterministic self-tests.
    """

    metadata = article_metadata(article)

    scorer_final_score = safe_float(
        metadata.get("editorial_score")
    )

    if scorer_final_score > 0.0:
        return round(scorer_final_score, 2)

    scorer_base_score = safe_float(
        metadata.get("base_score")
    )

    if scorer_base_score > 0.0:
        return round(scorer_base_score, 2)

    if isinstance(article, Mapping):
        editorial = safe_float(article.get("editorial_score"))
        importance = safe_float(article.get("importance_score"))
        relevance = safe_float(article.get("relevance_score"))
        reliability = safe_float(article.get("reliability_score"))
    else:
        editorial = safe_float(
            getattr(article, "editorial_score", 0.0)
        )
        importance = safe_float(
            getattr(article, "importance_score", 0.0)
        )
        relevance = safe_float(
            getattr(article, "relevance_score", 0.0)
        )
        reliability = safe_float(
            getattr(article, "reliability_score", 0.0)
        )

    score = (
        editorial * 0.40
        + importance * 0.25
        + relevance * 0.20
        + reliability * 0.15
    )

    return round(score, 2)


def calculate_confidence(
    article: NewsArticle | Mapping[str, Any],
) -> float:
    """
    Return ranking confidence.

    Prefer article_scorer's audited confidence for live production articles,
    then fall back to the canonical reliability score.
    """

    metadata = article_metadata(article)

    scorer_confidence = safe_float(
        metadata.get("scoring_confidence")
    )

    if scorer_confidence > 0.0:
        return round(scorer_confidence, 2)

    value = (
        article.get("reliability_score", 0.0)
        if isinstance(article, Mapping)
        else getattr(article, "reliability_score", 0.0)
    )

    return round(safe_float(value), 2)



def is_duplicate(article: NewsArticle | Mapping[str, Any]) -> bool:
    """Return True when the article is marked as a duplicate."""

    duplicate_of = (
        article.get("duplicate_of", "")
        if isinstance(article, Mapping)
        else getattr(article, "duplicate_of", "")
    )

    return bool(normalize_text(duplicate_of)) or article_status(article) == "duplicate"


def is_breaking(article: NewsArticle | Mapping[str, Any]) -> bool:
    """Return True when metadata or tags mark the story as breaking."""

    metadata = article_metadata(article)

    if bool(metadata.get("breaking")):
        return True

    tags = (
        article.get("tags", [])
        if isinstance(article, Mapping)
        else getattr(article, "tags", [])
    )

    return any(
        normalize_text(tag).lower() in {"breaking", "breaking_news"}
        for tag in tags
    )


def is_recent(
    article: NewsArticle | Mapping[str, Any],
    hours: int = 24,
) -> bool:
    """Return True when the story was published recently."""

    published = article_published_at(article)

    if published is None:
        return False

    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)

    age_seconds = (utc_now() - published.astimezone(timezone.utc)).total_seconds()
    return 0 <= age_seconds <= hours * 3600


def assign_band(score: float, rejected: bool = False) -> RankingBand:
    """Assign a human-readable score band."""

    if rejected:
        return RankingBand.REJECTED

    if score >= 85:
        return RankingBand.LEAD

    if score >= 72:
        return RankingBand.STRONG

    if score >= 55:
        return RankingBand.USABLE

    return RankingBand.WEAK


class StoryRanker:
    """Rank and select editorial stories."""

    def __init__(self, config: StoryRankerConfig | None = None) -> None:
        self.config = config or StoryRankerConfig()
        self.config.validate()

    def rank(
        self,
        articles: Sequence[NewsArticle],
    ) -> StoryRankingResult:
        """Rank articles and select the bulletin lineup."""

        ranked_candidates: list[RankedStory] = []
        rejected_results: list[RankedStory] = []

        for article in articles:
            result = self._evaluate_article(article)

            if result.decision is RankingDecision.REJECT:
                rejected_results.append(result)
            else:
                ranked_candidates.append(result)

        ranked_candidates.sort(
            key=lambda item: (
                item.final_score,
                item.confidence,
                article_published_at(item.article)
                or datetime.min.replace(tzinfo=timezone.utc),
                item.article_id,
            ),
            reverse=True,
        )

        self._apply_selection(ranked_candidates)

        ranked_stories = ranked_candidates + rejected_results

        selected_articles = [
            item.article
            for item in ranked_candidates
            if item.decision is RankingDecision.SELECT
        ]

        reserve_articles = [
            item.article
            for item in ranked_candidates
            if item.decision is RankingDecision.RESERVE
        ]

        rejected_articles = [
            item.article
            for item in rejected_results
        ]

        statistics = self._build_statistics(
            input_articles=len(articles),
            ranked_stories=ranked_stories,
        )

        return StoryRankingResult(
            ranked_stories=ranked_stories,
            selected_stories=selected_articles,
            reserve_stories=reserve_articles,
            rejected_stories=rejected_articles,
            statistics=statistics,
            generated_at=utc_now().isoformat(),
        )

    def _evaluate_article(self, article: NewsArticle) -> RankedStory:
        """Evaluate one article and calculate its final score."""

        identifier = article_id(article)
        title = article_title(article)
        category = article_category(article)
        status = article_status(article)
        confidence = calculate_confidence(article)
        base_score = calculate_base_score(article)

        bonuses: dict[str, float] = {}
        penalties: dict[str, float] = {}
        reasons: list[str] = []

        rejected = False

        if not identifier:
            rejected = True
            reasons.append("missing_article_id")

        if not title:
            rejected = True
            reasons.append("missing_title")

        if status in {
            "rejected",
            "duplicate",
            "failed",
            "published",
        }:
            rejected = True
            reasons.append(f"ineligible_status:{status}")

        if self.config.require_validated_status and status not in {
            "validated",
            "ranked",
            "selected",
        }:
            rejected = True
            reasons.append("article_not_validated")

        if is_duplicate(article):
            penalties["duplicate"] = self.config.duplicate_penalty
            rejected = True
            reasons.append("duplicate_article")

        if confidence < self.config.minimum_confidence:
            penalties["low_confidence"] = self.config.low_confidence_penalty
            reasons.append("low_confidence")

        if is_recent(article):
            bonuses["recent_story"] = self.config.recency_bonus
            reasons.append("recent_story")

        if is_breaking(article):
            bonuses["breaking_story"] = self.config.breaking_bonus
            reasons.append("breaking_story")

        if (
            self.config.prefer_english_source
            and article_language(article) == "en"
        ):
            bonuses["english_source"] = 1.0
            reasons.append("english_source")

        final_score = (
            base_score
            + sum(bonuses.values())
            - sum(penalties.values())
        )

        final_score = round(max(0.0, min(100.0, final_score)), 2)

        if final_score < self.config.minimum_score:
            rejected = True
            reasons.append("below_minimum_score")

        decision = (
            RankingDecision.REJECT
            if rejected
            else RankingDecision.RESERVE
        )

        return RankedStory(
            article=article,
            article_id=identifier,
            title=title,
            category=category,
            source_name=article_source_name(article),
            base_score=base_score,
            final_score=final_score,
            confidence=confidence,
            decision=decision,
            band=assign_band(final_score, rejected=rejected),
            bonuses=bonuses,
            penalties=penalties,
            reasons=reasons,
            selected=False,
        )

    def _apply_selection(
        self,
        ranked_candidates: list[RankedStory],
    ) -> None:
        """Build a balanced bulletin while preserving editorial ranking.

        Selection happens in two passes:

        1. Fill preferred editorial slots with the strongest eligible story.
        2. Fill remaining bulletin capacity using overall ranking score.

        Existing category limits remain active, and a source limit prevents
        one publisher from dominating the bulletin.
        """

        category_counts: dict[str, int] = defaultdict(int)
        source_counts: dict[str, int] = defaultdict(int)
        seen_categories: set[str] = set()
        selected_items: list[RankedStory] = []

        for rank_position, item in enumerate(
            ranked_candidates,
            start=1,
        ):
            item.rank = rank_position
            item.selected = False
            item.decision = RankingDecision.RESERVE

        def normalized(value: str) -> str:
            return (
                value.strip()
                .lower()
                .replace("-", "_")
                .replace(" ", "_")
            )

        def can_select(item: RankedStory) -> bool:
            if len(selected_items) >= self.config.max_stories:
                return False

            category_key = normalized(item.category or "other")
            source_key = normalized(item.source_name or "unknown")

            if (
                category_counts[category_key]
                >= self.config.max_per_category
            ):
                return False

            if (
                source_counts[source_key]
                >= self.config.max_per_source
            ):
                return False

            return True

        def select_item(
            item: RankedStory,
            reason: str,
        ) -> None:
            category_key = normalized(item.category or "other")
            source_key = normalized(item.source_name or "unknown")

            if category_key not in seen_categories:
                diversity_bonus = (
                    self.config.category_diversity_bonus
                )
                item.final_score = round(
                    min(
                        100.0,
                        item.final_score + diversity_bonus,
                    ),
                    2,
                )
                item.bonuses[
                    "category_diversity"
                ] = diversity_bonus
                item.reasons.append("category_diversity")

            item.decision = RankingDecision.SELECT
            item.selected = True
            item.band = assign_band(item.final_score)
            item.reasons.append(reason)

            selected_items.append(item)
            category_counts[category_key] += 1
            source_counts[source_key] += 1
            seen_categories.add(category_key)

        # -----------------------------------------------------------------
        # PASS 1: Fill the preferred newsroom slots.
        # -----------------------------------------------------------------

        for slot_number, slot_categories in enumerate(
            self.config.editorial_slots,
            start=1,
        ):
            if len(selected_items) >= self.config.max_stories:
                break

            preferred = {
                normalized(category)
                for category in slot_categories
            }

            candidate = next(
                (
                    item
                    for item in ranked_candidates
                    if (
                        not item.selected
                        and normalized(
                            item.category or "other"
                        ) in preferred
                        and can_select(item)
                    )
                ),
                None,
            )

            if candidate is not None:
                select_item(
                    candidate,
                    f"editorial_slot:{slot_number}",
                )

        # -----------------------------------------------------------------
        # PASS 2: Fill remaining capacity by score.
        # -----------------------------------------------------------------

        for item in ranked_candidates:
            if len(selected_items) >= self.config.max_stories:
                break

            if item.selected:
                continue

            if can_select(item):
                select_item(
                    item,
                    "score_based_capacity_fill",
                )

        # -----------------------------------------------------------------
        # Explain why unselected stories remain in reserve.
        # -----------------------------------------------------------------

        for item in ranked_candidates:
            if item.selected:
                continue

            category_key = normalized(item.category or "other")
            source_key = normalized(item.source_name or "unknown")

            if (
                category_counts[category_key]
                >= self.config.max_per_category
            ):
                item.reasons.append("category_limit_reached")
            elif (
                source_counts[source_key]
                >= self.config.max_per_source
            ):
                item.reasons.append("source_limit_reached")
            elif len(selected_items) >= self.config.max_stories:
                item.reasons.append("bulletin_capacity_reached")
            else:
                item.reasons.append("not_selected_for_bulletin_balance")

            item.decision = RankingDecision.RESERVE

        # The slot order is the final broadcast order. Stories used to fill
        # remaining capacity retain their original score order.
        for final_rank, item in enumerate(
            selected_items,
            start=1,
        ):
            item.rank = final_rank

            metadata = dict(
                getattr(item.article, "metadata", {}) or {}
            )
            metadata["ranking_score"] = item.final_score
            metadata["ranking_position"] = final_rank
            metadata["ranking_decision"] = item.decision.value
            metadata["ranking_reasons"] = list(item.reasons)
            metadata["bulletin_category"] = normalized(
                item.category or "other"
            )
            metadata["bulletin_source_position"] = source_counts[
                normalized(item.source_name or "unknown")
            ]

            item.article.status = ArticleStatus.SELECTED
            item.article.metadata = metadata

        reserve_items = [
            item
            for item in ranked_candidates
            if not item.selected
        ]

        reserve_items.sort(
            key=lambda item: (
                item.final_score,
                item.confidence,
                item.article_id,
            ),
            reverse=True,
        )

        start_rank = len(selected_items) + 1

        for offset, item in enumerate(reserve_items):
            item.rank = start_rank + offset

    def _build_statistics(
        self,
        input_articles: int,
        ranked_stories: Sequence[RankedStory],
    ) -> StoryRankingStatistics:
        """Build ranking statistics."""

        selected = [
            item
            for item in ranked_stories
            if item.decision is RankingDecision.SELECT
        ]
        reserve = [
            item
            for item in ranked_stories
            if item.decision is RankingDecision.RESERVE
        ]
        rejected = [
            item
            for item in ranked_stories
            if item.decision is RankingDecision.REJECT
        ]

        eligible = selected + reserve
        scores = [item.final_score for item in eligible]

        category_counts: dict[str, int] = defaultdict(int)
        selected_category_counts: dict[str, int] = defaultdict(int)

        for item in ranked_stories:
            category_counts[item.category] += 1

        for item in selected:
            selected_category_counts[item.category] += 1

        return StoryRankingStatistics(
            input_articles=input_articles,
            eligible_articles=len(eligible),
            ranked_articles=len(ranked_stories),
            selected_articles=len(selected),
            reserve_articles=len(reserve),
            rejected_articles=len(rejected),
            highest_score=max(scores, default=0.0),
            lowest_score=min(scores, default=0.0),
            average_score=(
                round(sum(scores) / len(scores), 2)
                if scores
                else 0.0
            ),
            category_counts=dict(sorted(category_counts.items())),
            selected_category_counts=dict(
                sorted(selected_category_counts.items())
            ),
        )


def rank_stories(
    articles: Sequence[NewsArticle],
    config: StoryRankerConfig | None = None,
) -> StoryRankingResult:
    """Convenience function for pipeline integration."""

    return StoryRanker(config).rank(articles)


def _make_sample_article(
    *,
    article_id_value: str,
    title: str,
    category: NewsCategory,
    editorial_score: float,
    importance_score: float,
    relevance_score: float,
    reliability_score: float,
    status: ArticleStatus = ArticleStatus.VALIDATED,
    duplicate_of: str = "",
    breaking: bool = False,
    published_hours_ago: int = 2,
) -> NewsArticle:
    """Create one canonical sample article."""

    published_at = utc_now().replace(microsecond=0)

    if published_hours_ago:
        published_at = published_at.replace(
            hour=max(0, published_at.hour - published_hours_ago)
        )

    return NewsArticle(
        title=title,
        url=f"https://example.com/{article_id_value}",
        source_id=f"source_{article_id_value}",
        article_id=article_id_value,
        status=status,
        category=category,
        language=LanguageCode.ENGLISH,
        source_name="Bahuvu Test Desk",
        publisher="Bahuvu News",
        author="Bahuvu Editorial Team",
        description=f"Summary for {title}",
        raw_text=f"Full report for {title}",
        cleaned_text=f"Verified report for {title}",
        summary=f"Summary for {title}",
        generated_headline=title,
        canonical_url=f"https://example.com/{article_id_value}",
        published_at=published_at,
        reliability_score=reliability_score,
        relevance_score=relevance_score,
        importance_score=importance_score,
        editorial_score=editorial_score,
        duplicate_of=duplicate_of,
        keywords=[category.value],
        tags=["breaking"] if breaking else [],
        metadata={
            "breaking": breaking,
            "editorial_validated": True,
            "production_ready": True,
        },
    )


def _build_sample_articles() -> list[NewsArticle]:
    """Build deterministic sample articles."""

    return [
        _make_sample_article(
            article_id_value="article_lead",
            title="Government Announces Major National Infrastructure Plan",
            category=NewsCategory.NATIONAL,
            editorial_score=94.0,
            importance_score=92.0,
            relevance_score=91.0,
            reliability_score=95.0,
            breaking=True,
        ),
        _make_sample_article(
            article_id_value="article_weather",
            title="Heavy Rain Alert Issued Across Andhra Pradesh",
            category=NewsCategory.WEATHER,
            editorial_score=88.0,
            importance_score=90.0,
            relevance_score=94.0,
            reliability_score=91.0,
        ),
        _make_sample_article(
            article_id_value="article_technology",
            title="Indian Researchers Introduce New AI Tool",
            category=NewsCategory.TECHNOLOGY,
            editorial_score=82.0,
            importance_score=79.0,
            relevance_score=84.0,
            reliability_score=86.0,
        ),
        _make_sample_article(
            article_id_value="article_sports",
            title="India Secures Important International Victory",
            category=NewsCategory.SPORTS,
            editorial_score=76.0,
            importance_score=73.0,
            relevance_score=78.0,
            reliability_score=82.0,
        ),
        _make_sample_article(
            article_id_value="article_business",
            title="Markets Close Higher After Broad Sector Gains",
            category=NewsCategory.BUSINESS,
            editorial_score=70.0,
            importance_score=68.0,
            relevance_score=74.0,
            reliability_score=80.0,
        ),
        _make_sample_article(
            article_id_value="article_low",
            title="Low Priority Community Update",
            category=NewsCategory.OTHER,
            editorial_score=30.0,
            importance_score=28.0,
            relevance_score=35.0,
            reliability_score=45.0,
        ),
        _make_sample_article(
            article_id_value="article_duplicate",
            title="Duplicate Infrastructure Story",
            category=NewsCategory.NATIONAL,
            editorial_score=91.0,
            importance_score=90.0,
            relevance_score=89.0,
            reliability_score=93.0,
            duplicate_of="article_lead",
        ),
    ]


def run_self_test() -> None:
    """Run deterministic self-test."""

    print("=" * 70)
    print(MODULE_NAME)
    print(f"Version: {MODULE_VERSION}")
    print("=" * 70)

    config = StoryRankerConfig(
        max_stories=5,
        minimum_score=50.0,
        max_per_category=2,
        max_per_source=5,
        minimum_confidence=50.0,
    )

    articles = _build_sample_articles()
    result = rank_stories(articles, config)

    stats = result.statistics

    assert stats.input_articles == 7
    assert stats.selected_articles == 5
    assert stats.rejected_articles == 2
    assert len(result.selected_stories) == 5
    assert result.selected_stories[0].article_id == "article_lead"
    assert result.selected_stories[0].status is ArticleStatus.SELECTED
    assert result.selected_stories[0].metadata["ranking_position"] == 1

    print("Input articles:", stats.input_articles)
    print("Eligible articles:", stats.eligible_articles)
    print("Ranked articles:", stats.ranked_articles)
    print("Selected articles:", stats.selected_articles)
    print("Reserve articles:", stats.reserve_articles)
    print("Rejected articles:", stats.rejected_articles)
    print("Highest score:", f"{stats.highest_score:.2f}")
    print("Lowest score:", f"{stats.lowest_score:.2f}")
    print("Average score:", f"{stats.average_score:.2f}")
    print("-" * 70)

    print("Selected bulletin stories:")

    selected_results = sorted(
        [
            item
            for item in result.ranked_stories
            if item.decision is RankingDecision.SELECT
        ],
        key=lambda item: item.rank,
    )

    for item in selected_results:
        print(
            f"{item.rank}. {item.title} | "
            f"{item.category} | "
            f"{item.final_score:.2f}"
        )

    print("-" * 70)
    print("Rejected stories:")

    for item in result.ranked_stories:
        if item.decision is RankingDecision.REJECT:
            print(
                f"- {item.title} | "
                f"{item.final_score:.2f} | "
                f"{', '.join(item.reasons)}"
            )

    print("-" * 70)
    print("Story ranker self-test passed.")
    print("=" * 70)


def main() -> None:
    """Command-line entry point."""

    run_self_test()


if __name__ == "__main__":
    main()