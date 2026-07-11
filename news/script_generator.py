# news/script_generator.py

"""
BahuvuNewsAI - Broadcast Script Generator
=========================================

Converts ranked and editorially approved NewsArticle objects into a structured,
broadcast-ready English news bulletin.

Responsibilities
----------------
1. Accept ranked NewsArticle objects.
2. Reject unusable or editorially rejected stories.
3. Select stories for the bulletin.
4. Organize stories into editorial sections.
5. Generate headlines, anchor introductions, story narration, transitions,
   opening copy, and closing copy.
6. Estimate word counts and broadcast duration.
7. Write bulletin output as:
       outputs/scripts/bulletin.txt
       outputs/scripts/bulletin.json
       outputs/scripts/bulletin_metadata.json
8. Provide a deterministic self-test.

This module does not perform:
- Telugu translation
- LLM generation
- Voice synthesis
- Graphics generation
- Video rendering
- YouTube publishing

The generated script is deliberately deterministic. A later editorial-polishing
or language-model stage may improve the prose without changing the underlying
facts or bulletin structure.
"""

from __future__ import annotations

import json
import re
import textwrap
from collections import defaultdict
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
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
        "Unable to import news models. Run this module from the project root "
        "using: python -m news.script_generator"
    ) from exc


# =============================================================================
# MODULE INFORMATION
# =============================================================================

MODULE_NAME = "BahuvuNewsAI Broadcast Script Generator"
MODULE_VERSION = "1.0.0"

DEFAULT_BULLETIN_TITLE = "BAHUVU NEWS"
DEFAULT_EDITION_NAME = "Evening Bulletin"
DEFAULT_LANGUAGE = "en"
DEFAULT_PRESENTER = "Bahuvu News Anchor"

DEFAULT_WORDS_PER_MINUTE = 145
DEFAULT_MAX_STORIES = 12
DEFAULT_MAX_HEADLINES = 6
DEFAULT_MINIMUM_SCORE = 50.0

OUTPUT_DIRECTORY = Path("outputs") / "scripts"
DEFAULT_TEXT_FILENAME = "bulletin.txt"
DEFAULT_JSON_FILENAME = "bulletin.json"
DEFAULT_METADATA_FILENAME = "bulletin_metadata.json"


# =============================================================================
# ENUMERATIONS
# =============================================================================


class BulletinSectionType(str, Enum):
    """Editorial sections used in a Bahuvu News bulletin."""

    OPENING = "opening"
    HEADLINES = "headlines"
    LEAD = "lead"
    NATIONAL = "national"
    STATE = "state"
    WORLD = "world"
    POLITICS = "politics"
    GOVERNANCE = "governance"
    BUSINESS = "business"
    ECONOMY = "economy"
    TECHNOLOGY = "technology"
    SCIENCE = "science"
    HEALTH = "health"
    EDUCATION = "education"
    AGRICULTURE = "agriculture"
    ENVIRONMENT = "environment"
    LAW_CRIME = "law_crime"
    SPORTS = "sports"
    ENTERTAINMENT = "entertainment"
    CULTURE = "culture"
    WEATHER = "weather"
    DISASTER = "disaster"
    LOCAL = "local"
    OTHER = "other"
    CLOSING = "closing"


class ScriptSegmentType(str, Enum):
    """Types of script elements within a bulletin."""

    OPENING = "opening"
    HEADLINE = "headline"
    SECTION_INTRO = "section_intro"
    STORY_INTRO = "story_intro"
    STORY_BODY = "story_body"
    CONTEXT = "context"
    TRANSITION = "transition"
    CLOSING = "closing"


class StoryRole(str, Enum):
    """Editorial role assigned to a story."""

    LEAD = "lead"
    MAJOR = "major"
    REGULAR = "regular"
    SHORT = "short"


# =============================================================================
# CONFIGURATION
# =============================================================================


@dataclass(slots=True)
class ScriptGeneratorConfig:
    """Runtime configuration for bulletin generation."""

    bulletin_title: str = DEFAULT_BULLETIN_TITLE
    edition_name: str = DEFAULT_EDITION_NAME
    presenter: str = DEFAULT_PRESENTER
    language: str = DEFAULT_LANGUAGE

    max_stories: int = DEFAULT_MAX_STORIES
    max_headlines: int = DEFAULT_MAX_HEADLINES
    minimum_score: float = DEFAULT_MINIMUM_SCORE
    words_per_minute: int = DEFAULT_WORDS_PER_MINUTE

    include_headlines: bool = True
    include_story_context: bool = True
    include_section_transitions: bool = True
    include_source_attribution: bool = True

    output_directory: Path = OUTPUT_DIRECTORY
    text_filename: str = DEFAULT_TEXT_FILENAME
    json_filename: str = DEFAULT_JSON_FILENAME
    metadata_filename: str = DEFAULT_METADATA_FILENAME

    def validate(self) -> None:
        """Validate configuration values."""

        if not self.bulletin_title.strip():
            raise ValueError("bulletin_title cannot be empty.")

        if not self.edition_name.strip():
            raise ValueError("edition_name cannot be empty.")

        if self.max_stories < 1:
            raise ValueError("max_stories must be at least 1.")

        if self.max_headlines < 0:
            raise ValueError("max_headlines cannot be negative.")

        if self.minimum_score < 0:
            raise ValueError("minimum_score cannot be negative.")

        if self.words_per_minute < 60:
            raise ValueError("words_per_minute must be at least 60.")

        if not isinstance(self.output_directory, Path):
            self.output_directory = Path(self.output_directory)


# =============================================================================
# OUTPUT DATA MODELS
# =============================================================================


@dataclass(slots=True)
class ScriptSegment:
    """A single readable segment of a broadcast script."""

    segment_type: ScriptSegmentType
    text: str
    section: BulletinSectionType
    article_id: str | None = None
    sequence: int = 0
    word_count: int = 0
    estimated_seconds: float = 0.0

    def __post_init__(self) -> None:
        self.text = normalize_text(self.text)
        self.word_count = count_words(self.text)


@dataclass(slots=True)
class ScriptStory:
    """A selected news story converted into broadcast copy."""

    article_id: str
    source_id: str
    headline: str
    anchor_intro: str
    body: str
    context: str
    section: BulletinSectionType
    role: StoryRole
    category: str
    region: str
    publisher: str
    source_url: str
    score: float
    confidence: float
    sequence: int
    word_count: int
    estimated_seconds: float
    published_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BulletinSection:
    """A logical section within the bulletin."""

    section_type: BulletinSectionType
    title: str
    sequence: int
    stories: list[ScriptStory] = field(default_factory=list)
    segments: list[ScriptSegment] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return sum(segment.word_count for segment in self.segments)

    @property
    def estimated_seconds(self) -> float:
        return sum(segment.estimated_seconds for segment in self.segments)


@dataclass(slots=True)
class BulletinStatistics:
    """Calculated bulletin production statistics."""

    input_articles: int = 0
    eligible_articles: int = 0
    selected_articles: int = 0
    rejected_articles: int = 0
    sections: int = 0
    segments: int = 0
    headlines: int = 0
    total_words: int = 0
    estimated_seconds: float = 0.0
    estimated_minutes: float = 0.0
    average_story_score: float = 0.0
    highest_story_score: float = 0.0
    lowest_story_score: float = 0.0
    category_counts: dict[str, int] = field(default_factory=dict)
    role_counts: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class Bulletin:
    """Complete generated bulletin."""

    bulletin_id: str
    title: str
    edition: str
    presenter: str
    language: str
    bulletin_date: str
    generated_at: str
    opening: str
    headlines: list[str]
    sections: list[BulletinSection]
    closing: str
    full_script: str
    statistics: BulletinStatistics
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BulletinOutputPaths:
    """Paths written by ScriptWriter."""

    text_path: Path
    json_path: Path
    metadata_path: Path


# =============================================================================
# CATEGORY MAPPING
# =============================================================================


CATEGORY_SECTION_MAP: dict[str, BulletinSectionType] = {
    "national": BulletinSectionType.NATIONAL,
    "international": BulletinSectionType.WORLD,
    "world": BulletinSectionType.WORLD,
    "state": BulletinSectionType.STATE,
    "politics": BulletinSectionType.POLITICS,
    "governance": BulletinSectionType.GOVERNANCE,
    "business": BulletinSectionType.BUSINESS,
    "economy": BulletinSectionType.ECONOMY,
    "technology": BulletinSectionType.TECHNOLOGY,
    "science": BulletinSectionType.SCIENCE,
    "health": BulletinSectionType.HEALTH,
    "education": BulletinSectionType.EDUCATION,
    "sports": BulletinSectionType.SPORTS,
    "entertainment": BulletinSectionType.ENTERTAINMENT,
    "culture": BulletinSectionType.CULTURE,
    "weather": BulletinSectionType.WEATHER,
    "disaster": BulletinSectionType.DISASTER,
    "traffic": BulletinSectionType.LOCAL,
    "crime": BulletinSectionType.LAW_CRIME,
    "law": BulletinSectionType.LAW_CRIME,
    "agriculture": BulletinSectionType.AGRICULTURE,
    "environment": BulletinSectionType.ENVIRONMENT,
    "local": BulletinSectionType.LOCAL,
    "editorial": BulletinSectionType.OTHER,
    "factcheck": BulletinSectionType.OTHER,
    "other": BulletinSectionType.OTHER,
}

SECTION_ORDER: tuple[BulletinSectionType, ...] = (
    BulletinSectionType.LEAD,
    BulletinSectionType.NATIONAL,
    BulletinSectionType.STATE,
    BulletinSectionType.POLITICS,
    BulletinSectionType.GOVERNANCE,
    BulletinSectionType.WORLD,
    BulletinSectionType.BUSINESS,
    BulletinSectionType.ECONOMY,
    BulletinSectionType.TECHNOLOGY,
    BulletinSectionType.SCIENCE,
    BulletinSectionType.HEALTH,
    BulletinSectionType.EDUCATION,
    BulletinSectionType.AGRICULTURE,
    BulletinSectionType.ENVIRONMENT,
    BulletinSectionType.LAW_CRIME,
    BulletinSectionType.SPORTS,
    BulletinSectionType.ENTERTAINMENT,
    BulletinSectionType.CULTURE,
    BulletinSectionType.WEATHER,
    BulletinSectionType.DISASTER,
    BulletinSectionType.LOCAL,
    BulletinSectionType.OTHER,
)

SECTION_TITLES: dict[BulletinSectionType, str] = {
    BulletinSectionType.LEAD: "Lead Story",
    BulletinSectionType.NATIONAL: "National News",
    BulletinSectionType.STATE: "State News",
    BulletinSectionType.WORLD: "World News",
    BulletinSectionType.POLITICS: "Politics",
    BulletinSectionType.GOVERNANCE: "Governance",
    BulletinSectionType.BUSINESS: "Business",
    BulletinSectionType.ECONOMY: "Economy",
    BulletinSectionType.TECHNOLOGY: "Technology",
    BulletinSectionType.SCIENCE: "Science",
    BulletinSectionType.HEALTH: "Health",
    BulletinSectionType.EDUCATION: "Education",
    BulletinSectionType.AGRICULTURE: "Agriculture",
    BulletinSectionType.ENVIRONMENT: "Environment",
    BulletinSectionType.LAW_CRIME: "Law and Crime",
    BulletinSectionType.SPORTS: "Sports",
    BulletinSectionType.ENTERTAINMENT: "Entertainment",
    BulletinSectionType.CULTURE: "Culture",
    BulletinSectionType.WEATHER: "Weather",
    BulletinSectionType.DISASTER: "Disaster Updates",
    BulletinSectionType.LOCAL: "Local News",
    BulletinSectionType.OTHER: "Other News",
    BulletinSectionType.OPENING: "Opening",
    BulletinSectionType.HEADLINES: "Headlines",
    BulletinSectionType.CLOSING: "Closing",
}

SECTION_TRANSITIONS: dict[BulletinSectionType, str] = {
    BulletinSectionType.NATIONAL: "We begin with national news.",
    BulletinSectionType.STATE: "Turning now to news from the states.",
    BulletinSectionType.POLITICS: "In political news.",
    BulletinSectionType.GOVERNANCE: "Now to governance and public administration.",
    BulletinSectionType.WORLD: "In international news.",
    BulletinSectionType.BUSINESS: "Moving to business news.",
    BulletinSectionType.ECONOMY: "Now to the economy.",
    BulletinSectionType.TECHNOLOGY: "In technology news.",
    BulletinSectionType.SCIENCE: "Turning to science.",
    BulletinSectionType.HEALTH: "In health news.",
    BulletinSectionType.EDUCATION: "Now to education.",
    BulletinSectionType.AGRICULTURE: "In agriculture news.",
    BulletinSectionType.ENVIRONMENT: "Turning to the environment.",
    BulletinSectionType.LAW_CRIME: "In law and crime news.",
    BulletinSectionType.SPORTS: "Now to sports.",
    BulletinSectionType.ENTERTAINMENT: "In entertainment news.",
    BulletinSectionType.CULTURE: "Turning to culture.",
    BulletinSectionType.WEATHER: "And now, the weather.",
    BulletinSectionType.DISASTER: "We have an important disaster update.",
    BulletinSectionType.LOCAL: "Now to local news.",
    BulletinSectionType.OTHER: "In other news.",
}


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""

    return datetime.now(timezone.utc)


def enum_value(value: Any) -> str:
    """Return an enum's value or a normalized string."""

    if isinstance(value, Enum):
        return str(value.value)

    if value is None:
        return ""

    return str(value)


def normalize_text(value: Any) -> str:
    """Normalize whitespace and remove unsafe control characters."""

    if value is None:
        return ""

    text = str(value)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_sentence(value: Any) -> str:
    """Normalize text and ensure it ends with sentence punctuation."""

    text = normalize_text(value)

    if not text:
        return ""

    if text[-1] not in ".!?":
        text += "."

    return text


def count_words(value: str) -> int:
    """Count readable words in a string."""

    return len(re.findall(r"\b[\w'-]+\b", value, flags=re.UNICODE))


def estimate_seconds(word_count: int, words_per_minute: int) -> float:
    """Estimate narration duration from word count."""

    if word_count <= 0:
        return 0.0

    return round((word_count / words_per_minute) * 60.0, 2)


def truncate_words(value: str, maximum_words: int) -> str:
    """Limit text to a maximum number of words without cutting a word."""

    text = normalize_text(value)

    if not text or maximum_words <= 0:
        return ""

    words = text.split()

    if len(words) <= maximum_words:
        return text

    result = " ".join(words[:maximum_words]).rstrip(" ,;:-")
    return result + "..."


def remove_html(value: str) -> str:
    """Remove basic HTML tags from source text."""

    text = normalize_text(value)
    text = re.sub(r"<[^>]+>", " ", text)
    return normalize_text(text)


def safe_float(value: Any, default: float = 0.0) -> float:
    """Convert a value to float safely."""

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_article_value(
    article: NewsArticle | Mapping[str, Any],
    name: str,
    default: Any = None,
) -> Any:
    """
    Read a logical article field from either a NewsArticle object or mapping.

    This compatibility layer translates the script generator's logical field
    names into the canonical field names used by news.models.NewsArticle.
    """

    field_aliases: dict[str, tuple[str, ...]] = {
        "id": ("article_id", "id"),
        "article_url": ("url", "article_url"),
        "content": (
            "cleaned_text",
            "raw_text",
            "description",
            "content",
        ),
        "summary": (
            "summary",
            "description",
            "cleaned_text",
        ),
        "score": (
            "editorial_score",
            "importance_score",
            "relevance_score",
            "reliability_score",
            "score",
        ),
        "confidence": (
            "reliability_score",
            "editorial_score",
            "confidence",
        ),
        "region": ("region",),
        "decision": ("decision",),
    }

    candidate_names = field_aliases.get(name, (name,))

    if isinstance(article, Mapping):
        for candidate in candidate_names:
            value = article.get(candidate)

            if value not in (None, "", [], {}):
                return value

        metadata = article.get("metadata", {})

        if isinstance(metadata, Mapping):
            value = metadata.get(name)

            if value not in (None, "", [], {}):
                return value

        return default

    for candidate in candidate_names:
        if hasattr(article, candidate):
            value = getattr(article, candidate)

            if value not in (None, "", [], {}):
                return value

    metadata = getattr(article, "metadata", {})

    if isinstance(metadata, Mapping):
        value = metadata.get(name)

        if value not in (None, "", [], {}):
            return value

    return default

def serialize_value(value: Any) -> Any:
    """Convert project objects into JSON-compatible values."""

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, date):
        return value.isoformat()

    if is_dataclass(value):
        return {
            key: serialize_value(item)
            for key, item in asdict(value).items()
        }

    if isinstance(value, Mapping):
        return {
            str(key): serialize_value(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [serialize_value(item) for item in value]

    return value


def article_sort_key(article: NewsArticle | Mapping[str, Any]) -> tuple[float, float, str]:
    """Produce deterministic descending rank criteria."""

    score = safe_float(get_article_value(article, "score", 0.0))
    confidence = safe_float(get_article_value(article, "confidence", 0.0))
    published = enum_value(get_article_value(article, "published_at", ""))

    return score, confidence, published


def make_bulletin_id(generated_at: datetime) -> str:
    """Build a deterministic-format bulletin identifier."""

    return generated_at.strftime("bulletin_%Y%m%d_%H%M%S")


# =============================================================================
# SCRIPT GENERATOR
# =============================================================================


class ScriptGenerator:
    """Generate a complete broadcast bulletin from ranked articles."""

    def __init__(self, config: ScriptGeneratorConfig | None = None) -> None:
        self.config = config or ScriptGeneratorConfig()
        self.config.validate()

    def generate(
        self,
        articles: Sequence[NewsArticle | Mapping[str, Any]],
        bulletin_date: date | datetime | str | None = None,
    ) -> Bulletin:
        """Generate a complete bulletin."""

        generated_at = utc_now()
        resolved_date = self._resolve_bulletin_date(bulletin_date)

        eligible = self._filter_eligible_articles(articles)
        ranked = sorted(
            eligible,
            key=article_sort_key,
            reverse=True,
        )
        selected = ranked[: self.config.max_stories]

        if not selected:
            raise ValueError(
                "No eligible articles were available for script generation."
            )

        script_stories = self._create_script_stories(selected)
        sections = self._build_sections(script_stories)

        opening = self._build_opening(resolved_date)
        headlines = self._build_headlines(script_stories)
        closing = self._build_closing()

        full_script = self._render_full_script(
            opening=opening,
            headlines=headlines,
            sections=sections,
            closing=closing,
        )

        statistics = self._calculate_statistics(
            input_articles=len(articles),
            eligible_articles=len(eligible),
            stories=script_stories,
            sections=sections,
            headlines=headlines,
            full_script=full_script,
        )

        bulletin = Bulletin(
            bulletin_id=make_bulletin_id(generated_at),
            title=self.config.bulletin_title,
            edition=self.config.edition_name,
            presenter=self.config.presenter,
            language=self.config.language,
            bulletin_date=resolved_date,
            generated_at=generated_at.isoformat(),
            opening=opening,
            headlines=headlines,
            sections=sections,
            closing=closing,
            full_script=full_script,
            statistics=statistics,
            metadata={
                "module": MODULE_NAME,
                "module_version": MODULE_VERSION,
                "generator_type": "deterministic_editorial_engine",
                "minimum_score": self.config.minimum_score,
                "maximum_stories": self.config.max_stories,
                "words_per_minute": self.config.words_per_minute,
                "requires_editorial_review": True,
            },
        )

        return bulletin

    def _resolve_bulletin_date(
        self,
        value: date | datetime | str | None,
    ) -> str:
        """Convert a bulletin date into ISO date format."""

        if value is None:
            return datetime.now().astimezone().date().isoformat()

        if isinstance(value, datetime):
            return value.date().isoformat()

        if isinstance(value, date):
            return value.isoformat()

        text = normalize_text(value)

        if not text:
            return datetime.now().astimezone().date().isoformat()

        try:
            return datetime.fromisoformat(text).date().isoformat()
        except ValueError:
            return text

    def _filter_eligible_articles(
        self,
        articles: Sequence[NewsArticle | Mapping[str, Any]],
    ) -> list[NewsArticle | Mapping[str, Any]]:
        """Remove rejected, duplicate, empty, or low-scoring articles."""

        eligible: list[NewsArticle | Mapping[str, Any]] = []

        for article in articles:
            article_id = normalize_text(get_article_value(article, "id", ""))
            title = normalize_text(get_article_value(article, "title", ""))
            score = safe_float(get_article_value(article, "score", 0.0))
            status = enum_value(
                get_article_value(article, "status", "")
            ).lower()
            decision = enum_value(
                get_article_value(article, "decision", "")
            ).lower()

            if not article_id or not title:
                continue

            if status in {
                "rejected",
                "duplicate",
                "archived",
            }:
                continue

            if decision in {
                "reject",
                "rejected",
                "duplicate",
                "blocked",
            }:
                continue

            if score < self.config.minimum_score:
                continue

            eligible.append(article)

        return eligible

    def _create_script_stories(
        self,
        articles: Sequence[NewsArticle | Mapping[str, Any]],
    ) -> list[ScriptStory]:
        """Convert selected articles into broadcast stories."""

        stories: list[ScriptStory] = []

        for index, article in enumerate(articles, start=1):
            role = self._assign_story_role(index=index)
            category = enum_value(
                get_article_value(article, "category", "other")
            ).lower()

            original_section = CATEGORY_SECTION_MAP.get(
                category,
                BulletinSectionType.OTHER,
            )

            section = (
                BulletinSectionType.LEAD
                if role is StoryRole.LEAD
                else original_section
            )

            headline = self._build_story_headline(article)
            anchor_intro = self._build_anchor_intro(
                article=article,
                role=role,
            )
            body = self._build_story_body(
                article=article,
                role=role,
            )
            context = self._build_story_context(
                article=article,
                role=role,
            )

            combined_text = " ".join(
                part for part in (anchor_intro, body, context) if part
            )
            word_count = count_words(combined_text)
            duration = estimate_seconds(
                word_count,
                self.config.words_per_minute,
            )

            stories.append(
                ScriptStory(
                    article_id=normalize_text(
                        get_article_value(article, "id", "")
                    ),
                    source_id=normalize_text(
                        get_article_value(article, "source_id", "")
                    ),
                    headline=headline,
                    anchor_intro=anchor_intro,
                    body=body,
                    context=context,
                    section=section,
                    role=role,
                    category=category,
                    region=normalize_text(
                        get_article_value(article, "region", "")
                    ),
                    publisher=normalize_text(
                        get_article_value(article, "publisher", "")
                    ),
                    source_url=normalize_text(
                        get_article_value(article, "article_url", "")
                    ),
                    score=round(
                        safe_float(
                            get_article_value(article, "score", 0.0)
                        ),
                        2,
                    ),
                    confidence=round(
                        safe_float(
                            get_article_value(article, "confidence", 0.0)
                        ),
                        2,
                    ),
                    sequence=index,
                    word_count=word_count,
                    estimated_seconds=duration,
                    published_at=enum_value(
                        get_article_value(article, "published_at", "")
                    ) or None,
                    metadata={
                        "original_section": original_section.value,
                        "editorial_review_required": True,
                    },
                )
            )

        return stories

    def _assign_story_role(self, index: int) -> StoryRole:
        """Assign story importance based on ranking position."""

        if index == 1:
            return StoryRole.LEAD

        if index <= 3:
            return StoryRole.MAJOR

        if index <= 8:
            return StoryRole.REGULAR

        return StoryRole.SHORT

    def _build_story_headline(
        self,
        article: NewsArticle | Mapping[str, Any],
    ) -> str:
        """Create a clean headline suitable for the headline roundup."""

        title = remove_html(
            normalize_text(get_article_value(article, "title", ""))
        )

        title = re.sub(
            r"\s*[-|]\s*(Reuters|AP|ANI|PTI|BBC|CNN|The Hindu|NDTV)\s*$",
            "",
            title,
            flags=re.IGNORECASE,
        )

        return truncate_words(title, 18).rstrip(".")

    def _build_anchor_intro(
        self,
        article: NewsArticle | Mapping[str, Any],
        role: StoryRole,
    ) -> str:
        """Build the anchor introduction for a story."""

        title = self._build_story_headline(article)
        region = normalize_text(get_article_value(article, "region", ""))
        publisher = normalize_text(
            get_article_value(article, "publisher", "")
        )

        if role is StoryRole.LEAD:
            prefix = "Our lead story tonight:"
        elif role is StoryRole.MAJOR:
            prefix = "In another major development,"
        elif role is StoryRole.SHORT:
            prefix = "Briefly,"
        else:
            prefix = "In other news,"

        location_phrase = f" in {region}" if region else ""
        attribution = ""

        if self.config.include_source_attribution and publisher:
            attribution = f" The report comes from {publisher}."

        return clean_sentence(
            f"{prefix} {title}{location_phrase}."
            f"{attribution}"
        )

    def _build_story_body(
        self,
        article: NewsArticle | Mapping[str, Any],
        role: StoryRole,
    ) -> str:
        """Build the main factual narration for a story."""

        summary = remove_html(
            normalize_text(get_article_value(article, "summary", ""))
        )
        content = remove_html(
            normalize_text(get_article_value(article, "content", ""))
        )

        source_text = summary or content

        if not source_text:
            source_text = self._build_story_headline(article)

        maximum_words = {
            StoryRole.LEAD: 125,
            StoryRole.MAJOR: 95,
            StoryRole.REGULAR: 70,
            StoryRole.SHORT: 42,
        }[role]

        body = truncate_words(source_text, maximum_words)
        return clean_sentence(body)

    def _build_story_context(
        self,
        article: NewsArticle | Mapping[str, Any],
        role: StoryRole,
    ) -> str:
        """Build optional secondary context without inventing facts."""

        if not self.config.include_story_context:
            return ""

        if role not in {StoryRole.LEAD, StoryRole.MAJOR}:
            return ""

        content = remove_html(
            normalize_text(get_article_value(article, "content", ""))
        )
        summary = remove_html(
            normalize_text(get_article_value(article, "summary", ""))
        )

        if not content:
            return ""

        normalized_summary = summary.lower()
        normalized_content = content.lower()

        if normalized_content == normalized_summary:
            return ""

        if summary and normalized_content.startswith(normalized_summary):
            remainder = content[len(summary):].strip(" .,-:")
        else:
            remainder = content

        if not remainder:
            return ""

        maximum_words = 65 if role is StoryRole.LEAD else 40
        context = truncate_words(remainder, maximum_words)

        if not context:
            return ""

        return clean_sentence(f"Additional details indicate that {context}")

    def _build_sections(
        self,
        stories: Sequence[ScriptStory],
    ) -> list[BulletinSection]:
        """Group generated stories into ordered bulletin sections."""

        grouped: dict[BulletinSectionType, list[ScriptStory]] = defaultdict(list)

        for story in stories:
            grouped[story.section].append(story)

        sections: list[BulletinSection] = []
        segment_sequence = 1

        for section_sequence, section_type in enumerate(
            SECTION_ORDER,
            start=1,
        ):
            section_stories = grouped.get(section_type, [])

            if not section_stories:
                continue

            section = BulletinSection(
                section_type=section_type,
                title=SECTION_TITLES[section_type],
                sequence=section_sequence,
                stories=list(section_stories),
            )

            if (
                self.config.include_section_transitions
                and section_type is not BulletinSectionType.LEAD
            ):
                transition = SECTION_TRANSITIONS.get(section_type)

                if transition:
                    segment = ScriptSegment(
                        segment_type=ScriptSegmentType.SECTION_INTRO,
                        text=transition,
                        section=section_type,
                        sequence=segment_sequence,
                    )
                    segment.estimated_seconds = estimate_seconds(
                        segment.word_count,
                        self.config.words_per_minute,
                    )
                    section.segments.append(segment)
                    segment_sequence += 1

            for story_index, story in enumerate(section_stories):
                intro_segment = ScriptSegment(
                    segment_type=ScriptSegmentType.STORY_INTRO,
                    text=story.anchor_intro,
                    section=section_type,
                    article_id=story.article_id,
                    sequence=segment_sequence,
                )
                intro_segment.estimated_seconds = estimate_seconds(
                    intro_segment.word_count,
                    self.config.words_per_minute,
                )
                section.segments.append(intro_segment)
                segment_sequence += 1

                body_segment = ScriptSegment(
                    segment_type=ScriptSegmentType.STORY_BODY,
                    text=story.body,
                    section=section_type,
                    article_id=story.article_id,
                    sequence=segment_sequence,
                )
                body_segment.estimated_seconds = estimate_seconds(
                    body_segment.word_count,
                    self.config.words_per_minute,
                )
                section.segments.append(body_segment)
                segment_sequence += 1

                if story.context:
                    context_segment = ScriptSegment(
                        segment_type=ScriptSegmentType.CONTEXT,
                        text=story.context,
                        section=section_type,
                        article_id=story.article_id,
                        sequence=segment_sequence,
                    )
                    context_segment.estimated_seconds = estimate_seconds(
                        context_segment.word_count,
                        self.config.words_per_minute,
                    )
                    section.segments.append(context_segment)
                    segment_sequence += 1

                if story_index < len(section_stories) - 1:
                    transition_segment = ScriptSegment(
                        segment_type=ScriptSegmentType.TRANSITION,
                        text="Also in this section:",
                        section=section_type,
                        sequence=segment_sequence,
                    )
                    transition_segment.estimated_seconds = estimate_seconds(
                        transition_segment.word_count,
                        self.config.words_per_minute,
                    )
                    section.segments.append(transition_segment)
                    segment_sequence += 1

            sections.append(section)

        return sections

    def _build_opening(self, bulletin_date: str) -> str:
        """Generate the bulletin opening."""

        try:
            formatted_date = datetime.fromisoformat(
                bulletin_date
            ).strftime("%A, %d %B %Y")
        except ValueError:
            formatted_date = bulletin_date

        return (
            f"Good evening. This is {self.config.bulletin_title}, "
            f"with the {self.config.edition_name} for {formatted_date}. "
            "Here are the day's most important developments."
        )

    def _build_headlines(
        self,
        stories: Sequence[ScriptStory],
    ) -> list[str]:
        """Generate the opening headline roundup."""

        if not self.config.include_headlines:
            return []

        maximum = min(
            self.config.max_headlines,
            len(stories),
        )

        return [
            clean_sentence(story.headline)
            for story in stories[:maximum]
        ]

    def _build_closing(self) -> str:
        """Generate the bulletin closing."""

        return (
            f"Those were the main stories in this "
            f"{self.config.edition_name}. "
            f"Thank you for watching {self.config.bulletin_title}. "
            "Please follow Bahuvu News for verified news and further updates. "
            "Good night."
        )

    def _render_full_script(
        self,
        opening: str,
        headlines: Sequence[str],
        sections: Sequence[BulletinSection],
        closing: str,
    ) -> str:
        """Render the bulletin into readable anchor copy."""

        parts: list[str] = [
            self.config.bulletin_title,
            self.config.edition_name,
            "",
            opening,
        ]

        if headlines:
            parts.extend(
                [
                    "",
                    "TOP HEADLINES",
                    "",
                ]
            )

            for index, headline in enumerate(headlines, start=1):
                parts.append(f"{index}. {headline}")

        for section in sections:
            parts.extend(
                [
                    "",
                    section.title.upper(),
                    "",
                ]
            )

            for segment in section.segments:
                parts.append(segment.text)
                parts.append("")

        parts.extend(
            [
                "CLOSING",
                "",
                closing,
            ]
        )

        script = "\n".join(parts)
        script = re.sub(r"\n{3,}", "\n\n", script)

        return script.strip() + "\n"

    def _calculate_statistics(
        self,
        input_articles: int,
        eligible_articles: int,
        stories: Sequence[ScriptStory],
        sections: Sequence[BulletinSection],
        headlines: Sequence[str],
        full_script: str,
    ) -> BulletinStatistics:
        """Calculate production statistics for the bulletin."""

        scores = [story.score for story in stories]
        category_counts: dict[str, int] = defaultdict(int)
        role_counts: dict[str, int] = defaultdict(int)

        for story in stories:
            category_counts[story.category] += 1
            role_counts[story.role.value] += 1

        total_words = count_words(full_script)
        total_seconds = estimate_seconds(
            total_words,
            self.config.words_per_minute,
        )

        return BulletinStatistics(
            input_articles=input_articles,
            eligible_articles=eligible_articles,
            selected_articles=len(stories),
            rejected_articles=input_articles - eligible_articles,
            sections=len(sections),
            segments=sum(len(section.segments) for section in sections),
            headlines=len(headlines),
            total_words=total_words,
            estimated_seconds=total_seconds,
            estimated_minutes=round(total_seconds / 60.0, 2),
            average_story_score=(
                round(sum(scores) / len(scores), 2)
                if scores
                else 0.0
            ),
            highest_story_score=max(scores, default=0.0),
            lowest_story_score=min(scores, default=0.0),
            category_counts=dict(sorted(category_counts.items())),
            role_counts=dict(sorted(role_counts.items())),
        )


# =============================================================================
# OUTPUT WRITER
# =============================================================================


class ScriptWriter:
    """Write generated bulletin files to disk."""

    def __init__(self, config: ScriptGeneratorConfig | None = None) -> None:
        self.config = config or ScriptGeneratorConfig()
        self.config.validate()

    def write(self, bulletin: Bulletin) -> BulletinOutputPaths:
        """Write TXT, JSON, and metadata output files."""

        output_directory = self.config.output_directory
        output_directory.mkdir(parents=True, exist_ok=True)

        text_path = output_directory / self.config.text_filename
        json_path = output_directory / self.config.json_filename
        metadata_path = output_directory / self.config.metadata_filename

        text_path.write_text(
            bulletin.full_script,
            encoding="utf-8",
        )

        json_payload = serialize_value(bulletin)

        json_path.write_text(
            json.dumps(
                json_payload,
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        metadata_payload = {
            "bulletin_id": bulletin.bulletin_id,
            "title": bulletin.title,
            "edition": bulletin.edition,
            "language": bulletin.language,
            "bulletin_date": bulletin.bulletin_date,
            "generated_at": bulletin.generated_at,
            "statistics": serialize_value(bulletin.statistics),
            "output_files": {
                "text": str(text_path),
                "json": str(json_path),
                "metadata": str(metadata_path),
            },
            "module": MODULE_NAME,
            "module_version": MODULE_VERSION,
        }

        metadata_path.write_text(
            json.dumps(
                metadata_payload,
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        return BulletinOutputPaths(
            text_path=text_path,
            json_path=json_path,
            metadata_path=metadata_path,
        )


# =============================================================================
# PUBLIC CONVENIENCE FUNCTION
# =============================================================================


def generate_bulletin(
    articles: Sequence[NewsArticle | Mapping[str, Any]],
    config: ScriptGeneratorConfig | None = None,
    write_outputs: bool = True,
    bulletin_date: date | datetime | str | None = None,
) -> Bulletin:
    """
    Generate a bulletin and optionally write its output files.

    This is the preferred integration function for other pipeline modules.
    """

    resolved_config = config or ScriptGeneratorConfig()
    generator = ScriptGenerator(resolved_config)

    bulletin = generator.generate(
        articles=articles,
        bulletin_date=bulletin_date,
    )

    if write_outputs:
        ScriptWriter(resolved_config).write(bulletin)

    return bulletin


# =============================================================================
# SELF-TEST
# =============================================================================


def _make_sample_article(
    article_id: str,
    title: str,
    summary: str,
    content: str,
    category: NewsCategory,
    score: float,
    confidence: float,
    region: str,
    publisher: str,
    published_hour: int,
) -> NewsArticle:
    """Create a sample article using the canonical NewsArticle model."""

    return NewsArticle(
        title=title,
        url=f"https://example.com/news/{article_id}",
        source_id=f"source_{article_id}",
        article_id=article_id,
        status=ArticleStatus.SELECTED,
        category=category,
        language=LanguageCode.ENGLISH,
        source_name=publisher,
        publisher=publisher,
        author="Bahuvu Test Desk",
        description=summary,
        raw_text=content,
        cleaned_text=content,
        summary=summary,
        generated_headline=title,
        image_url=f"https://example.com/images/{article_id}.jpg",
        canonical_url=f"https://example.com/news/{article_id}",
        published_at=datetime(
            2026,
            7,
            11,
            published_hour,
            0,
            tzinfo=timezone.utc,
        ),
        reliability_score=confidence,
        relevance_score=score,
        importance_score=score,
        editorial_score=score,
        keywords=[category.value, region],
        tags=["self-test", category.value],
        metadata={
            "self_test": True,
            "region": region,
            "decision": "accept",
            "editorial_validated": True,
            "production_ready": True,
        },
    )

def _build_sample_articles() -> list[NewsArticle]:
    """Build deterministic sample input for the module self-test."""

    return [
        _make_sample_article(
            article_id="article_lead",
            title=(
                "Government Announces Major National Infrastructure "
                "Programme"
            ),
            summary=(
                "The government has announced a nationwide infrastructure "
                "programme covering transport, water supply and urban "
                "development projects."
            ),
            content=(
                "The government has announced a nationwide infrastructure "
                "programme covering transport, water supply and urban "
                "development projects. Officials said implementation will "
                "take place in phases, with priority given to projects that "
                "are ready to begin. Detailed financing and monitoring plans "
                "are expected to be released separately."
            ),
            category=NewsCategory.NATIONAL,
            score=92.5,
            confidence=94.0,
            region="India",
            publisher="Bahuvu National Desk",
            published_hour=6,
        ),
        _make_sample_article(
            article_id="article_weather",
            title=(
                "Heavy Rain Alert Issued Across Andhra Pradesh Districts"
            ),
            summary=(
                "Weather officials have issued a heavy rain alert for "
                "several districts of Andhra Pradesh and advised residents "
                "to remain cautious."
            ),
            content=(
                "Weather officials have issued a heavy rain alert for "
                "several districts of Andhra Pradesh and advised residents "
                "to remain cautious. Local administrations have been asked "
                "to monitor low-lying areas and prepare emergency response "
                "teams where necessary."
            ),
            category=NewsCategory.WEATHER,
            score=86.4,
            confidence=91.0,
            region="Andhra Pradesh",
            publisher="Bahuvu Weather Desk",
            published_hour=7,
        ),
        _make_sample_article(
            article_id="article_technology",
            title=(
                "Indian Researchers Develop New Artificial Intelligence Tool"
            ),
            summary=(
                "A research team has introduced an artificial intelligence "
                "tool designed to improve the analysis of public datasets."
            ),
            content=(
                "A research team has introduced an artificial intelligence "
                "tool designed to improve the analysis of public datasets. "
                "The researchers say further testing will be conducted "
                "before the system is considered for large-scale use."
            ),
            category=NewsCategory.TECHNOLOGY,
            score=79.8,
            confidence=84.0,
            region="India",
            publisher="Bahuvu Technology Desk",
            published_hour=8,
        ),
        _make_sample_article(
            article_id="article_sports",
            title="India Records Important Victory in International Match",
            summary=(
                "India secured an important victory after a disciplined "
                "performance in the international sporting event."
            ),
            content=(
                "India secured an important victory after a disciplined "
                "performance in the international sporting event. The team "
                "maintained control during the decisive stages and received "
                "praise for its preparation."
            ),
            category=NewsCategory.SPORTS,
            score=74.2,
            confidence=82.0,
            region="India",
            publisher="Bahuvu Sports Desk",
            published_hour=9,
        ),
        _make_sample_article(
            article_id="article_business",
            title="Markets Close Higher as Major Sectors Record Gains",
            summary=(
                "Domestic markets closed higher, supported by gains in "
                "major sectors and steady investor activity."
            ),
            content=(
                "Domestic markets closed higher, supported by gains in "
                "major sectors and steady investor activity. Analysts said "
                "future movement will depend on economic data and global "
                "market conditions."
            ),
            category=NewsCategory.BUSINESS,
            score=69.5,
            confidence=77.0,
            region="India",
            publisher="Bahuvu Business Desk",
            published_hour=10,
        ),
        _make_sample_article(
            article_id="article_rejected",
            title="Low Priority Test Story",
            summary="This story should not enter the generated bulletin.",
            content="This story exists only to test the minimum score filter.",
            category=NewsCategory.OTHER,
            score=25.0,
            confidence=30.0,
            region="",
            publisher="Test Publisher",
            published_hour=11,
        ),
    ]


def run_self_test() -> None:
    """Run deterministic module checks and write sample outputs."""

    print("=" * 70)
    print(MODULE_NAME)
    print(f"Version: {MODULE_VERSION}")
    print("=" * 70)

    config = ScriptGeneratorConfig(
        max_stories=10,
        max_headlines=5,
        minimum_score=50.0,
        words_per_minute=145,
        output_directory=OUTPUT_DIRECTORY,
    )

    articles = _build_sample_articles()

    bulletin = generate_bulletin(
        articles=articles,
        config=config,
        write_outputs=True,
        bulletin_date="2026-07-11",
    )

    output_paths = BulletinOutputPaths(
        text_path=config.output_directory / config.text_filename,
        json_path=config.output_directory / config.json_filename,
        metadata_path=config.output_directory / config.metadata_filename,
    )

    assert bulletin.title == DEFAULT_BULLETIN_TITLE
    assert bulletin.edition == DEFAULT_EDITION_NAME
    assert bulletin.statistics.input_articles == 6
    assert bulletin.statistics.eligible_articles == 5
    assert bulletin.statistics.selected_articles == 5
    assert bulletin.statistics.rejected_articles == 1
    assert bulletin.statistics.headlines == 5
    assert bulletin.statistics.sections >= 4
    assert bulletin.statistics.total_words > 100
    assert bulletin.statistics.estimated_seconds > 0

    assert bulletin.sections[0].section_type is BulletinSectionType.LEAD
    assert bulletin.sections[0].stories[0].role is StoryRole.LEAD
    assert bulletin.sections[0].stories[0].article_id == "article_lead"

    assert output_paths.text_path.exists()
    assert output_paths.json_path.exists()
    assert output_paths.metadata_path.exists()

    print("Input articles:", bulletin.statistics.input_articles)
    print("Eligible articles:", bulletin.statistics.eligible_articles)
    print("Selected articles:", bulletin.statistics.selected_articles)
    print("Rejected articles:", bulletin.statistics.rejected_articles)
    print("Bulletin sections:", bulletin.statistics.sections)
    print("Script segments:", bulletin.statistics.segments)
    print("Headline count:", bulletin.statistics.headlines)
    print("Total words:", bulletin.statistics.total_words)
    print(
        "Estimated duration:",
        f"{bulletin.statistics.estimated_minutes:.2f} minutes",
    )
    print(
        "Average story score:",
        f"{bulletin.statistics.average_story_score:.2f}",
    )
    print("Lead story:", bulletin.sections[0].stories[0].headline)

    print("-" * 70)
    print("Created:", output_paths.text_path)
    print("Created:", output_paths.json_path)
    print("Created:", output_paths.metadata_path)
    print("-" * 70)

    preview = "\n".join(bulletin.full_script.splitlines()[:18])
    print("Bulletin preview:")
    print()
    print(textwrap.indent(preview, "  "))
    print()
    print("Broadcast script generator self-test passed.")
    print("=" * 70)


def main() -> None:
    """Module command-line entry point."""

    run_self_test()


if __name__ == "__main__":
    main()