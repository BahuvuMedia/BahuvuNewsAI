"""
BahuvuNewsAI - Canonical News Bulletin Model

This module defines the stable production contract shared by the editorial,
voice, graphics, video, thumbnail, and publishing stages.

Run:
    python -m news.bulletin
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import date, datetime, timezone
from enum import Enum
import json
import re
from pathlib import Path
from typing import Any, ClassVar, Iterable, Mapping, Sequence, TypeVar
from uuid import uuid4


T = TypeVar("T")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "_", prefix.lower()).strip("_") or "item"
    return f"{clean}_{uuid4().hex[:16]}"


def normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize_lines(value: str | None) -> str:
    if value is None:
        return ""
    lines = [normalize_text(line) for line in str(value).splitlines()]
    return "\n".join(line for line in lines if line)


def normalize_tags(values: Iterable[str] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        tag = normalize_text(value)
        if not tag:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(tag)
    return result


def ensure_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def enum_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def to_primitive(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return {item.name: to_primitive(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): to_primitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_primitive(item) for item in value]
    return value


def parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return ensure_aware(value)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return ensure_aware(parsed)


def parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


class BulletinError(ValueError):
    """Raised when bulletin data is structurally invalid."""


class ProductionStatus(str, Enum):
    DRAFT = "draft"
    SELECTED = "selected"
    SCRIPTED = "scripted"
    TRANSLATED = "translated"
    POLISHED = "polished"
    VOICED = "voiced"
    GRAPHICS_READY = "graphics_ready"
    VIDEO_READY = "video_ready"
    THUMBNAIL_READY = "thumbnail_ready"
    READY_TO_PUBLISH = "ready_to_publish"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    FAILED = "failed"
    ARCHIVED = "archived"


class StoryRole(str, Enum):
    LEAD = "lead"
    MAJOR = "major"
    STANDARD = "standard"
    BRIEF = "brief"
    CLOSING = "closing"


class SectionType(str, Enum):
    OPENING = "opening"
    HEADLINES = "headlines"
    NATIONAL = "national"
    STATE = "state"
    WORLD = "world"
    POLITICS = "politics"
    GOVERNANCE = "governance"
    BUSINESS = "business"
    TECHNOLOGY = "technology"
    SCIENCE = "science"
    HEALTH = "health"
    EDUCATION = "education"
    AGRICULTURE = "agriculture"
    WEATHER = "weather"
    SPORTS = "sports"
    ENTERTAINMENT = "entertainment"
    CULTURE = "culture"
    EXPLAINER = "explainer"
    FACTCHECK = "factcheck"
    CLOSING = "closing"
    OTHER = "other"


class ScriptLanguage(str, Enum):
    ENGLISH = "en"
    TELUGU = "te"
    HINDI = "hi"
    MIXED = "mixed"


class VoiceSegmentType(str, Enum):
    INTRO = "intro"
    HEADLINE = "headline"
    BODY = "body"
    TRANSITION = "transition"
    OUTRO = "outro"
    DISCLAIMER = "disclaimer"


class GraphicCueType(str, Enum):
    OPENING = "opening"
    TITLE_CARD = "title_card"
    HEADLINE = "headline"
    LOWER_THIRD = "lower_third"
    PHOTO = "photo"
    VIDEO = "video"
    MAP = "map"
    QUOTE = "quote"
    DATA = "data"
    SOURCE = "source"
    BREAKING = "breaking"
    TRANSITION = "transition"
    END_CARD = "end_card"


class VideoSegmentType(str, Enum):
    OPENING = "opening"
    STORY = "story"
    TRANSITION = "transition"
    PROMO = "promo"
    CLOSING = "closing"


class PublishVisibility(str, Enum):
    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"


class ValidationSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(slots=True)
class ValidationIssue:
    code: str
    message: str
    severity: ValidationSeverity = ValidationSeverity.ERROR
    path: str = ""

    def __post_init__(self) -> None:
        self.code = normalize_text(self.code)
        self.message = normalize_text(self.message)
        self.path = normalize_text(self.path)


@dataclass(slots=True)
class SourceReference:
    source_id: str = ""
    source_name: str = ""
    publisher: str = ""
    article_url: str = ""
    canonical_url: str = ""
    author: str = ""
    published_at: datetime | None = None
    retrieved_at: datetime | None = None
    reliability_score: float = 0.0
    is_primary: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        self.source_id = normalize_text(self.source_id)
        self.source_name = normalize_text(self.source_name)
        self.publisher = normalize_text(self.publisher)
        self.article_url = normalize_text(self.article_url)
        self.canonical_url = normalize_text(self.canonical_url)
        self.author = normalize_text(self.author)
        self.notes = normalize_lines(self.notes)
        self.published_at = ensure_aware(self.published_at)
        self.retrieved_at = ensure_aware(self.retrieved_at)
        self.reliability_score = max(0.0, min(100.0, float(self.reliability_score)))


@dataclass(slots=True)
class AnchorScript:
    language: ScriptLanguage = ScriptLanguage.ENGLISH
    headline: str = ""
    intro: str = ""
    body: str = ""
    outro: str = ""
    pronunciation_notes: dict[str, str] = field(default_factory=dict)
    fact_notes: list[str] = field(default_factory=list)
    estimated_words_per_minute: int = 135
    version: int = 1
    approved: bool = False
    approved_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.language, ScriptLanguage):
            self.language = ScriptLanguage(str(self.language))
        self.headline = normalize_text(self.headline)
        self.intro = normalize_lines(self.intro)
        self.body = normalize_lines(self.body)
        self.outro = normalize_lines(self.outro)
        self.pronunciation_notes = {
            normalize_text(k): normalize_text(v)
            for k, v in self.pronunciation_notes.items()
            if normalize_text(k) and normalize_text(v)
        }
        self.fact_notes = normalize_tags(self.fact_notes)
        self.estimated_words_per_minute = max(60, min(240, int(self.estimated_words_per_minute)))
        self.version = max(1, int(self.version))
        self.approved_at = ensure_aware(self.approved_at)
        if self.approved and self.approved_at is None:
            self.approved_at = utc_now()

    @property
    def full_text(self) -> str:
        return "\n\n".join(part for part in (self.intro, self.body, self.outro) if part)

    @property
    def word_count(self) -> int:
        return len(re.findall(r"\S+", self.full_text))

    @property
    def estimated_duration_seconds(self) -> float:
        if not self.word_count:
            return 0.0
        return round((self.word_count / self.estimated_words_per_minute) * 60.0, 2)


@dataclass(slots=True)
class VoiceSegment:
    id: str = field(default_factory=lambda: new_id("voice"))
    story_id: str = ""
    segment_type: VoiceSegmentType = VoiceSegmentType.BODY
    language: ScriptLanguage = ScriptLanguage.TELUGU
    text: str = ""
    voice_name: str = ""
    rate: str = "+0%"
    pitch: str = "+0Hz"
    volume: str = "+0%"
    audio_path: str = ""
    duration_seconds: float = 0.0
    start_seconds: float = 0.0
    end_seconds: float = 0.0
    checksum: str = ""
    status: ProductionStatus = ProductionStatus.DRAFT
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = normalize_text(self.id) or new_id("voice")
        self.story_id = normalize_text(self.story_id)
        if not isinstance(self.segment_type, VoiceSegmentType):
            self.segment_type = VoiceSegmentType(str(self.segment_type))
        if not isinstance(self.language, ScriptLanguage):
            self.language = ScriptLanguage(str(self.language))
        if not isinstance(self.status, ProductionStatus):
            self.status = ProductionStatus(str(self.status))
        self.text = normalize_lines(self.text)
        self.voice_name = normalize_text(self.voice_name)
        self.audio_path = normalize_text(self.audio_path)
        self.checksum = normalize_text(self.checksum)
        self.duration_seconds = max(0.0, float(self.duration_seconds))
        self.start_seconds = max(0.0, float(self.start_seconds))
        self.end_seconds = max(0.0, float(self.end_seconds))
        if self.end_seconds == 0.0 and self.duration_seconds:
            self.end_seconds = self.start_seconds + self.duration_seconds


@dataclass(slots=True)
class GraphicCue:
    id: str = field(default_factory=lambda: new_id("graphic"))
    story_id: str = ""
    cue_type: GraphicCueType = GraphicCueType.HEADLINE
    start_seconds: float = 0.0
    duration_seconds: float = 0.0
    headline: str = ""
    subheadline: str = ""
    body: str = ""
    category_label: str = ""
    location_label: str = ""
    source_label: str = ""
    media_path: str = ""
    output_path: str = ""
    template_name: str = "default"
    priority: int = 50
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = normalize_text(self.id) or new_id("graphic")
        self.story_id = normalize_text(self.story_id)
        if not isinstance(self.cue_type, GraphicCueType):
            self.cue_type = GraphicCueType(str(self.cue_type))
        self.start_seconds = max(0.0, float(self.start_seconds))
        self.duration_seconds = max(0.0, float(self.duration_seconds))
        self.headline = normalize_text(self.headline)
        self.subheadline = normalize_text(self.subheadline)
        self.body = normalize_lines(self.body)
        self.category_label = normalize_text(self.category_label)
        self.location_label = normalize_text(self.location_label)
        self.source_label = normalize_text(self.source_label)
        self.media_path = normalize_text(self.media_path)
        self.output_path = normalize_text(self.output_path)
        self.template_name = normalize_text(self.template_name) or "default"
        self.priority = max(0, min(100, int(self.priority)))


@dataclass(slots=True)
class VideoSegment:
    id: str = field(default_factory=lambda: new_id("video"))
    story_id: str = ""
    segment_type: VideoSegmentType = VideoSegmentType.STORY
    title: str = ""
    start_seconds: float = 0.0
    duration_seconds: float = 0.0
    audio_path: str = ""
    visual_paths: list[str] = field(default_factory=list)
    subtitle_path: str = ""
    output_path: str = ""
    transition_in: str = "fade"
    transition_out: str = "fade"
    status: ProductionStatus = ProductionStatus.DRAFT
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = normalize_text(self.id) or new_id("video")
        self.story_id = normalize_text(self.story_id)
        if not isinstance(self.segment_type, VideoSegmentType):
            self.segment_type = VideoSegmentType(str(self.segment_type))
        if not isinstance(self.status, ProductionStatus):
            self.status = ProductionStatus(str(self.status))
        self.title = normalize_text(self.title)
        self.start_seconds = max(0.0, float(self.start_seconds))
        self.duration_seconds = max(0.0, float(self.duration_seconds))
        self.audio_path = normalize_text(self.audio_path)
        self.visual_paths = [normalize_text(path) for path in self.visual_paths if normalize_text(path)]
        self.subtitle_path = normalize_text(self.subtitle_path)
        self.output_path = normalize_text(self.output_path)
        self.transition_in = normalize_text(self.transition_in) or "fade"
        self.transition_out = normalize_text(self.transition_out) or "fade"


@dataclass(slots=True)
class ThumbnailMetadata:
    headline: str = ""
    subheadline: str = ""
    category_label: str = ""
    image_path: str = ""
    output_path: str = ""
    template_name: str = "default"
    generated: bool = False
    approved: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.headline = normalize_text(self.headline)
        self.subheadline = normalize_text(self.subheadline)
        self.category_label = normalize_text(self.category_label)
        self.image_path = normalize_text(self.image_path)
        self.output_path = normalize_text(self.output_path)
        self.template_name = normalize_text(self.template_name) or "default"


@dataclass(slots=True)
class PublishingMetadata:
    platform: str = "youtube"
    title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    category_id: str = "25"
    visibility: PublishVisibility = PublishVisibility.PRIVATE
    language: ScriptLanguage = ScriptLanguage.TELUGU
    scheduled_at: datetime | None = None
    made_for_kids: bool = False
    contains_paid_promotion: bool = False
    playlist_ids: list[str] = field(default_factory=list)
    video_id: str = ""
    video_url: str = ""
    published_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.platform = normalize_text(self.platform) or "youtube"
        self.title = normalize_text(self.title)
        self.description = normalize_lines(self.description)
        self.tags = normalize_tags(self.tags)
        self.category_id = normalize_text(self.category_id) or "25"
        if not isinstance(self.visibility, PublishVisibility):
            self.visibility = PublishVisibility(str(self.visibility))
        if not isinstance(self.language, ScriptLanguage):
            self.language = ScriptLanguage(str(self.language))
        self.scheduled_at = ensure_aware(self.scheduled_at)
        self.playlist_ids = normalize_tags(self.playlist_ids)
        self.video_id = normalize_text(self.video_id)
        self.video_url = normalize_text(self.video_url)
        self.published_at = ensure_aware(self.published_at)


@dataclass(slots=True)
class ProductionRecord:
    stage: str
    status: ProductionStatus
    updated_at: datetime = field(default_factory=utc_now)
    message: str = ""
    artifact_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.stage = normalize_text(self.stage)
        if not isinstance(self.status, ProductionStatus):
            self.status = ProductionStatus(str(self.status))
        self.updated_at = ensure_aware(self.updated_at) or utc_now()
        self.message = normalize_text(self.message)
        self.artifact_path = normalize_text(self.artifact_path)


@dataclass(slots=True)
class BulletinStory:
    id: str = field(default_factory=lambda: new_id("story"))
    article_id: str = ""
    rank: int = 0
    role: StoryRole = StoryRole.STANDARD
    section: SectionType = SectionType.OTHER
    category: str = ""
    region: str = ""
    language: ScriptLanguage = ScriptLanguage.ENGLISH
    original_title: str = ""
    original_summary: str = ""
    original_content: str = ""
    editorial_headline: str = ""
    editorial_summary: str = ""
    key_facts: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    score: float = 0.0
    confidence: float = 0.0
    selected_reason: str = ""
    image_url: str = ""
    image_path: str = ""
    sources: list[SourceReference] = field(default_factory=list)
    scripts: dict[str, AnchorScript] = field(default_factory=dict)
    voice_segments: list[VoiceSegment] = field(default_factory=list)
    graphic_cues: list[GraphicCue] = field(default_factory=list)
    video_segment: VideoSegment | None = None
    status: ProductionStatus = ProductionStatus.SELECTED
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = normalize_text(self.id) or new_id("story")
        self.article_id = normalize_text(self.article_id)
        self.rank = max(0, int(self.rank))
        if not isinstance(self.role, StoryRole):
            self.role = StoryRole(str(self.role))
        if not isinstance(self.section, SectionType):
            self.section = SectionType(str(self.section))
        if not isinstance(self.language, ScriptLanguage):
            self.language = ScriptLanguage(str(self.language))
        if not isinstance(self.status, ProductionStatus):
            self.status = ProductionStatus(str(self.status))
        self.category = normalize_text(self.category)
        self.region = normalize_text(self.region)
        self.original_title = normalize_text(self.original_title)
        self.original_summary = normalize_lines(self.original_summary)
        self.original_content = normalize_lines(self.original_content)
        self.editorial_headline = normalize_text(self.editorial_headline)
        self.editorial_summary = normalize_lines(self.editorial_summary)
        self.key_facts = normalize_tags(self.key_facts)
        self.keywords = normalize_tags(self.keywords)
        self.tags = normalize_tags(self.tags)
        self.score = max(0.0, min(100.0, float(self.score)))
        self.confidence = max(0.0, min(100.0, float(self.confidence)))
        self.selected_reason = normalize_lines(self.selected_reason)
        self.image_url = normalize_text(self.image_url)
        self.image_path = normalize_text(self.image_path)
        self.scripts = {str(key): value for key, value in self.scripts.items()}

    @property
    def headline(self) -> str:
        return self.editorial_headline or self.original_title

    @property
    def primary_source(self) -> SourceReference | None:
        for source in self.sources:
            if source.is_primary:
                return source
        return self.sources[0] if self.sources else None

    def add_script(self, script: AnchorScript) -> None:
        self.scripts[script.language.value] = script

    def get_script(self, language: ScriptLanguage | str) -> AnchorScript | None:
        key = enum_value(language)
        return self.scripts.get(str(key))

    def validate(self, path: str = "story") -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not self.id:
            issues.append(ValidationIssue("story.id_missing", "Story ID is required.", path=f"{path}.id"))
        if not self.headline:
            issues.append(ValidationIssue("story.headline_missing", "Story headline is required.", path=f"{path}.headline"))
        if not self.sources:
            issues.append(ValidationIssue("story.sources_missing", "At least one source is required.", path=f"{path}.sources"))
        if self.rank < 1:
            issues.append(ValidationIssue("story.rank_invalid", "Story rank should start at 1.", ValidationSeverity.WARNING, f"{path}.rank"))
        if self.status in {ProductionStatus.SCRIPTED, ProductionStatus.TRANSLATED, ProductionStatus.POLISHED} and not self.scripts:
            issues.append(ValidationIssue("story.script_missing", "A scripted story must contain at least one script.", path=f"{path}.scripts"))
        if self.status == ProductionStatus.VOICED and not self.voice_segments:
            issues.append(ValidationIssue("story.voice_missing", "A voiced story must contain voice segments.", path=f"{path}.voice_segments"))
        return issues


@dataclass(slots=True)
class BulletinSection:
    id: str = field(default_factory=lambda: new_id("section"))
    section_type: SectionType = SectionType.OTHER
    title: str = ""
    order: int = 0
    intro_script: str = ""
    outro_script: str = ""
    story_ids: list[str] = field(default_factory=list)
    target_duration_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = normalize_text(self.id) or new_id("section")
        if not isinstance(self.section_type, SectionType):
            self.section_type = SectionType(str(self.section_type))
        self.title = normalize_text(self.title)
        self.order = max(0, int(self.order))
        self.intro_script = normalize_lines(self.intro_script)
        self.outro_script = normalize_lines(self.outro_script)
        self.story_ids = normalize_tags(self.story_ids)
        self.target_duration_seconds = max(0.0, float(self.target_duration_seconds))


@dataclass(slots=True)
class NewsBulletin:
    SCHEMA_VERSION: ClassVar[str] = "1.0"

    id: str = field(default_factory=lambda: new_id("bulletin"))
    title: str = ""
    edition_name: str = ""
    edition_date: date = field(default_factory=date.today)
    language: ScriptLanguage = ScriptLanguage.TELUGU
    region: str = "India"
    timezone_name: str = "Asia/Kolkata"
    status: ProductionStatus = ProductionStatus.DRAFT
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    stories: list[BulletinStory] = field(default_factory=list)
    sections: list[BulletinSection] = field(default_factory=list)
    opening_script: str = ""
    closing_script: str = ""
    voice_segments: list[VoiceSegment] = field(default_factory=list)
    graphic_cues: list[GraphicCue] = field(default_factory=list)
    video_segments: list[VideoSegment] = field(default_factory=list)
    thumbnail: ThumbnailMetadata = field(default_factory=ThumbnailMetadata)
    publishing: PublishingMetadata = field(default_factory=PublishingMetadata)
    production_history: list[ProductionRecord] = field(default_factory=list)
    final_video_path: str = ""
    subtitle_path: str = ""
    duration_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = normalize_text(self.id) or new_id("bulletin")
        self.title = normalize_text(self.title)
        self.edition_name = normalize_text(self.edition_name)
        self.edition_date = parse_date(self.edition_date) or date.today()
        if not isinstance(self.language, ScriptLanguage):
            self.language = ScriptLanguage(str(self.language))
        if not isinstance(self.status, ProductionStatus):
            self.status = ProductionStatus(str(self.status))
        self.region = normalize_text(self.region) or "India"
        self.timezone_name = normalize_text(self.timezone_name) or "Asia/Kolkata"
        self.created_at = ensure_aware(self.created_at) or utc_now()
        self.updated_at = ensure_aware(self.updated_at) or utc_now()
        self.opening_script = normalize_lines(self.opening_script)
        self.closing_script = normalize_lines(self.closing_script)
        self.final_video_path = normalize_text(self.final_video_path)
        self.subtitle_path = normalize_text(self.subtitle_path)
        self.duration_seconds = max(0.0, float(self.duration_seconds))
        self._recalculate_ranks()

    @property
    def story_count(self) -> int:
        return len(self.stories)

    @property
    def lead_story(self) -> BulletinStory | None:
        for story in self.stories:
            if story.role == StoryRole.LEAD:
                return story
        return self.stories[0] if self.stories else None

    @property
    def production_ready(self) -> bool:
        return not any(issue.severity == ValidationSeverity.ERROR for issue in self.validate(for_publication=True))

    def touch(self) -> None:
        self.updated_at = utc_now()

    def _recalculate_ranks(self) -> None:
        self.stories.sort(key=lambda story: (story.rank or 10**9, -story.score, story.id))
        for index, story in enumerate(self.stories, start=1):
            story.rank = index

    def add_story(self, story: BulletinStory) -> None:
        if any(existing.id == story.id for existing in self.stories):
            raise BulletinError(f"Duplicate story ID: {story.id}")
        self.stories.append(story)
        self._recalculate_ranks()
        self.touch()

    def remove_story(self, story_id: str) -> BulletinStory:
        for index, story in enumerate(self.stories):
            if story.id == story_id:
                removed = self.stories.pop(index)
                self._recalculate_ranks()
                for section in self.sections:
                    section.story_ids = [item for item in section.story_ids if item != story_id]
                self.touch()
                return removed
        raise BulletinError(f"Story not found: {story_id}")

    def get_story(self, story_id: str) -> BulletinStory | None:
        return next((story for story in self.stories if story.id == story_id), None)

    def set_status(
        self,
        status: ProductionStatus | str,
        *,
        stage: str = "bulletin",
        message: str = "",
        artifact_path: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        new_status = status if isinstance(status, ProductionStatus) else ProductionStatus(str(status))
        self.status = new_status
        self.production_history.append(
            ProductionRecord(
                stage=stage,
                status=new_status,
                message=message,
                artifact_path=artifact_path,
                metadata=dict(metadata or {}),
            )
        )
        self.touch()

    def rebuild_sections(self) -> None:
        grouped: dict[SectionType, list[BulletinStory]] = {}
        for story in self.stories:
            grouped.setdefault(story.section, []).append(story)
        self.sections = []
        for order, (section_type, stories) in enumerate(grouped.items(), start=1):
            self.sections.append(
                BulletinSection(
                    section_type=section_type,
                    title=section_type.value.replace("_", " ").title(),
                    order=order,
                    story_ids=[story.id for story in stories],
                )
            )
        self.touch()

    def validate(self, *, for_publication: bool = False) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not self.id:
            issues.append(ValidationIssue("bulletin.id_missing", "Bulletin ID is required.", path="id"))
        if not self.title:
            issues.append(ValidationIssue("bulletin.title_missing", "Bulletin title is required.", path="title"))
        if not self.stories:
            issues.append(ValidationIssue("bulletin.stories_missing", "At least one story is required.", path="stories"))

        seen_ids: set[str] = set()
        for index, story in enumerate(self.stories):
            if story.id in seen_ids:
                issues.append(ValidationIssue("bulletin.duplicate_story", f"Duplicate story ID: {story.id}", path=f"stories[{index}].id"))
            seen_ids.add(story.id)
            issues.extend(story.validate(path=f"stories[{index}]"))

        section_story_ids = {story_id for section in self.sections for story_id in section.story_ids}
        unknown_ids = section_story_ids - seen_ids
        for story_id in sorted(unknown_ids):
            issues.append(ValidationIssue("section.unknown_story", f"Section references unknown story: {story_id}", path="sections"))

        if for_publication:
            if not self.final_video_path:
                issues.append(ValidationIssue("publication.video_missing", "Final video path is required.", path="final_video_path"))
            if not self.thumbnail.output_path:
                issues.append(ValidationIssue("publication.thumbnail_missing", "Thumbnail output path is required.", path="thumbnail.output_path"))
            if not self.publishing.title:
                issues.append(ValidationIssue("publication.title_missing", "Publishing title is required.", path="publishing.title"))
            if not self.publishing.description:
                issues.append(ValidationIssue("publication.description_missing", "Publishing description is required.", path="publishing.description"))
            for index, story in enumerate(self.stories):
                script = story.get_script(self.language)
                if script is None or not script.full_text:
                    issues.append(ValidationIssue("publication.script_missing", f"Story {story.id} has no {self.language.value} script.", path=f"stories[{index}].scripts"))

        return issues

    def assert_valid(self, *, for_publication: bool = False) -> None:
        errors = [issue for issue in self.validate(for_publication=for_publication) if issue.severity == ValidationSeverity.ERROR]
        if errors:
            message = "; ".join(f"{issue.code}: {issue.message}" for issue in errors)
            raise BulletinError(message)

    def to_dict(self) -> dict[str, Any]:
        payload = to_primitive(self)
        payload["schema_version"] = self.SCHEMA_VERSION
        return payload

    def to_json(self, *, indent: int = 2, ensure_ascii: bool = False) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=ensure_ascii, sort_keys=False)

    def save_json(self, path: str | Path) -> Path:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(self.to_json(), encoding="utf-8")
        return output_path

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NewsBulletin":
        stories = [story_from_dict(item) for item in data.get("stories", [])]
        sections = [section_from_dict(item) for item in data.get("sections", [])]
        return cls(
            id=data.get("id", new_id("bulletin")),
            title=data.get("title", ""),
            edition_name=data.get("edition_name", ""),
            edition_date=parse_date(data.get("edition_date")) or date.today(),
            language=ScriptLanguage(data.get("language", ScriptLanguage.TELUGU.value)),
            region=data.get("region", "India"),
            timezone_name=data.get("timezone_name", "Asia/Kolkata"),
            status=ProductionStatus(data.get("status", ProductionStatus.DRAFT.value)),
            created_at=parse_datetime(data.get("created_at")) or utc_now(),
            updated_at=parse_datetime(data.get("updated_at")) or utc_now(),
            stories=stories,
            sections=sections,
            opening_script=data.get("opening_script", ""),
            closing_script=data.get("closing_script", ""),
            voice_segments=[voice_from_dict(item) for item in data.get("voice_segments", [])],
            graphic_cues=[graphic_from_dict(item) for item in data.get("graphic_cues", [])],
            video_segments=[video_from_dict(item) for item in data.get("video_segments", [])],
            thumbnail=thumbnail_from_dict(data.get("thumbnail", {})),
            publishing=publishing_from_dict(data.get("publishing", {})),
            production_history=[production_record_from_dict(item) for item in data.get("production_history", [])],
            final_video_path=data.get("final_video_path", ""),
            subtitle_path=data.get("subtitle_path", ""),
            duration_seconds=data.get("duration_seconds", 0.0),
            metadata=dict(data.get("metadata", {})),
        )

    @classmethod
    def load_json(cls, path: str | Path) -> "NewsBulletin":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise BulletinError("Bulletin JSON root must be an object.")
        return cls.from_dict(payload)


def source_from_dict(data: Mapping[str, Any]) -> SourceReference:
    return SourceReference(
        source_id=data.get("source_id", ""), source_name=data.get("source_name", ""),
        publisher=data.get("publisher", ""), article_url=data.get("article_url", ""),
        canonical_url=data.get("canonical_url", ""), author=data.get("author", ""),
        published_at=parse_datetime(data.get("published_at")), retrieved_at=parse_datetime(data.get("retrieved_at")),
        reliability_score=data.get("reliability_score", 0.0), is_primary=bool(data.get("is_primary", False)),
        notes=data.get("notes", ""),
    )


def script_from_dict(data: Mapping[str, Any]) -> AnchorScript:
    return AnchorScript(
        language=ScriptLanguage(data.get("language", ScriptLanguage.ENGLISH.value)),
        headline=data.get("headline", ""), intro=data.get("intro", ""), body=data.get("body", ""),
        outro=data.get("outro", ""), pronunciation_notes=dict(data.get("pronunciation_notes", {})),
        fact_notes=list(data.get("fact_notes", [])), estimated_words_per_minute=data.get("estimated_words_per_minute", 135),
        version=data.get("version", 1), approved=bool(data.get("approved", False)),
        approved_at=parse_datetime(data.get("approved_at")),
    )


def voice_from_dict(data: Mapping[str, Any]) -> VoiceSegment:
    return VoiceSegment(
        id=data.get("id", new_id("voice")), story_id=data.get("story_id", ""),
        segment_type=VoiceSegmentType(data.get("segment_type", VoiceSegmentType.BODY.value)),
        language=ScriptLanguage(data.get("language", ScriptLanguage.TELUGU.value)), text=data.get("text", ""),
        voice_name=data.get("voice_name", ""), rate=data.get("rate", "+0%"), pitch=data.get("pitch", "+0Hz"),
        volume=data.get("volume", "+0%"), audio_path=data.get("audio_path", ""),
        duration_seconds=data.get("duration_seconds", 0.0), start_seconds=data.get("start_seconds", 0.0),
        end_seconds=data.get("end_seconds", 0.0), checksum=data.get("checksum", ""),
        status=ProductionStatus(data.get("status", ProductionStatus.DRAFT.value)), metadata=dict(data.get("metadata", {})),
    )


def graphic_from_dict(data: Mapping[str, Any]) -> GraphicCue:
    return GraphicCue(
        id=data.get("id", new_id("graphic")), story_id=data.get("story_id", ""),
        cue_type=GraphicCueType(data.get("cue_type", GraphicCueType.HEADLINE.value)),
        start_seconds=data.get("start_seconds", 0.0), duration_seconds=data.get("duration_seconds", 0.0),
        headline=data.get("headline", ""), subheadline=data.get("subheadline", ""), body=data.get("body", ""),
        category_label=data.get("category_label", ""), location_label=data.get("location_label", ""),
        source_label=data.get("source_label", ""), media_path=data.get("media_path", ""),
        output_path=data.get("output_path", ""), template_name=data.get("template_name", "default"),
        priority=data.get("priority", 50), metadata=dict(data.get("metadata", {})),
    )


def video_from_dict(data: Mapping[str, Any]) -> VideoSegment:
    return VideoSegment(
        id=data.get("id", new_id("video")), story_id=data.get("story_id", ""),
        segment_type=VideoSegmentType(data.get("segment_type", VideoSegmentType.STORY.value)),
        title=data.get("title", ""), start_seconds=data.get("start_seconds", 0.0),
        duration_seconds=data.get("duration_seconds", 0.0), audio_path=data.get("audio_path", ""),
        visual_paths=list(data.get("visual_paths", [])), subtitle_path=data.get("subtitle_path", ""),
        output_path=data.get("output_path", ""), transition_in=data.get("transition_in", "fade"),
        transition_out=data.get("transition_out", "fade"),
        status=ProductionStatus(data.get("status", ProductionStatus.DRAFT.value)), metadata=dict(data.get("metadata", {})),
    )


def thumbnail_from_dict(data: Mapping[str, Any]) -> ThumbnailMetadata:
    return ThumbnailMetadata(
        headline=data.get("headline", ""), subheadline=data.get("subheadline", ""),
        category_label=data.get("category_label", ""), image_path=data.get("image_path", ""),
        output_path=data.get("output_path", ""), template_name=data.get("template_name", "default"),
        generated=bool(data.get("generated", False)), approved=bool(data.get("approved", False)),
        metadata=dict(data.get("metadata", {})),
    )


def publishing_from_dict(data: Mapping[str, Any]) -> PublishingMetadata:
    return PublishingMetadata(
        platform=data.get("platform", "youtube"), title=data.get("title", ""),
        description=data.get("description", ""), tags=list(data.get("tags", [])),
        category_id=data.get("category_id", "25"),
        visibility=PublishVisibility(data.get("visibility", PublishVisibility.PRIVATE.value)),
        language=ScriptLanguage(data.get("language", ScriptLanguage.TELUGU.value)),
        scheduled_at=parse_datetime(data.get("scheduled_at")), made_for_kids=bool(data.get("made_for_kids", False)),
        contains_paid_promotion=bool(data.get("contains_paid_promotion", False)),
        playlist_ids=list(data.get("playlist_ids", [])), video_id=data.get("video_id", ""),
        video_url=data.get("video_url", ""), published_at=parse_datetime(data.get("published_at")),
        metadata=dict(data.get("metadata", {})),
    )


def production_record_from_dict(data: Mapping[str, Any]) -> ProductionRecord:
    return ProductionRecord(
        stage=data.get("stage", ""), status=ProductionStatus(data.get("status", ProductionStatus.DRAFT.value)),
        updated_at=parse_datetime(data.get("updated_at")) or utc_now(), message=data.get("message", ""),
        artifact_path=data.get("artifact_path", ""), metadata=dict(data.get("metadata", {})),
    )


def story_from_dict(data: Mapping[str, Any]) -> BulletinStory:
    scripts = {str(key): script_from_dict(value) for key, value in dict(data.get("scripts", {})).items()}
    video_data = data.get("video_segment")
    return BulletinStory(
        id=data.get("id", new_id("story")), article_id=data.get("article_id", ""), rank=data.get("rank", 0),
        role=StoryRole(data.get("role", StoryRole.STANDARD.value)),
        section=SectionType(data.get("section", SectionType.OTHER.value)),
        category=data.get("category", ""), region=data.get("region", ""),
        language=ScriptLanguage(data.get("language", ScriptLanguage.ENGLISH.value)),
        original_title=data.get("original_title", ""), original_summary=data.get("original_summary", ""),
        original_content=data.get("original_content", ""), editorial_headline=data.get("editorial_headline", ""),
        editorial_summary=data.get("editorial_summary", ""), key_facts=list(data.get("key_facts", [])),
        keywords=list(data.get("keywords", [])), tags=list(data.get("tags", [])), score=data.get("score", 0.0),
        confidence=data.get("confidence", 0.0), selected_reason=data.get("selected_reason", ""),
        image_url=data.get("image_url", ""), image_path=data.get("image_path", ""),
        sources=[source_from_dict(item) for item in data.get("sources", [])], scripts=scripts,
        voice_segments=[voice_from_dict(item) for item in data.get("voice_segments", [])],
        graphic_cues=[graphic_from_dict(item) for item in data.get("graphic_cues", [])],
        video_segment=video_from_dict(video_data) if isinstance(video_data, Mapping) else None,
        status=ProductionStatus(data.get("status", ProductionStatus.SELECTED.value)), metadata=dict(data.get("metadata", {})),
    )


def section_from_dict(data: Mapping[str, Any]) -> BulletinSection:
    return BulletinSection(
        id=data.get("id", new_id("section")),
        section_type=SectionType(data.get("section_type", SectionType.OTHER.value)),
        title=data.get("title", ""), order=data.get("order", 0), intro_script=data.get("intro_script", ""),
        outro_script=data.get("outro_script", ""), story_ids=list(data.get("story_ids", [])),
        target_duration_seconds=data.get("target_duration_seconds", 0.0), metadata=dict(data.get("metadata", {})),
    )


def _build_sample_bulletin() -> NewsBulletin:
    source = SourceReference(
        source_id="sample_source",
        source_name="Bahuvu Test Source",
        publisher="Bahuvu News Test Desk",
        article_url="https://example.com/weather-story",
        canonical_url="https://example.com/weather-story",
        published_at=utc_now(),
        retrieved_at=utc_now(),
        reliability_score=92.0,
        is_primary=True,
    )
    telugu_script = AnchorScript(
        language=ScriptLanguage.TELUGU,
        headline="ఆంధ్రప్రదేశ్‌లో భారీ వర్షాల హెచ్చరిక",
        intro="నమస్కారం. బాహువు న్యూస్‌కు స్వాగతం.",
        body="ఆంధ్రప్రదేశ్‌లోని పలు జిల్లాలకు భారీ వర్షాల హెచ్చరిక జారీ అయింది. ప్రజలు అప్రమత్తంగా ఉండాలని అధికారులు సూచించారు.",
        outro="తాజా సమాచారానికి బాహువు న్యూస్‌ను అనుసరించండి.",
        approved=True,
    )
    story = BulletinStory(
        article_id="article_weather_001",
        rank=1,
        role=StoryRole.LEAD,
        section=SectionType.WEATHER,
        category="weather",
        region="Andhra Pradesh",
        original_title="Heavy Rain Alert Issued Across Andhra Pradesh Districts",
        editorial_headline="Heavy Rain Alert Across Andhra Pradesh",
        editorial_summary="Authorities advise residents to remain alert as heavy rainfall is forecast.",
        key_facts=["Heavy rainfall forecast", "Multiple districts affected", "Official safety advisory issued"],
        score=88.5,
        confidence=94.0,
        selected_reason="High public importance and immediate safety relevance.",
        sources=[source],
        status=ProductionStatus.POLISHED,
    )
    story.add_script(telugu_script)
    bulletin = NewsBulletin(
        title="BAHUVU NEWS - Telugu News Bulletin",
        edition_name="Daily Test Edition",
        language=ScriptLanguage.TELUGU,
        status=ProductionStatus.POLISHED,
        opening_script="బాహువు న్యూస్‌కు స్వాగతం.",
        closing_script="ఇది బాహువు న్యూస్.",
        stories=[story],
        thumbnail=ThumbnailMetadata(
            headline="భారీ వర్షాల హెచ్చరిక",
            category_label="WEATHER",
            output_path="outputs/thumbnails/sample_bulletin.png",
            generated=True,
        ),
        publishing=PublishingMetadata(
            title="ఆంధ్రప్రదేశ్‌లో భారీ వర్షాల హెచ్చరిక | BAHUVU NEWS",
            description="ఆంధ్రప్రదేశ్ వాతావరణ పరిస్థితులపై తాజా తెలుగు వార్తలు.",
            tags=["Bahuvu News", "Telugu News", "Andhra Pradesh", "Weather"],
            visibility=PublishVisibility.PRIVATE,
        ),
        final_video_path="outputs/videos/sample_bulletin.mp4",
    )
    bulletin.rebuild_sections()
    bulletin.set_status(ProductionStatus.POLISHED, stage="self_test", message="Sample bulletin prepared.")
    return bulletin


def _self_test() -> None:
    bulletin = _build_sample_bulletin()
    bulletin.assert_valid()

    json_text = bulletin.to_json()
    restored = NewsBulletin.from_dict(json.loads(json_text))
    restored.assert_valid()

    assert restored.id == bulletin.id
    assert restored.story_count == 1
    assert restored.lead_story is not None
    assert restored.lead_story.get_script(ScriptLanguage.TELUGU) is not None
    assert restored.sections[0].story_ids == [restored.lead_story.id]
    assert restored.to_dict()["schema_version"] == NewsBulletin.SCHEMA_VERSION

    publication_issues = restored.validate(for_publication=True)
    errors = [issue for issue in publication_issues if issue.severity == ValidationSeverity.ERROR]
    assert not errors, errors

    print("Canonical bulletin model initialized successfully.")
    print(f"Bulletin ID: {restored.id}")
    print(f"Edition: {restored.edition_name}")
    print(f"Stories: {restored.story_count}")
    print(f"Sections: {len(restored.sections)}")
    print(f"Lead story: {restored.lead_story.headline}")
    print(f"Language: {restored.language.value}")
    print(f"Status: {restored.status.value}")
    print(f"Production ready: {restored.production_ready}")
    print("Bulletin model self-test passed.")


if __name__ == "__main__":
    _self_test()