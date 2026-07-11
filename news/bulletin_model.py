"""
BahuvuNewsAI - Canonical Bulletin Production Models
====================================================

This module defines the stable data contract shared by the complete
BahuvuNewsAI production pipeline:

    Story Ranker
        -> Script Generator
        -> Telugu Translator
        -> Editorial Polisher
        -> Voice Generator
        -> Graphics Composer
        -> Video Composer
        -> Thumbnail Generator
        -> YouTube Publisher

The models in this file are intentionally independent of external
packages. They support:

- Strong validation
- JSON-safe serialization
- Deserialization
- Duration calculations
- Timeline calculations
- Script, voice, visual, and production metadata
- Deterministic identifiers
- Production-readiness checks
- A built-in self-test

This module must remain the canonical production contract. Downstream
modules should extend behaviour around these objects rather than
creating incompatible bulletin structures.
"""

from __future__ import annotations

import json
import math
import uuid

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_WORDS_PER_MINUTE = 135.0
DEFAULT_FRAME_RATE = 24
DEFAULT_VIDEO_WIDTH = 1280
DEFAULT_VIDEO_HEIGHT = 720
DEFAULT_LANGUAGE = "en"
DEFAULT_TIMEZONE = "Asia/Kolkata"

MIN_WORDS_PER_MINUTE = 60.0
MAX_WORDS_PER_MINUTE = 240.0

SUPPORTED_VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
}

SUPPORTED_AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".ogg",
}

SUPPORTED_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
}


# ============================================================================
# EXCEPTIONS
# ============================================================================


class BulletinModelError(ValueError):
    """Base exception for bulletin model failures."""


class BulletinValidationError(BulletinModelError):
    """Raised when a bulletin object fails validation."""


class BulletinSerializationError(BulletinModelError):
    """Raised when bulletin serialization or deserialization fails."""


# ============================================================================
# ENUMERATIONS
# ============================================================================


class BulletinStatus(str, Enum):
    """Lifecycle status of a news bulletin."""

    DRAFT = "draft"
    SCRIPTED = "scripted"
    TRANSLATED = "translated"
    POLISHED = "polished"
    VOICED = "voiced"
    GRAPHICS_READY = "graphics_ready"
    VIDEO_READY = "video_ready"
    APPROVED = "approved"
    PUBLISHED = "published"
    FAILED = "failed"


class StoryRole(str, Enum):
    """Editorial role of a story within a bulletin."""

    LEAD = "lead"
    MAJOR = "major"
    STANDARD = "standard"
    BRIEF = "brief"
    CLOSER = "closer"
    BACKUP = "backup"


class SegmentType(str, Enum):
    """Type of broadcast script segment."""

    OPENING = "opening"
    HEADLINES_INTRO = "headlines_intro"
    HEADLINE = "headline"
    STORY_INTRO = "story_intro"
    STORY_BODY = "story_body"
    QUOTE = "quote"
    CONTEXT = "context"
    TRANSITION = "transition"
    BREAK = "break"
    CLOSING = "closing"
    CREDIT = "credit"


class SegmentStatus(str, Enum):
    """Processing status of a script segment."""

    DRAFT = "draft"
    READY = "ready"
    TRANSLATED = "translated"
    POLISHED = "polished"
    VOICED = "voiced"
    REJECTED = "rejected"


class VoiceStyle(str, Enum):
    """Expected delivery style for generated speech."""

    NEUTRAL = "neutral"
    FORMAL = "formal"
    AUTHORITATIVE = "authoritative"
    URGENT = "urgent"
    WARM = "warm"
    SOMBER = "somber"
    ENERGETIC = "energetic"


class GraphicType(str, Enum):
    """Type of visual treatment requested for a segment."""

    NONE = "none"
    OPENING_CARD = "opening_card"
    HEADLINE_CARD = "headline_card"
    STORY_CARD = "story_card"
    FULLSCREEN_IMAGE = "fullscreen_image"
    LOWER_THIRD = "lower_third"
    QUOTE_CARD = "quote_card"
    DATA_CARD = "data_card"
    MAP = "map"
    CLOSING_CARD = "closing_card"
    LOGO = "logo"


class MediaType(str, Enum):
    """Kind of production media asset."""

    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    GRAPHIC = "graphic"
    DOCUMENT = "document"
    OTHER = "other"


class MarkerType(str, Enum):
    """Purpose of a production timeline marker."""

    BULLETIN_START = "bulletin_start"
    BULLETIN_END = "bulletin_end"
    STORY_START = "story_start"
    STORY_END = "story_end"
    SEGMENT_START = "segment_start"
    SEGMENT_END = "segment_end"
    GRAPHIC_IN = "graphic_in"
    GRAPHIC_OUT = "graphic_out"
    AUDIO_IN = "audio_in"
    AUDIO_OUT = "audio_out"
    CHAPTER = "chapter"
    CUSTOM = "custom"


class ProductionStage(str, Enum):
    """A production pipeline stage."""

    RANKING = "ranking"
    SCRIPTING = "scripting"
    TRANSLATION = "translation"
    POLISHING = "polishing"
    VOICE = "voice"
    GRAPHICS = "graphics"
    VIDEO = "video"
    THUMBNAIL = "thumbnail"
    PUBLISHING = "publishing"


# ============================================================================
# GENERAL UTILITIES
# ============================================================================


def utc_now_iso() -> str:
    """Return the current UTC time as a stable ISO-8601 string."""

    return datetime.now(timezone.utc).isoformat()


def generate_id(prefix: str) -> str:
    """Generate a readable unique identifier."""

    clean_prefix = str(prefix).strip().lower().replace(" ", "_")
    if not clean_prefix:
        clean_prefix = "item"

    return f"{clean_prefix}_{uuid.uuid4().hex}"


def normalize_text(value: Any) -> str:
    """Convert a value to normalized single-spaced text."""

    if value is None:
        return ""

    return " ".join(str(value).split()).strip()


def normalize_optional_text(value: Any) -> str | None:
    """Normalize optional text and return None when empty."""

    text = normalize_text(value)
    return text or None


def count_words(text: str) -> int:
    """Count whitespace-separated words in normalized text."""

    normalized = normalize_text(text)
    if not normalized:
        return 0

    return len(normalized.split(" "))


def estimate_speech_duration(
    text: str,
    words_per_minute: float = DEFAULT_WORDS_PER_MINUTE,
    minimum_seconds: float = 0.0,
) -> float:
    """
    Estimate spoken duration for text.

    Duration is calculated from normalized word count and reading speed.
    """

    if words_per_minute < MIN_WORDS_PER_MINUTE:
        raise BulletinValidationError(
            f"words_per_minute must be at least {MIN_WORDS_PER_MINUTE}."
        )

    if words_per_minute > MAX_WORDS_PER_MINUTE:
        raise BulletinValidationError(
            f"words_per_minute must not exceed {MAX_WORDS_PER_MINUTE}."
        )

    if minimum_seconds < 0:
        raise BulletinValidationError("minimum_seconds cannot be negative.")

    words = count_words(text)

    if words == 0:
        return round(float(minimum_seconds), 3)

    duration = (words / words_per_minute) * 60.0
    return round(max(duration, minimum_seconds), 3)


def ensure_non_negative(value: float, field_name: str) -> float:
    """Validate and normalize a non-negative numeric value."""

    try:
        normalized = float(value)
    except (TypeError, ValueError) as exc:
        raise BulletinValidationError(
            f"{field_name} must be numeric."
        ) from exc

    if not math.isfinite(normalized):
        raise BulletinValidationError(
            f"{field_name} must be finite."
        )

    if normalized < 0:
        raise BulletinValidationError(
            f"{field_name} cannot be negative."
        )

    return normalized


def ensure_probability(value: float, field_name: str) -> float:
    """Validate a score expressed from 0 to 100."""

    normalized = ensure_non_negative(value, field_name)

    if normalized > 100:
        raise BulletinValidationError(
            f"{field_name} cannot exceed 100."
        )

    return normalized


def enum_value(value: Any) -> Any:
    """Return the raw string value for an Enum object."""

    if isinstance(value, Enum):
        return value.value

    return value


def json_safe(value: Any) -> Any:
    """Recursively convert values into JSON-safe structures."""

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, datetime):
        return value.isoformat()

    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()

    if isinstance(value, Mapping):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [
            json_safe(item)
            for item in value
        ]

    return value


def parse_enum(
    enum_class: type[Enum],
    value: Any,
    field_name: str,
) -> Enum:
    """Parse an enum from either an enum instance or its stored value."""

    if isinstance(value, enum_class):
        return value

    try:
        return enum_class(str(value))
    except (TypeError, ValueError) as exc:
        valid_values = ", ".join(
            str(item.value)
            for item in enum_class
        )
        raise BulletinSerializationError(
            f"Invalid {field_name}: {value!r}. "
            f"Expected one of: {valid_values}."
        ) from exc


def unique_strings(values: Iterable[Any]) -> list[str]:
    """Normalize strings, preserve order, and remove duplicates."""

    results: list[str] = []
    seen: set[str] = set()

    for value in values:
        normalized = normalize_text(value)
        lookup_key = normalized.casefold()

        if normalized and lookup_key not in seen:
            results.append(normalized)
            seen.add(lookup_key)

    return results


# ============================================================================
# MEDIA ASSET
# ============================================================================


@dataclass(slots=True)
class MediaAsset:
    """A media item attached to a story or production stage."""

    id: str = field(default_factory=lambda: generate_id("asset"))
    media_type: MediaType = MediaType.OTHER
    source: str = ""
    local_path: str | None = None
    title: str | None = None
    description: str | None = None
    attribution: str | None = None
    license_name: str | None = None
    duration_seconds: float = 0.0
    width: int | None = None
    height: int | None = None
    checksum: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = normalize_text(self.id) or generate_id("asset")
        self.media_type = parse_enum(
            MediaType,
            self.media_type,
            "media_type",
        )
        self.source = normalize_text(self.source)
        self.local_path = normalize_optional_text(self.local_path)
        self.title = normalize_optional_text(self.title)
        self.description = normalize_optional_text(self.description)
        self.attribution = normalize_optional_text(self.attribution)
        self.license_name = normalize_optional_text(self.license_name)
        self.duration_seconds = ensure_non_negative(
            self.duration_seconds,
            "duration_seconds",
        )

        if self.width is not None:
            self.width = int(self.width)
            if self.width <= 0:
                raise BulletinValidationError(
                    "MediaAsset width must be positive."
                )

        if self.height is not None:
            self.height = int(self.height)
            if self.height <= 0:
                raise BulletinValidationError(
                    "MediaAsset height must be positive."
                )

        self.checksum = normalize_optional_text(self.checksum)
        self.metadata = dict(self.metadata or {})

        self.validate()

    @property
    def effective_path(self) -> str:
        """Return local path when present, otherwise source."""

        return self.local_path or self.source

    @property
    def extension(self) -> str:
        """Return the lower-case extension of the effective path."""

        return Path(self.effective_path).suffix.lower()

    def validate(self) -> None:
        """Validate the media asset."""

        if not self.source and not self.local_path:
            raise BulletinValidationError(
                "MediaAsset requires source or local_path."
            )

        extension = self.extension

        if extension:
            if (
                self.media_type is MediaType.IMAGE
                and extension not in SUPPORTED_IMAGE_EXTENSIONS
            ):
                raise BulletinValidationError(
                    f"Unsupported image extension: {extension}"
                )

            if (
                self.media_type is MediaType.AUDIO
                and extension not in SUPPORTED_AUDIO_EXTENSIONS
            ):
                raise BulletinValidationError(
                    f"Unsupported audio extension: {extension}"
                )

            if (
                self.media_type is MediaType.VIDEO
                and extension not in SUPPORTED_VIDEO_EXTENSIONS
            ):
                raise BulletinValidationError(
                    f"Unsupported video extension: {extension}"
                )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the media asset."""

        return json_safe(asdict(self))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MediaAsset:
        """Deserialize the media asset."""

        values = dict(data)
        values["media_type"] = parse_enum(
            MediaType,
            values.get("media_type", MediaType.OTHER),
            "media_type",
        )
        return cls(**values)


# ============================================================================
# VOICE CUE
# ============================================================================


@dataclass(slots=True)
class VoiceCue:
    """Voice-generation instructions for a script segment."""

    id: str = field(default_factory=lambda: generate_id("voice"))
    language: str = DEFAULT_LANGUAGE
    voice_name: str | None = None
    style: VoiceStyle = VoiceStyle.NEUTRAL
    rate: str = "+0%"
    pitch: str = "+0Hz"
    volume: str = "+0%"
    pause_before_seconds: float = 0.0
    pause_after_seconds: float = 0.0
    audio_path: str | None = None
    generated_duration_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = normalize_text(self.id) or generate_id("voice")
        self.language = normalize_text(self.language) or DEFAULT_LANGUAGE
        self.voice_name = normalize_optional_text(self.voice_name)
        self.style = parse_enum(
            VoiceStyle,
            self.style,
            "voice style",
        )
        self.rate = normalize_text(self.rate) or "+0%"
        self.pitch = normalize_text(self.pitch) or "+0Hz"
        self.volume = normalize_text(self.volume) or "+0%"
        self.pause_before_seconds = ensure_non_negative(
            self.pause_before_seconds,
            "pause_before_seconds",
        )
        self.pause_after_seconds = ensure_non_negative(
            self.pause_after_seconds,
            "pause_after_seconds",
        )
        self.audio_path = normalize_optional_text(self.audio_path)

        if self.generated_duration_seconds is not None:
            self.generated_duration_seconds = ensure_non_negative(
                self.generated_duration_seconds,
                "generated_duration_seconds",
            )

        self.metadata = dict(self.metadata or {})

    @property
    def total_pause_seconds(self) -> float:
        """Return total pauses associated with the voice cue."""

        return round(
            self.pause_before_seconds + self.pause_after_seconds,
            3,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the voice cue."""

        return json_safe(asdict(self))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> VoiceCue:
        """Deserialize the voice cue."""

        values = dict(data)
        values["style"] = parse_enum(
            VoiceStyle,
            values.get("style", VoiceStyle.NEUTRAL),
            "voice style",
        )
        return cls(**values)


# ============================================================================
# GRAPHIC CUE
# ============================================================================


@dataclass(slots=True)
class GraphicCue:
    """Visual instructions associated with a script segment."""

    id: str = field(default_factory=lambda: generate_id("graphic"))
    graphic_type: GraphicType = GraphicType.NONE
    headline: str | None = None
    subheadline: str | None = None
    category_label: str | None = None
    location_label: str | None = None
    image_path: str | None = None
    template_name: str | None = None
    show_logo: bool = True
    show_watermark: bool = True
    duration_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = normalize_text(self.id) or generate_id("graphic")
        self.graphic_type = parse_enum(
            GraphicType,
            self.graphic_type,
            "graphic_type",
        )
        self.headline = normalize_optional_text(self.headline)
        self.subheadline = normalize_optional_text(self.subheadline)
        self.category_label = normalize_optional_text(
            self.category_label
        )
        self.location_label = normalize_optional_text(
            self.location_label
        )
        self.image_path = normalize_optional_text(self.image_path)
        self.template_name = normalize_optional_text(
            self.template_name
        )
        self.show_logo = bool(self.show_logo)
        self.show_watermark = bool(self.show_watermark)

        if self.duration_seconds is not None:
            self.duration_seconds = ensure_non_negative(
                self.duration_seconds,
                "graphic duration_seconds",
            )

        self.metadata = dict(self.metadata or {})

    def to_dict(self) -> dict[str, Any]:
        """Serialize the graphic cue."""

        return json_safe(asdict(self))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GraphicCue:
        """Deserialize the graphic cue."""

        values = dict(data)
        values["graphic_type"] = parse_enum(
            GraphicType,
            values.get("graphic_type", GraphicType.NONE),
            "graphic_type",
        )
        return cls(**values)


# ============================================================================
# SCRIPT SEGMENT
# ============================================================================


@dataclass(slots=True)
class ScriptSegment:
    """An individually timed unit of a broadcast script."""

    id: str = field(default_factory=lambda: generate_id("segment"))
    segment_type: SegmentType = SegmentType.STORY_BODY
    text: str = ""
    language: str = DEFAULT_LANGUAGE
    order: int = 0
    status: SegmentStatus = SegmentStatus.DRAFT
    estimated_duration_seconds: float = 0.0
    actual_duration_seconds: float | None = None
    words_per_minute: float = DEFAULT_WORDS_PER_MINUTE
    voice_cue: VoiceCue = field(default_factory=VoiceCue)
    graphic_cue: GraphicCue = field(default_factory=GraphicCue)
    source_references: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = normalize_text(self.id) or generate_id("segment")
        self.segment_type = parse_enum(
            SegmentType,
            self.segment_type,
            "segment_type",
        )
        self.text = normalize_text(self.text)
        self.language = normalize_text(self.language) or DEFAULT_LANGUAGE
        self.order = int(self.order)

        if self.order < 0:
            raise BulletinValidationError(
                "ScriptSegment order cannot be negative."
            )

        self.status = parse_enum(
            SegmentStatus,
            self.status,
            "segment status",
        )

        self.words_per_minute = float(self.words_per_minute)

        if not isinstance(self.voice_cue, VoiceCue):
            self.voice_cue = VoiceCue.from_dict(self.voice_cue)

        if not isinstance(self.graphic_cue, GraphicCue):
            self.graphic_cue = GraphicCue.from_dict(
                self.graphic_cue
            )

        self.source_references = unique_strings(
            self.source_references
        )
        self.notes = unique_strings(self.notes)
        self.metadata = dict(self.metadata or {})

        calculated = estimate_speech_duration(
            self.text,
            self.words_per_minute,
        )

        supplied_duration = ensure_non_negative(
            self.estimated_duration_seconds,
            "estimated_duration_seconds",
        )

        self.estimated_duration_seconds = (
            supplied_duration
            if supplied_duration > 0
            else calculated
        )

        if self.actual_duration_seconds is not None:
            self.actual_duration_seconds = ensure_non_negative(
                self.actual_duration_seconds,
                "actual_duration_seconds",
            )

        self.validate()

    @property
    def word_count(self) -> int:
        """Return normalized word count."""

        return count_words(self.text)

    @property
    def speech_duration_seconds(self) -> float:
        """Return actual duration when available, otherwise estimated."""

        if self.actual_duration_seconds is not None:
            return round(self.actual_duration_seconds, 3)

        return round(self.estimated_duration_seconds, 3)

    @property
    def total_duration_seconds(self) -> float:
        """Return speech duration plus voice pauses."""

        return round(
            self.speech_duration_seconds
            + self.voice_cue.total_pause_seconds,
            3,
        )

    def recalculate_duration(
        self,
        words_per_minute: float | None = None,
    ) -> float:
        """Recalculate estimated reading duration."""

        if words_per_minute is not None:
            self.words_per_minute = float(words_per_minute)

        self.estimated_duration_seconds = estimate_speech_duration(
            self.text,
            self.words_per_minute,
        )

        return self.estimated_duration_seconds

    def validate(self) -> None:
        """Validate segment-level requirements."""

        text_optional_types = {
            SegmentType.BREAK,
        }

        if (
            not self.text
            and self.segment_type not in text_optional_types
        ):
            raise BulletinValidationError(
                f"{self.segment_type.value} segment requires text."
            )

        if (
            self.graphic_cue.duration_seconds is not None
            and self.graphic_cue.duration_seconds
            > self.total_duration_seconds + 10
        ):
            raise BulletinValidationError(
                "Graphic cue duration is unreasonably longer "
                "than its script segment."
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the script segment."""

        return {
            "id": self.id,
            "segment_type": self.segment_type.value,
            "text": self.text,
            "language": self.language,
            "order": self.order,
            "status": self.status.value,
            "estimated_duration_seconds": (
                self.estimated_duration_seconds
            ),
            "actual_duration_seconds": (
                self.actual_duration_seconds
            ),
            "words_per_minute": self.words_per_minute,
            "voice_cue": self.voice_cue.to_dict(),
            "graphic_cue": self.graphic_cue.to_dict(),
            "source_references": list(self.source_references),
            "notes": list(self.notes),
            "metadata": json_safe(self.metadata),
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> ScriptSegment:
        """Deserialize the script segment."""

        values = dict(data)
        values["segment_type"] = parse_enum(
            SegmentType,
            values.get("segment_type", SegmentType.STORY_BODY),
            "segment_type",
        )
        values["status"] = parse_enum(
            SegmentStatus,
            values.get("status", SegmentStatus.DRAFT),
            "segment status",
        )
        values["voice_cue"] = VoiceCue.from_dict(
            values.get("voice_cue", {})
        )
        values["graphic_cue"] = GraphicCue.from_dict(
            values.get("graphic_cue", {})
        )

        return cls(**values)


# ============================================================================
# BULLETIN STORY
# ============================================================================


@dataclass(slots=True)
class BulletinStory:
    """A ranked news story prepared for bulletin production."""

    id: str = field(default_factory=lambda: generate_id("story"))
    article_id: str = ""
    rank: int = 0
    role: StoryRole = StoryRole.STANDARD
    headline: str = ""
    short_headline: str | None = None
    summary: str = ""
    category: str = "other"
    region: str | None = None
    language: str = DEFAULT_LANGUAGE
    source_name: str | None = None
    source_url: str | None = None
    image_url: str | None = None
    editorial_score: float = 0.0
    confidence: float = 0.0
    priority: int = 0
    production_ready: bool = False
    segments: list[ScriptSegment] = field(default_factory=list)
    media_assets: list[MediaAsset] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    fact_notes: list[str] = field(default_factory=list)
    editorial_notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = normalize_text(self.id) or generate_id("story")
        self.article_id = normalize_text(self.article_id)
        self.rank = int(self.rank)

        if self.rank < 0:
            raise BulletinValidationError(
                "BulletinStory rank cannot be negative."
            )

        self.role = parse_enum(
            StoryRole,
            self.role,
            "story role",
        )
        self.headline = normalize_text(self.headline)
        self.short_headline = normalize_optional_text(
            self.short_headline
        )
        self.summary = normalize_text(self.summary)
        self.category = normalize_text(self.category) or "other"
        self.region = normalize_optional_text(self.region)
        self.language = normalize_text(self.language) or DEFAULT_LANGUAGE
        self.source_name = normalize_optional_text(
            self.source_name
        )
        self.source_url = normalize_optional_text(
            self.source_url
        )
        self.image_url = normalize_optional_text(self.image_url)
        self.editorial_score = ensure_probability(
            self.editorial_score,
            "editorial_score",
        )
        self.confidence = ensure_probability(
            self.confidence,
            "confidence",
        )
        self.priority = int(self.priority)

        if self.priority < 0:
            raise BulletinValidationError(
                "BulletinStory priority cannot be negative."
            )

        self.production_ready = bool(self.production_ready)

        self.segments = [
            segment
            if isinstance(segment, ScriptSegment)
            else ScriptSegment.from_dict(segment)
            for segment in self.segments
        ]

        self.media_assets = [
            asset
            if isinstance(asset, MediaAsset)
            else MediaAsset.from_dict(asset)
            for asset in self.media_assets
        ]

        self.keywords = unique_strings(self.keywords)
        self.tags = unique_strings(self.tags)
        self.fact_notes = unique_strings(self.fact_notes)
        self.editorial_notes = unique_strings(
            self.editorial_notes
        )
        self.metadata = dict(self.metadata or {})

        self.sort_segments()
        self.validate()

    @property
    def word_count(self) -> int:
        """Return total script word count for the story."""

        return sum(
            segment.word_count
            for segment in self.segments
        )

    @property
    def estimated_duration_seconds(self) -> float:
        """Return total story duration."""

        return round(
            sum(
                segment.total_duration_seconds
                for segment in self.segments
            ),
            3,
        )

    @property
    def script_text(self) -> str:
        """Return the complete story script in broadcast order."""

        return "\n\n".join(
            segment.text
            for segment in self.segments
            if segment.text
        )

    @property
    def has_voice(self) -> bool:
        """Return True when every spoken segment has generated audio."""

        spoken_segments = [
            segment
            for segment in self.segments
            if segment.text
        ]

        return bool(spoken_segments) and all(
            bool(segment.voice_cue.audio_path)
            for segment in spoken_segments
        )

    @property
    def has_visuals(self) -> bool:
        """Return True when the story has usable visual instructions."""

        has_segment_visuals = any(
            segment.graphic_cue.graphic_type
            is not GraphicType.NONE
            for segment in self.segments
        )

        return has_segment_visuals or bool(
            self.media_assets
            or self.image_url
        )

    def sort_segments(self) -> None:
        """Sort segments by order and assign stable missing orders."""

        self.segments.sort(
            key=lambda item: (
                item.order,
                item.id,
            )
        )

        used_orders: set[int] = set()

        for index, segment in enumerate(self.segments, start=1):
            if segment.order <= 0 or segment.order in used_orders:
                segment.order = index

            used_orders.add(segment.order)

        self.segments.sort(
            key=lambda item: (
                item.order,
                item.id,
            )
        )

    def add_segment(self, segment: ScriptSegment) -> None:
        """Add a segment and preserve ordering."""

        if not isinstance(segment, ScriptSegment):
            raise BulletinValidationError(
                "segment must be a ScriptSegment."
            )

        if any(
            existing.id == segment.id
            for existing in self.segments
        ):
            raise BulletinValidationError(
                f"Duplicate segment id: {segment.id}"
            )

        self.segments.append(segment)
        self.sort_segments()

    def validate(self) -> None:
        """Validate story-level requirements."""

        if not self.article_id:
            raise BulletinValidationError(
                "BulletinStory requires article_id."
            )

        if not self.headline:
            raise BulletinValidationError(
                "BulletinStory requires a headline."
            )

        segment_ids = [
            segment.id
            for segment in self.segments
        ]

        if len(segment_ids) != len(set(segment_ids)):
            raise BulletinValidationError(
                "BulletinStory contains duplicate segment IDs."
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the bulletin story."""

        return {
            "id": self.id,
            "article_id": self.article_id,
            "rank": self.rank,
            "role": self.role.value,
            "headline": self.headline,
            "short_headline": self.short_headline,
            "summary": self.summary,
            "category": self.category,
            "region": self.region,
            "language": self.language,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "image_url": self.image_url,
            "editorial_score": self.editorial_score,
            "confidence": self.confidence,
            "priority": self.priority,
            "production_ready": self.production_ready,
            "segments": [
                segment.to_dict()
                for segment in self.segments
            ],
            "media_assets": [
                asset.to_dict()
                for asset in self.media_assets
            ],
            "keywords": list(self.keywords),
            "tags": list(self.tags),
            "fact_notes": list(self.fact_notes),
            "editorial_notes": list(self.editorial_notes),
            "metadata": json_safe(self.metadata),
        }

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> BulletinStory:
        """Deserialize the bulletin story."""

        values = dict(data)
        values["role"] = parse_enum(
            StoryRole,
            values.get("role", StoryRole.STANDARD),
            "story role",
        )
        values["segments"] = [
            ScriptSegment.from_dict(segment)
            for segment in values.get("segments", [])
        ]
        values["media_assets"] = [
            MediaAsset.from_dict(asset)
            for asset in values.get("media_assets", [])
        ]

        return cls(**values)


# ============================================================================
# TIMELINE MARKER
# ============================================================================


@dataclass(slots=True)
class TimelineMarker:
    """A timed marker used by voice, graphics, and video composition."""

    id: str = field(default_factory=lambda: generate_id("marker"))
    marker_type: MarkerType = MarkerType.CUSTOM
    time_seconds: float = 0.0
    duration_seconds: float = 0.0
    label: str = ""
    story_id: str | None = None
    segment_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = normalize_text(self.id) or generate_id("marker")
        self.marker_type = parse_enum(
            MarkerType,
            self.marker_type,
            "marker_type",
        )
        self.time_seconds = ensure_non_negative(
            self.time_seconds,
            "time_seconds",
        )
        self.duration_seconds = ensure_non_negative(
            self.duration_seconds,
            "duration_seconds",
        )
        self.label = normalize_text(self.label)
        self.story_id = normalize_optional_text(self.story_id)
        self.segment_id = normalize_optional_text(self.segment_id)
        self.payload = dict(self.payload or {})

    @property
    def end_seconds(self) -> float:
        """Return marker end time."""

        return round(
            self.time_seconds + self.duration_seconds,
            3,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize timeline marker."""

        return json_safe(asdict(self))

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> TimelineMarker:
        """Deserialize timeline marker."""

        values = dict(data)
        values["marker_type"] = parse_enum(
            MarkerType,
            values.get("marker_type", MarkerType.CUSTOM),
            "marker_type",
        )
        return cls(**values)


# ============================================================================
# PRODUCTION METADATA
# ============================================================================


@dataclass(slots=True)
class ProductionMetadata:
    """Shared technical configuration for bulletin production."""

    project_name: str = "BahuvuNewsAI"
    channel_name: str = "BAHUVU NEWS"
    edition_name: str = "Daily Bulletin"
    timezone_name: str = DEFAULT_TIMEZONE
    frame_rate: int = DEFAULT_FRAME_RATE
    video_width: int = DEFAULT_VIDEO_WIDTH
    video_height: int = DEFAULT_VIDEO_HEIGHT
    target_duration_seconds: float = 0.0
    output_directory: str = "outputs"
    script_path: str | None = None
    audio_path: str | None = None
    graphics_directory: str | None = None
    video_path: str | None = None
    thumbnail_path: str | None = None
    youtube_video_id: str | None = None
    stage_completed: dict[str, bool] = field(default_factory=dict)
    stage_outputs: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.project_name = (
            normalize_text(self.project_name)
            or "BahuvuNewsAI"
        )
        self.channel_name = (
            normalize_text(self.channel_name)
            or "BAHUVU NEWS"
        )
        self.edition_name = (
            normalize_text(self.edition_name)
            or "Daily Bulletin"
        )
        self.timezone_name = (
            normalize_text(self.timezone_name)
            or DEFAULT_TIMEZONE
        )

        self.frame_rate = int(self.frame_rate)
        self.video_width = int(self.video_width)
        self.video_height = int(self.video_height)

        if self.frame_rate <= 0:
            raise BulletinValidationError(
                "frame_rate must be positive."
            )

        if self.video_width <= 0 or self.video_height <= 0:
            raise BulletinValidationError(
                "Video dimensions must be positive."
            )

        self.target_duration_seconds = ensure_non_negative(
            self.target_duration_seconds,
            "target_duration_seconds",
        )
        self.output_directory = (
            normalize_text(self.output_directory)
            or "outputs"
        )
        self.script_path = normalize_optional_text(
            self.script_path
        )
        self.audio_path = normalize_optional_text(self.audio_path)
        self.graphics_directory = normalize_optional_text(
            self.graphics_directory
        )
        self.video_path = normalize_optional_text(self.video_path)
        self.thumbnail_path = normalize_optional_text(
            self.thumbnail_path
        )
        self.youtube_video_id = normalize_optional_text(
            self.youtube_video_id
        )

        self.stage_completed = {
            str(key): bool(value)
            for key, value in dict(
                self.stage_completed or {}
            ).items()
        }
        self.stage_outputs = {
            str(key): normalize_text(value)
            for key, value in dict(
                self.stage_outputs or {}
            ).items()
            if normalize_text(value)
        }
        self.warnings = unique_strings(self.warnings)
        self.errors = unique_strings(self.errors)
        self.created_at = (
            normalize_text(self.created_at)
            or utc_now_iso()
        )
        self.updated_at = (
            normalize_text(self.updated_at)
            or utc_now_iso()
        )
        self.metadata = dict(self.metadata or {})

    @property
    def aspect_ratio(self) -> float:
        """Return video aspect ratio."""

        return round(
            self.video_width / self.video_height,
            6,
        )

    def mark_stage(
        self,
        stage: ProductionStage | str,
        completed: bool = True,
        output_path: str | None = None,
    ) -> None:
        """Record the state and optional output of a production stage."""

        stage_value = (
            stage.value
            if isinstance(stage, ProductionStage)
            else normalize_text(stage)
        )

        if not stage_value:
            raise BulletinValidationError(
                "Production stage cannot be empty."
            )

        self.stage_completed[stage_value] = bool(completed)

        if output_path:
            self.stage_outputs[stage_value] = normalize_text(
                output_path
            )

        self.updated_at = utc_now_iso()

    def is_stage_complete(
        self,
        stage: ProductionStage | str,
    ) -> bool:
        """Return whether a production stage is complete."""

        stage_value = (
            stage.value
            if isinstance(stage, ProductionStage)
            else normalize_text(stage)
        )

        return bool(
            self.stage_completed.get(stage_value, False)
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize production metadata."""

        return json_safe(asdict(self))

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> ProductionMetadata:
        """Deserialize production metadata."""

        return cls(**dict(data))


# ============================================================================
# NEWS BULLETIN
# ============================================================================


@dataclass(slots=True)
class NewsBulletin:
    """Canonical end-to-end bulletin production object."""

    id: str = field(default_factory=lambda: generate_id("bulletin"))
    title: str = ""
    edition_date: str = ""
    language: str = DEFAULT_LANGUAGE
    status: BulletinStatus = BulletinStatus.DRAFT
    opening_segments: list[ScriptSegment] = field(
        default_factory=list
    )
    stories: list[BulletinStory] = field(default_factory=list)
    closing_segments: list[ScriptSegment] = field(
        default_factory=list
    )
    backup_stories: list[BulletinStory] = field(
        default_factory=list
    )
    timeline: list[TimelineMarker] = field(
        default_factory=list
    )
    production: ProductionMetadata = field(
        default_factory=ProductionMetadata
    )
    version: int = 1
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    approved_by: str | None = None
    published_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = normalize_text(self.id) or generate_id(
            "bulletin"
        )
        self.title = normalize_text(self.title)
        self.edition_date = normalize_text(self.edition_date)
        self.language = normalize_text(self.language) or DEFAULT_LANGUAGE
        self.status = parse_enum(
            BulletinStatus,
            self.status,
            "bulletin status",
        )

        self.opening_segments = [
            segment
            if isinstance(segment, ScriptSegment)
            else ScriptSegment.from_dict(segment)
            for segment in self.opening_segments
        ]

        self.stories = [
            story
            if isinstance(story, BulletinStory)
            else BulletinStory.from_dict(story)
            for story in self.stories
        ]

        self.closing_segments = [
            segment
            if isinstance(segment, ScriptSegment)
            else ScriptSegment.from_dict(segment)
            for segment in self.closing_segments
        ]

        self.backup_stories = [
            story
            if isinstance(story, BulletinStory)
            else BulletinStory.from_dict(story)
            for story in self.backup_stories
        ]

        self.timeline = [
            marker
            if isinstance(marker, TimelineMarker)
            else TimelineMarker.from_dict(marker)
            for marker in self.timeline
        ]

        if not isinstance(
            self.production,
            ProductionMetadata,
        ):
            self.production = ProductionMetadata.from_dict(
                self.production
            )

        self.version = int(self.version)

        if self.version <= 0:
            raise BulletinValidationError(
                "NewsBulletin version must be positive."
            )

        self.created_at = (
            normalize_text(self.created_at)
            or utc_now_iso()
        )
        self.updated_at = (
            normalize_text(self.updated_at)
            or utc_now_iso()
        )
        self.approved_by = normalize_optional_text(
            self.approved_by
        )
        self.published_at = normalize_optional_text(
            self.published_at
        )
        self.metadata = dict(self.metadata or {})

        self.sort_content()
        self.validate()

    @property
    def story_count(self) -> int:
        """Return the number of selected bulletin stories."""

        return len(self.stories)

    @property
    def backup_story_count(self) -> int:
        """Return the number of backup stories."""

        return len(self.backup_stories)

    @property
    def lead_story(self) -> BulletinStory | None:
        """Return the designated lead story."""

        for story in self.stories:
            if story.role is StoryRole.LEAD:
                return story

        return self.stories[0] if self.stories else None

    @property
    def all_segments(self) -> list[ScriptSegment]:
        """Return all primary bulletin segments in broadcast order."""

        segments: list[ScriptSegment] = []
        segments.extend(self.opening_segments)

        for story in self.stories:
            segments.extend(story.segments)

        segments.extend(self.closing_segments)
        return segments

    @property
    def word_count(self) -> int:
        """Return complete bulletin word count."""

        return sum(
            segment.word_count
            for segment in self.all_segments
        )

    @property
    def estimated_duration_seconds(self) -> float:
        """Return complete estimated bulletin duration."""

        return round(
            sum(
                segment.total_duration_seconds
                for segment in self.all_segments
            ),
            3,
        )

    @property
    def estimated_duration_minutes(self) -> float:
        """Return estimated duration in minutes."""

        return round(
            self.estimated_duration_seconds / 60.0,
            3,
        )

    @property
    def script_text(self) -> str:
        """Return complete broadcast script."""

        blocks = [
            segment.text
            for segment in self.all_segments
            if segment.text
        ]
        return "\n\n".join(blocks)

    @property
    def production_ready(self) -> bool:
        """Return whether the bulletin has enough data for production."""

        if not self.title or not self.edition_date:
            return False

        if not self.stories:
            return False

        if not self.opening_segments:
            return False

        if not self.closing_segments:
            return False

        if not all(story.production_ready for story in self.stories):
            return False

        if any(
            not segment.text
            for segment in self.all_segments
            if segment.segment_type is not SegmentType.BREAK
        ):
            return False

        return True

    def sort_content(self) -> None:
        """Normalize story and segment ordering."""

        self.opening_segments.sort(
            key=lambda segment: (
                segment.order,
                segment.id,
            )
        )
        self.closing_segments.sort(
            key=lambda segment: (
                segment.order,
                segment.id,
            )
        )

        self.stories.sort(
            key=lambda story: (
                story.rank if story.rank > 0 else 10**9,
                -story.priority,
                -story.editorial_score,
                story.id,
            )
        )

        self.backup_stories.sort(
            key=lambda story: (
                story.rank if story.rank > 0 else 10**9,
                -story.priority,
                -story.editorial_score,
                story.id,
            )
        )

        for index, story in enumerate(self.stories, start=1):
            story.rank = index
            story.sort_segments()

        for index, story in enumerate(
            self.backup_stories,
            start=1,
        ):
            if story.rank <= 0:
                story.rank = index

    def add_story(
        self,
        story: BulletinStory,
        *,
        backup: bool = False,
    ) -> None:
        """Add a primary or backup story."""

        if not isinstance(story, BulletinStory):
            raise BulletinValidationError(
                "story must be a BulletinStory."
            )

        all_story_ids = {
            existing.id
            for existing in (
                self.stories + self.backup_stories
            )
        }

        all_article_ids = {
            existing.article_id
            for existing in (
                self.stories + self.backup_stories
            )
        }

        if story.id in all_story_ids:
            raise BulletinValidationError(
                f"Duplicate bulletin story id: {story.id}"
            )

        if story.article_id in all_article_ids:
            raise BulletinValidationError(
                f"Duplicate article_id: {story.article_id}"
            )

        if backup:
            story.role = StoryRole.BACKUP
            self.backup_stories.append(story)
        else:
            self.stories.append(story)

        self.sort_content()
        self.updated_at = utc_now_iso()

    def set_status(self, status: BulletinStatus | str) -> None:
        """Update bulletin status."""

        self.status = parse_enum(
            BulletinStatus,
            status,
            "bulletin status",
        )
        self.updated_at = utc_now_iso()

    def build_timeline(self) -> list[TimelineMarker]:
        """
        Generate deterministic story and segment timeline markers.

        Existing markers are replaced because generated marker times must
        always match the latest segment durations.
        """

        markers: list[TimelineMarker] = []
        cursor = 0.0

        markers.append(
            TimelineMarker(
                marker_type=MarkerType.BULLETIN_START,
                time_seconds=0.0,
                label=self.title or "Bulletin start",
            )
        )

        for segment in self.opening_segments:
            markers.extend(
                self._segment_markers(
                    segment=segment,
                    start_time=cursor,
                    story_id=None,
                )
            )
            cursor += segment.total_duration_seconds

        for story in self.stories:
            story_start = cursor

            markers.append(
                TimelineMarker(
                    marker_type=MarkerType.STORY_START,
                    time_seconds=story_start,
                    label=story.headline,
                    story_id=story.id,
                )
            )

            markers.append(
                TimelineMarker(
                    marker_type=MarkerType.CHAPTER,
                    time_seconds=story_start,
                    label=story.headline,
                    story_id=story.id,
                    payload={
                        "rank": story.rank,
                        "category": story.category,
                        "role": story.role.value,
                    },
                )
            )

            for segment in story.segments:
                markers.extend(
                    self._segment_markers(
                        segment=segment,
                        start_time=cursor,
                        story_id=story.id,
                    )
                )
                cursor += segment.total_duration_seconds

            markers.append(
                TimelineMarker(
                    marker_type=MarkerType.STORY_END,
                    time_seconds=cursor,
                    label=story.headline,
                    story_id=story.id,
                )
            )

        for segment in self.closing_segments:
            markers.extend(
                self._segment_markers(
                    segment=segment,
                    start_time=cursor,
                    story_id=None,
                )
            )
            cursor += segment.total_duration_seconds

        markers.append(
            TimelineMarker(
                marker_type=MarkerType.BULLETIN_END,
                time_seconds=cursor,
                label=self.title or "Bulletin end",
            )
        )

                 # Sort only by time. Python's sort is stable, so markers that
        # share the same timestamp retain their intentional insertion
        # order. This ensures BULLETIN_END remains the final marker.
        self.timeline = sorted(
            markers,
            key=lambda marker: marker.time_seconds,
        )      

        self.updated_at = utc_now_iso()
        return list(self.timeline)

    def _segment_markers(
        self,
        *,
        segment: ScriptSegment,
        start_time: float,
        story_id: str | None,
    ) -> list[TimelineMarker]:
        """Create start, end, audio, and visual markers."""

        duration = segment.total_duration_seconds
        end_time = start_time + duration

        markers = [
            TimelineMarker(
                marker_type=MarkerType.SEGMENT_START,
                time_seconds=start_time,
                duration_seconds=duration,
                label=segment.segment_type.value,
                story_id=story_id,
                segment_id=segment.id,
            ),
            TimelineMarker(
                marker_type=MarkerType.SEGMENT_END,
                time_seconds=end_time,
                label=segment.segment_type.value,
                story_id=story_id,
                segment_id=segment.id,
            ),
        ]

        if segment.voice_cue.audio_path:
            markers.extend(
                [
                    TimelineMarker(
                        marker_type=MarkerType.AUDIO_IN,
                        time_seconds=start_time,
                        duration_seconds=duration,
                        label=segment.voice_cue.audio_path,
                        story_id=story_id,
                        segment_id=segment.id,
                    ),
                    TimelineMarker(
                        marker_type=MarkerType.AUDIO_OUT,
                        time_seconds=end_time,
                        label=segment.voice_cue.audio_path,
                        story_id=story_id,
                        segment_id=segment.id,
                    ),
                ]
            )

        if (
            segment.graphic_cue.graphic_type
            is not GraphicType.NONE
        ):
            graphic_duration = (
                segment.graphic_cue.duration_seconds
                if segment.graphic_cue.duration_seconds is not None
                else duration
            )

            markers.extend(
                [
                    TimelineMarker(
                        marker_type=MarkerType.GRAPHIC_IN,
                        time_seconds=start_time,
                        duration_seconds=graphic_duration,
                        label=(
                            segment.graphic_cue.headline
                            or segment.segment_type.value
                        ),
                        story_id=story_id,
                        segment_id=segment.id,
                    ),
                    TimelineMarker(
                        marker_type=MarkerType.GRAPHIC_OUT,
                        time_seconds=(
                            start_time + graphic_duration
                        ),
                        label=(
                            segment.graphic_cue.headline
                            or segment.segment_type.value
                        ),
                        story_id=story_id,
                        segment_id=segment.id,
                    ),
                ]
            )

        return markers

    def validate(self) -> None:
        """Validate complete bulletin consistency."""

        if not self.id:
            raise BulletinValidationError(
                "NewsBulletin requires an id."
            )

        story_ids = [
            story.id
            for story in (
                self.stories + self.backup_stories
            )
        ]

        if len(story_ids) != len(set(story_ids)):
            raise BulletinValidationError(
                "NewsBulletin contains duplicate story IDs."
            )

        article_ids = [
            story.article_id
            for story in (
                self.stories + self.backup_stories
            )
        ]

        if len(article_ids) != len(set(article_ids)):
            raise BulletinValidationError(
                "NewsBulletin contains duplicate article IDs."
            )

        segment_ids = [
            segment.id
            for segment in self.all_segments
        ]

        if len(segment_ids) != len(set(segment_ids)):
            raise BulletinValidationError(
                "NewsBulletin contains duplicate segment IDs."
            )

        lead_stories = [
            story
            for story in self.stories
            if story.role is StoryRole.LEAD
        ]

        if len(lead_stories) > 1:
            raise BulletinValidationError(
                "NewsBulletin cannot contain more than one "
                "lead story."
            )

        if (
            self.status is BulletinStatus.PUBLISHED
            and not self.published_at
        ):
            raise BulletinValidationError(
                "Published bulletin requires published_at."
            )

    def summary(self) -> dict[str, Any]:
        """Return concise bulletin statistics."""

        lead = self.lead_story

        return {
            "bulletin_id": self.id,
            "title": self.title,
            "edition_date": self.edition_date,
            "language": self.language,
            "status": self.status.value,
            "story_count": self.story_count,
            "backup_story_count": self.backup_story_count,
            "lead_story": lead.headline if lead else None,
            "word_count": self.word_count,
            "estimated_duration_seconds": (
                self.estimated_duration_seconds
            ),
            "estimated_duration_minutes": (
                self.estimated_duration_minutes
            ),
            "timeline_markers": len(self.timeline),
            "production_ready": self.production_ready,
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize the complete bulletin."""

        return {
            "id": self.id,
            "title": self.title,
            "edition_date": self.edition_date,
            "language": self.language,
            "status": self.status.value,
            "opening_segments": [
                segment.to_dict()
                for segment in self.opening_segments
            ],
            "stories": [
                story.to_dict()
                for story in self.stories
            ],
            "closing_segments": [
                segment.to_dict()
                for segment in self.closing_segments
            ],
            "backup_stories": [
                story.to_dict()
                for story in self.backup_stories
            ],
            "timeline": [
                marker.to_dict()
                for marker in self.timeline
            ],
            "production": self.production.to_dict(),
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "approved_by": self.approved_by,
            "published_at": self.published_at,
            "metadata": json_safe(self.metadata),
        }

    def to_json(
        self,
        *,
        indent: int = 2,
        ensure_ascii: bool = False,
    ) -> str:
        """Serialize bulletin to JSON text."""

        try:
            return json.dumps(
                self.to_dict(),
                indent=indent,
                ensure_ascii=ensure_ascii,
                sort_keys=True,
            )
        except (TypeError, ValueError) as exc:
            raise BulletinSerializationError(
                "Unable to serialize bulletin to JSON."
            ) from exc

    def save_json(
        self,
        path: str | Path,
        *,
        indent: int = 2,
        ensure_ascii: bool = False,
    ) -> Path:
        """Write bulletin JSON to disk."""

        output_path = Path(path)
        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        try:
            output_path.write_text(
                self.to_json(
                    indent=indent,
                    ensure_ascii=ensure_ascii,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            raise BulletinSerializationError(
                f"Unable to save bulletin JSON: {output_path}"
            ) from exc

        return output_path

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> NewsBulletin:
        """Deserialize a complete bulletin."""

        try:
            values = dict(data)
            values["status"] = parse_enum(
                BulletinStatus,
                values.get("status", BulletinStatus.DRAFT),
                "bulletin status",
            )
            values["opening_segments"] = [
                ScriptSegment.from_dict(segment)
                for segment in values.get(
                    "opening_segments",
                    [],
                )
            ]
            values["stories"] = [
                BulletinStory.from_dict(story)
                for story in values.get("stories", [])
            ]
            values["closing_segments"] = [
                ScriptSegment.from_dict(segment)
                for segment in values.get(
                    "closing_segments",
                    [],
                )
            ]
            values["backup_stories"] = [
                BulletinStory.from_dict(story)
                for story in values.get(
                    "backup_stories",
                    [],
                )
            ]
            values["timeline"] = [
                TimelineMarker.from_dict(marker)
                for marker in values.get("timeline", [])
            ]
            values["production"] = (
                ProductionMetadata.from_dict(
                    values.get("production", {})
                )
            )

            return cls(**values)
        except BulletinModelError:
            raise
        except (TypeError, ValueError, KeyError) as exc:
            raise BulletinSerializationError(
                "Unable to deserialize bulletin."
            ) from exc

    @classmethod
    def from_json(cls, value: str) -> NewsBulletin:
        """Deserialize a bulletin from JSON text."""

        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise BulletinSerializationError(
                "Invalid bulletin JSON."
            ) from exc

        if not isinstance(payload, dict):
            raise BulletinSerializationError(
                "Bulletin JSON root must be an object."
            )

        return cls.from_dict(payload)

    @classmethod
    def load_json(
        cls,
        path: str | Path,
    ) -> NewsBulletin:
        """Load a bulletin from a JSON file."""

        input_path = Path(path)

        try:
            content = input_path.read_text(
                encoding="utf-8"
            )
        except OSError as exc:
            raise BulletinSerializationError(
                f"Unable to read bulletin JSON: {input_path}"
            ) from exc

        return cls.from_json(content)


# ============================================================================
# FACTORY HELPERS
# ============================================================================


def create_script_segment(
    *,
    text: str,
    segment_type: SegmentType = SegmentType.STORY_BODY,
    order: int = 0,
    language: str = DEFAULT_LANGUAGE,
    voice_style: VoiceStyle = VoiceStyle.NEUTRAL,
    graphic_type: GraphicType = GraphicType.NONE,
    graphic_headline: str | None = None,
    source_references: Sequence[str] | None = None,
    pause_before_seconds: float = 0.0,
    pause_after_seconds: float = 0.0,
) -> ScriptSegment:
    """Create a script segment with aligned voice and graphic cues."""

    return ScriptSegment(
        segment_type=segment_type,
        text=text,
        language=language,
        order=order,
        voice_cue=VoiceCue(
            language=language,
            style=voice_style,
            pause_before_seconds=pause_before_seconds,
            pause_after_seconds=pause_after_seconds,
        ),
        graphic_cue=GraphicCue(
            graphic_type=graphic_type,
            headline=graphic_headline,
        ),
        source_references=list(
            source_references or []
        ),
    )


def create_bulletin_story(
    *,
    article_id: str,
    headline: str,
    summary: str,
    rank: int,
    category: str,
    editorial_score: float,
    confidence: float,
    role: StoryRole = StoryRole.STANDARD,
    language: str = DEFAULT_LANGUAGE,
    source_name: str | None = None,
    source_url: str | None = None,
    image_url: str | None = None,
    segments: Sequence[ScriptSegment] | None = None,
    production_ready: bool = False,
) -> BulletinStory:
    """Create a normalized bulletin story."""

    return BulletinStory(
        article_id=article_id,
        headline=headline,
        summary=summary,
        rank=rank,
        role=role,
        category=category,
        language=language,
        source_name=source_name,
        source_url=source_url,
        image_url=image_url,
        editorial_score=editorial_score,
        confidence=confidence,
        priority=max(0, 101 - rank),
        production_ready=production_ready,
        segments=list(segments or []),
    )


# ============================================================================
# SELF-TEST
# ============================================================================


def _build_self_test_bulletin() -> NewsBulletin:
    """Build a deterministic production-model test bulletin."""

    opening = create_script_segment(
        text=(
            "Good evening. You are watching BAHUVU NEWS. "
            "Here are today's most important stories."
        ),
        segment_type=SegmentType.OPENING,
        order=1,
        language="en",
        voice_style=VoiceStyle.FORMAL,
        graphic_type=GraphicType.OPENING_CARD,
        graphic_headline="BAHUVU NEWS",
        pause_after_seconds=0.5,
    )

    lead_intro = create_script_segment(
        text=(
            "Our top story tonight. Authorities have announced "
            "new emergency measures after severe weather affected "
            "several districts."
        ),
        segment_type=SegmentType.STORY_INTRO,
        order=1,
        language="en",
        voice_style=VoiceStyle.AUTHORITATIVE,
        graphic_type=GraphicType.HEADLINE_CARD,
        graphic_headline="Severe Weather Emergency Measures",
        source_references=[
            "https://example.com/weather-story"
        ],
        pause_after_seconds=0.25,
    )

    lead_body = create_script_segment(
        text=(
            "Relief teams have been deployed, control rooms are "
            "operating around the clock, and residents in vulnerable "
            "areas have been advised to follow official alerts."
        ),
        segment_type=SegmentType.STORY_BODY,
        order=2,
        language="en",
        voice_style=VoiceStyle.FORMAL,
        graphic_type=GraphicType.STORY_CARD,
        graphic_headline="Relief Teams Deployed",
        source_references=[
            "https://example.com/weather-story"
        ],
    )

    second_story_segment = create_script_segment(
        text=(
            "In technology news, researchers have introduced "
            "a new public-interest artificial intelligence system "
            "designed to improve access to verified information."
        ),
        segment_type=SegmentType.STORY_BODY,
        order=1,
        language="en",
        voice_style=VoiceStyle.NEUTRAL,
        graphic_type=GraphicType.STORY_CARD,
        graphic_headline="Public-Interest AI System",
        source_references=[
            "https://example.com/technology-story"
        ],
    )

    closing = create_script_segment(
        text=(
            "Those were today's major developments. "
            "Thank you for watching BAHUVU NEWS."
        ),
        segment_type=SegmentType.CLOSING,
        order=1,
        language="en",
        voice_style=VoiceStyle.WARM,
        graphic_type=GraphicType.CLOSING_CARD,
        graphic_headline="BAHUVU NEWS",
        pause_before_seconds=0.25,
    )

    lead_story = create_bulletin_story(
        article_id="article_weather_001",
        headline=(
            "Emergency measures announced after severe weather"
        ),
        summary=(
            "Authorities deployed relief teams and activated "
            "district control rooms."
        ),
        rank=1,
        category="weather",
        editorial_score=94.5,
        confidence=92.0,
        role=StoryRole.LEAD,
        source_name="Bahuvu Test Wire",
        source_url="https://example.com/weather-story",
        image_url="https://example.com/weather.jpg",
        segments=[
            lead_intro,
            lead_body,
        ],
        production_ready=True,
    )

    lead_story.media_assets.append(
        MediaAsset(
            media_type=MediaType.IMAGE,
            source="https://example.com/weather.jpg",
            title="Severe weather response",
            attribution="Bahuvu Test Wire",
        )
    )

    second_story = create_bulletin_story(
        article_id="article_technology_001",
        headline=(
            "Researchers introduce public-interest AI system"
        ),
        summary=(
            "The system is designed to improve access to "
            "verified public information."
        ),
        rank=2,
        category="technology",
        editorial_score=86.0,
        confidence=88.0,
        role=StoryRole.STANDARD,
        source_name="Bahuvu Technology Desk",
        source_url="https://example.com/technology-story",
        segments=[
            second_story_segment,
        ],
        production_ready=True,
    )

    backup_story = create_bulletin_story(
        article_id="article_business_001",
        headline="Markets close higher after broad gains",
        summary=(
            "Major market indices recorded broad-based gains."
        ),
        rank=1,
        category="business",
        editorial_score=74.0,
        confidence=80.0,
        role=StoryRole.BACKUP,
        source_name="Bahuvu Business Desk",
        source_url="https://example.com/business-story",
        production_ready=False,
    )

    production = ProductionMetadata(
        edition_name="Self-Test Bulletin",
        target_duration_seconds=180.0,
        output_directory="outputs/bulletins",
    )
    production.mark_stage(
        ProductionStage.RANKING,
        output_path="outputs/ranking/self_test.json",
    )
    production.mark_stage(
        ProductionStage.SCRIPTING,
        output_path="outputs/scripts/self_test.json",
    )

    bulletin = NewsBulletin(
        id="bulletin_self_test",
        title="BAHUVU NEWS Self-Test Bulletin",
        edition_date="2026-07-11",
        language="en",
        status=BulletinStatus.SCRIPTED,
        opening_segments=[opening],
        stories=[
            lead_story,
            second_story,
        ],
        closing_segments=[closing],
        backup_stories=[backup_story],
        production=production,
        metadata={
            "test": True,
            "pipeline": "production",
        },
    )

    bulletin.build_timeline()
    return bulletin


def _run_self_test() -> None:
    """Run deterministic module verification."""

    bulletin = _build_self_test_bulletin()

    assert bulletin.story_count == 2
    assert bulletin.backup_story_count == 1
    assert bulletin.lead_story is not None
    assert bulletin.lead_story.role is StoryRole.LEAD
    assert bulletin.lead_story.rank == 1
    assert bulletin.word_count > 0
    assert bulletin.estimated_duration_seconds > 0
    assert bulletin.production_ready
    assert bulletin.timeline
    assert (
        bulletin.timeline[0].marker_type
        is MarkerType.BULLETIN_START
    )
    assert (
        bulletin.timeline[-1].marker_type
        is MarkerType.BULLETIN_END
    )
    assert bulletin.production.is_stage_complete(
        ProductionStage.RANKING
    )
    assert bulletin.production.is_stage_complete(
        ProductionStage.SCRIPTING
    )

    serialized = bulletin.to_json()
    restored = NewsBulletin.from_json(serialized)

    assert restored.id == bulletin.id
    assert restored.title == bulletin.title
    assert restored.story_count == bulletin.story_count
    assert restored.word_count == bulletin.word_count
    assert (
        restored.lead_story is not None
        and restored.lead_story.article_id
        == "article_weather_001"
    )
    assert restored.production_ready
    assert len(restored.timeline) == len(bulletin.timeline)

    summary = bulletin.summary()

    print("Bulletin production models initialized successfully.")
    print(f"Bulletin ID: {summary['bulletin_id']}")
    print(f"Title: {summary['title']}")
    print(f"Status: {summary['status']}")
    print(f"Stories: {summary['story_count']}")
    print(f"Backup stories: {summary['backup_story_count']}")
    print(f"Lead story: {summary['lead_story']}")
    print(f"Words: {summary['word_count']}")
    print(
        "Estimated duration: "
        f"{summary['estimated_duration_seconds']:.2f} seconds"
    )
    print(
        f"Timeline markers: {summary['timeline_markers']}"
    )
    print(
        "Production ready: "
        f"{summary['production_ready']}"
    )
    print("Serialization round-trip: passed")
    print("Bulletin model self-test passed.")


if __name__ == "__main__":
    _run_self_test()