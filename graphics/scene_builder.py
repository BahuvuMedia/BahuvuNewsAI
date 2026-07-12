"""
BahuvuNewsAI - Graphics Scene Builder
=====================================

Builds a canonical, ordered scene timeline from bulletin stories and audio
metadata. This module does not render pixels or video. It prepares the exact
scene plan that downstream graphics and video renderers will follow.

Pipeline position:

    bulletin + audio manifest
        -> graphics.scene_builder
        -> graphics renderer
        -> video renderer

Run:

    python -m py_compile graphics/scene_builder.py
    python -m graphics.scene_builder
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable, Mapping, Sequence


# =============================================================================
# ENUMS
# =============================================================================


class SceneType(str, Enum):
    INTRO = "intro"
    HEADLINE = "headline"
    PHOTO = "photo"
    SUMMARY = "summary"
    QUOTE = "quote"
    DATA = "data"
    MAP = "map"
    TRANSITION = "transition"
    OUTRO = "outro"


class SceneStatus(str, Enum):
    PLANNED = "planned"
    READY = "ready"
    BLOCKED = "blocked"


class TransitionType(str, Enum):
    NONE = "none"
    FADE = "fade"
    CROSSFADE = "crossfade"
    SLIDE = "slide"
    CUT = "cut"


class LayoutType(str, Enum):
    FULL_FRAME = "full_frame"
    HEADLINE_FOCUS = "headline_focus"
    IMAGE_LEFT = "image_left"
    IMAGE_RIGHT = "image_right"
    IMAGE_FULL = "image_full"
    SUMMARY_PANEL = "summary_panel"
    QUOTE_CARD = "quote_card"
    DATA_PANEL = "data_panel"
    MAP_PANEL = "map_panel"


# =============================================================================
# DATA MODELS
# =============================================================================


@dataclass(slots=True)
class SceneBuilderConfig:
    intro_duration_seconds: float = 5.0
    outro_duration_seconds: float = 5.0
    headline_duration_seconds: float = 4.0
    photo_duration_seconds: float = 6.0
    summary_minimum_duration_seconds: float = 6.0
    transition_duration_seconds: float = 1.0
    default_story_duration_seconds: float = 20.0
    minimum_scene_duration_seconds: float = 1.0
    maximum_scene_duration_seconds: float = 45.0
    include_intro: bool = True
    include_outro: bool = True
    include_transitions: bool = True
    include_photo_scene: bool = True
    include_summary_scene: bool = True
    default_transition: TransitionType = TransitionType.FADE
    output_dir: Path = Path("outputs/scenes")
    manifest_filename: str = "scene_manifest.json"
    write_manifest: bool = True

    def validate(self) -> None:
        numeric_fields = {
            "intro_duration_seconds": self.intro_duration_seconds,
            "outro_duration_seconds": self.outro_duration_seconds,
            "headline_duration_seconds": self.headline_duration_seconds,
            "photo_duration_seconds": self.photo_duration_seconds,
            "summary_minimum_duration_seconds": self.summary_minimum_duration_seconds,
            "transition_duration_seconds": self.transition_duration_seconds,
            "default_story_duration_seconds": self.default_story_duration_seconds,
            "minimum_scene_duration_seconds": self.minimum_scene_duration_seconds,
            "maximum_scene_duration_seconds": self.maximum_scene_duration_seconds,
        }

        for name, value in numeric_fields.items():
            if value < 0:
                raise ValueError(f"{name} cannot be negative.")

        if self.minimum_scene_duration_seconds <= 0:
            raise ValueError("Minimum scene duration must be positive.")

        if (
            self.maximum_scene_duration_seconds
            < self.minimum_scene_duration_seconds
        ):
            raise ValueError("Maximum scene duration is invalid.")

        if not self.manifest_filename.strip():
            raise ValueError("Manifest filename cannot be empty.")


@dataclass(slots=True)
class SceneStoryInput:
    story_id: str
    order: int
    headline: str
    summary: str = ""
    category: str = ""
    image_path: str = ""
    audio_path: str = ""
    audio_duration_seconds: float = 0.0
    quote: str = ""
    data_points: list[str] = field(default_factory=list)
    map_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Scene:
    scene_id: str
    story_id: str
    order: int
    scene_type: SceneType
    status: SceneStatus
    start_time_seconds: float
    duration_seconds: float
    end_time_seconds: float
    headline: str = ""
    summary: str = ""
    image_path: str = ""
    audio_path: str = ""
    category: str = ""
    layout: LayoutType = LayoutType.FULL_FRAME
    transition_in: TransitionType = TransitionType.NONE
    transition_out: TransitionType = TransitionType.NONE
    overlay: str = ""
    background: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "story_id": self.story_id,
            "order": self.order,
            "scene_type": self.scene_type.value,
            "status": self.status.value,
            "start_time_seconds": self.start_time_seconds,
            "duration_seconds": self.duration_seconds,
            "end_time_seconds": self.end_time_seconds,
            "headline": self.headline,
            "summary": self.summary,
            "image_path": self.image_path,
            "audio_path": self.audio_path,
            "category": self.category,
            "layout": self.layout.value,
            "transition_in": self.transition_in.value,
            "transition_out": self.transition_out.value,
            "overlay": self.overlay,
            "background": self.background,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class SceneTimeline:
    bulletin_id: str
    generated_at: str
    total_duration_seconds: float
    scene_count: int
    story_count: int
    scenes: list[Scene]
    manifest_path: Path | None = None
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def production_ready(self) -> bool:
        return (
            self.scene_count > 0
            and all(scene.status != SceneStatus.BLOCKED for scene in self.scenes)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bulletin_id": self.bulletin_id,
            "generated_at": self.generated_at,
            "total_duration_seconds": self.total_duration_seconds,
            "scene_count": self.scene_count,
            "story_count": self.story_count,
            "production_ready": self.production_ready,
            "manifest_path": (
                str(self.manifest_path) if self.manifest_path else None
            ),
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
            "scenes": [scene.to_dict() for scene in self.scenes],
        }


@dataclass(slots=True)
class SceneBuilderSummary:
    timelines_processed: int = 0
    stories_processed: int = 0
    scenes_created: int = 0
    blocked_scenes: int = 0
    total_duration_seconds: float = 0.0

    @classmethod
    def from_timelines(
        cls,
        timelines: Sequence[SceneTimeline],
    ) -> "SceneBuilderSummary":
        return cls(
            timelines_processed=len(timelines),
            stories_processed=sum(item.story_count for item in timelines),
            scenes_created=sum(item.scene_count for item in timelines),
            blocked_scenes=sum(
                1
                for timeline in timelines
                for scene in timeline.scenes
                if scene.status == SceneStatus.BLOCKED
            ),
            total_duration_seconds=round(
                sum(item.total_duration_seconds for item in timelines),
                2,
            ),
        )


# =============================================================================
# HELPERS
# =============================================================================


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _coerce_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _slugify(value: str, fallback: str = "item") -> str:
    value = value.strip().lower()
    value = re.sub(r"[^\w\-]+", "_", value, flags=re.UNICODE)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or fallback


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def coerce_scene_story_input(
    value: Any,
    *,
    fallback_order: int = 1,
) -> SceneStoryInput:
    if isinstance(value, SceneStoryInput):
        return value

    mapping = _coerce_mapping(value)
    if not mapping:
        raise TypeError(
            "Scene story input must be a mapping, dataclass, or object."
        )

    story_id = _safe_text(
        mapping.get("story_id")
        or mapping.get("article_id")
        or mapping.get("id")
        or f"story_{fallback_order:03d}"
    )

    order_value = (
        mapping.get("order")
        or mapping.get("position")
        or mapping.get("rank")
        or fallback_order
    )

    try:
        order = int(order_value)
    except (TypeError, ValueError):
        order = fallback_order

    summary_value = (
        mapping.get("summary")
        or mapping.get("translated_summary")
        or mapping.get("body")
        or mapping.get("translated_body")
        or mapping.get("content")
        or ""
    )

    data_points = mapping.get("data_points") or mapping.get("facts") or []
    if isinstance(data_points, str):
        data_points = [data_points]
    elif not isinstance(data_points, Sequence):
        data_points = []

    metadata = mapping.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        metadata = {}

    return SceneStoryInput(
        story_id=story_id,
        order=order,
        headline=_safe_text(
            mapping.get("headline")
            or mapping.get("translated_headline")
            or mapping.get("title")
            or ""
        ),
        summary=_safe_text(summary_value),
        category=_safe_text(mapping.get("category") or ""),
        image_path=_safe_text(
            mapping.get("image_path")
            or mapping.get("image_url")
            or mapping.get("photo_path")
            or ""
        ),
        audio_path=_safe_text(
            mapping.get("audio_path")
            or mapping.get("narration_path")
            or ""
        ),
        audio_duration_seconds=_safe_float(
            mapping.get("audio_duration_seconds")
            or mapping.get("duration_seconds")
            or 0.0
        ),
        quote=_safe_text(mapping.get("quote") or ""),
        data_points=[
            _safe_text(item).strip()
            for item in data_points
            if _safe_text(item).strip()
        ],
        map_path=_safe_text(mapping.get("map_path") or ""),
        metadata=dict(metadata),
    )


def coerce_story_list(values: Iterable[Any]) -> list[SceneStoryInput]:
    stories = [
        coerce_scene_story_input(value, fallback_order=index)
        for index, value in enumerate(values, start=1)
    ]
    stories.sort(key=lambda item: (item.order, item.story_id))
    return stories


# =============================================================================
# SCENE BUILDER
# =============================================================================


class SceneBuilder:
    def __init__(self, config: SceneBuilderConfig | None = None) -> None:
        self.config = config or SceneBuilderConfig()
        self.config.validate()

    def build_timeline(
        self,
        *,
        bulletin_id: str,
        stories: Iterable[Any],
        metadata: Mapping[str, Any] | None = None,
    ) -> SceneTimeline:
        story_inputs = coerce_story_list(stories)
        scenes: list[Scene] = []
        warnings: list[str] = []
        cursor = 0.0
        scene_order = 1

        if self.config.include_intro:
            intro = self._make_scene(
                scene_id=f"{_slugify(bulletin_id)}_intro",
                story_id="",
                order=scene_order,
                scene_type=SceneType.INTRO,
                start=cursor,
                duration=self.config.intro_duration_seconds,
                headline="BAHUVU NEWS",
                layout=LayoutType.FULL_FRAME,
                transition_in=TransitionType.FADE,
                transition_out=self.config.default_transition,
                background="brand_intro",
            )
            scenes.append(intro)
            cursor = intro.end_time_seconds
            scene_order += 1

        for index, story in enumerate(story_inputs):
            if not story.headline.strip():
                warnings.append(
                    f"{story.story_id}: headline is missing."
                )

            story_scenes, cursor, scene_order = self._build_story_scenes(
                story=story,
                cursor=cursor,
                scene_order=scene_order,
            )
            scenes.extend(story_scenes)

            if (
                self.config.include_transitions
                and index < len(story_inputs) - 1
            ):
                transition = self._make_scene(
                    scene_id=(
                        f"{_slugify(bulletin_id)}_transition_"
                        f"{index + 1:03d}"
                    ),
                    story_id=story.story_id,
                    order=scene_order,
                    scene_type=SceneType.TRANSITION,
                    start=cursor,
                    duration=self.config.transition_duration_seconds,
                    layout=LayoutType.FULL_FRAME,
                    transition_in=self.config.default_transition,
                    transition_out=self.config.default_transition,
                    background="brand_transition",
                )
                scenes.append(transition)
                cursor = transition.end_time_seconds
                scene_order += 1

        if self.config.include_outro:
            outro = self._make_scene(
                scene_id=f"{_slugify(bulletin_id)}_outro",
                story_id="",
                order=scene_order,
                scene_type=SceneType.OUTRO,
                start=cursor,
                duration=self.config.outro_duration_seconds,
                headline="BAHUVU NEWS",
                summary="మరిన్ని వార్తల కోసం బాహువు న్యూస్‌ను అనుసరించండి.",
                layout=LayoutType.FULL_FRAME,
                transition_in=self.config.default_transition,
                transition_out=TransitionType.FADE,
                background="brand_outro",
            )
            scenes.append(outro)
            cursor = outro.end_time_seconds

        manifest_path = (
            self.config.output_dir
            / _slugify(bulletin_id, "bulletin")
            / self.config.manifest_filename
        )

        timeline = SceneTimeline(
            bulletin_id=bulletin_id,
            generated_at=_utc_now_iso(),
            total_duration_seconds=round(cursor, 2),
            scene_count=len(scenes),
            story_count=len(story_inputs),
            scenes=scenes,
            manifest_path=manifest_path if self.config.write_manifest else None,
            warnings=warnings,
            metadata=dict(metadata or {}),
        )

        self._validate_timeline(timeline)

        if self.config.write_manifest:
            self.write_manifest(timeline)

        return timeline

    def _build_story_scenes(
        self,
        *,
        story: SceneStoryInput,
        cursor: float,
        scene_order: int,
    ) -> tuple[list[Scene], float, int]:
        scenes: list[Scene] = []

        story_duration = (
            story.audio_duration_seconds
            if story.audio_duration_seconds > 0
            else self.config.default_story_duration_seconds
        )

        fixed_duration = self.config.headline_duration_seconds
        if self.config.include_photo_scene and story.image_path:
            fixed_duration += self.config.photo_duration_seconds

        remaining = max(
            self.config.summary_minimum_duration_seconds,
            story_duration - fixed_duration,
        )

        headline_status = (
            SceneStatus.READY
            if story.headline.strip()
            else SceneStatus.BLOCKED
        )

        headline_scene = self._make_scene(
            scene_id=f"{_slugify(story.story_id)}_headline",
            story_id=story.story_id,
            order=scene_order,
            scene_type=SceneType.HEADLINE,
            start=cursor,
            duration=self.config.headline_duration_seconds,
            headline=story.headline,
            category=story.category,
            audio_path=story.audio_path,
            layout=LayoutType.HEADLINE_FOCUS,
            transition_in=self.config.default_transition,
            transition_out=TransitionType.CUT,
            background="news_background",
            status=headline_status,
            metadata=story.metadata,
        )
        scenes.append(headline_scene)
        cursor = headline_scene.end_time_seconds
        scene_order += 1

        if self.config.include_photo_scene and story.image_path:
            photo_scene = self._make_scene(
                scene_id=f"{_slugify(story.story_id)}_photo",
                story_id=story.story_id,
                order=scene_order,
                scene_type=SceneType.PHOTO,
                start=cursor,
                duration=self.config.photo_duration_seconds,
                headline=story.headline,
                summary=story.summary,
                image_path=story.image_path,
                audio_path=story.audio_path,
                category=story.category,
                layout=LayoutType.IMAGE_FULL,
                transition_in=TransitionType.CUT,
                transition_out=TransitionType.CROSSFADE,
                overlay="lower_third",
                background="news_background",
                metadata=story.metadata,
            )
            scenes.append(photo_scene)
            cursor = photo_scene.end_time_seconds
            scene_order += 1

        if story.quote.strip():
            quote_duration = min(
                self.config.maximum_scene_duration_seconds,
                max(
                    self.config.minimum_scene_duration_seconds,
                    remaining * 0.25,
                ),
            )
            quote_scene = self._make_scene(
                scene_id=f"{_slugify(story.story_id)}_quote",
                story_id=story.story_id,
                order=scene_order,
                scene_type=SceneType.QUOTE,
                start=cursor,
                duration=quote_duration,
                headline=story.headline,
                summary=story.quote,
                image_path=story.image_path,
                audio_path=story.audio_path,
                category=story.category,
                layout=LayoutType.QUOTE_CARD,
                transition_in=TransitionType.CROSSFADE,
                transition_out=TransitionType.CROSSFADE,
                overlay="quote_overlay",
                background="news_background",
                metadata=story.metadata,
            )
            scenes.append(quote_scene)
            cursor = quote_scene.end_time_seconds
            scene_order += 1
            remaining = max(
                self.config.summary_minimum_duration_seconds,
                remaining - quote_duration,
            )

        if story.data_points:
            data_duration = min(
                self.config.maximum_scene_duration_seconds,
                max(
                    self.config.minimum_scene_duration_seconds,
                    remaining * 0.25,
                ),
            )
            data_scene = self._make_scene(
                scene_id=f"{_slugify(story.story_id)}_data",
                story_id=story.story_id,
                order=scene_order,
                scene_type=SceneType.DATA,
                start=cursor,
                duration=data_duration,
                headline=story.headline,
                summary=" | ".join(story.data_points),
                image_path=story.image_path,
                audio_path=story.audio_path,
                category=story.category,
                layout=LayoutType.DATA_PANEL,
                transition_in=TransitionType.CROSSFADE,
                transition_out=TransitionType.CROSSFADE,
                overlay="data_overlay",
                background="news_background",
                metadata=story.metadata,
            )
            scenes.append(data_scene)
            cursor = data_scene.end_time_seconds
            scene_order += 1
            remaining = max(
                self.config.summary_minimum_duration_seconds,
                remaining - data_duration,
            )

        if story.map_path:
            map_duration = min(
                self.config.maximum_scene_duration_seconds,
                max(
                    self.config.minimum_scene_duration_seconds,
                    remaining * 0.25,
                ),
            )
            map_scene = self._make_scene(
                scene_id=f"{_slugify(story.story_id)}_map",
                story_id=story.story_id,
                order=scene_order,
                scene_type=SceneType.MAP,
                start=cursor,
                duration=map_duration,
                headline=story.headline,
                summary=story.summary,
                image_path=story.map_path,
                audio_path=story.audio_path,
                category=story.category,
                layout=LayoutType.MAP_PANEL,
                transition_in=TransitionType.CROSSFADE,
                transition_out=TransitionType.CROSSFADE,
                overlay="map_overlay",
                background="news_background",
                metadata=story.metadata,
            )
            scenes.append(map_scene)
            cursor = map_scene.end_time_seconds
            scene_order += 1
            remaining = max(
                self.config.summary_minimum_duration_seconds,
                remaining - map_duration,
            )

        if self.config.include_summary_scene:
            summary_status = (
                SceneStatus.READY
                if story.summary.strip()
                else SceneStatus.BLOCKED
            )
            summary_scene = self._make_scene(
                scene_id=f"{_slugify(story.story_id)}_summary",
                story_id=story.story_id,
                order=scene_order,
                scene_type=SceneType.SUMMARY,
                start=cursor,
                duration=remaining,
                headline=story.headline,
                summary=story.summary,
                image_path=story.image_path,
                audio_path=story.audio_path,
                category=story.category,
                layout=LayoutType.SUMMARY_PANEL,
                transition_in=TransitionType.CROSSFADE,
                transition_out=self.config.default_transition,
                overlay="summary_overlay",
                background="news_background",
                status=summary_status,
                metadata=story.metadata,
            )
            scenes.append(summary_scene)
            cursor = summary_scene.end_time_seconds
            scene_order += 1

        return scenes, cursor, scene_order

    def _make_scene(
        self,
        *,
        scene_id: str,
        story_id: str,
        order: int,
        scene_type: SceneType,
        start: float,
        duration: float,
        headline: str = "",
        summary: str = "",
        image_path: str = "",
        audio_path: str = "",
        category: str = "",
        layout: LayoutType = LayoutType.FULL_FRAME,
        transition_in: TransitionType = TransitionType.NONE,
        transition_out: TransitionType = TransitionType.NONE,
        overlay: str = "",
        background: str = "",
        status: SceneStatus = SceneStatus.READY,
        metadata: Mapping[str, Any] | None = None,
    ) -> Scene:
        duration = max(
            self.config.minimum_scene_duration_seconds,
            min(duration, self.config.maximum_scene_duration_seconds),
        )
        start = round(start, 2)
        duration = round(duration, 2)
        end = round(start + duration, 2)

        return Scene(
            scene_id=scene_id,
            story_id=story_id,
            order=order,
            scene_type=scene_type,
            status=status,
            start_time_seconds=start,
            duration_seconds=duration,
            end_time_seconds=end,
            headline=headline,
            summary=summary,
            image_path=image_path,
            audio_path=audio_path,
            category=category,
            layout=layout,
            transition_in=transition_in,
            transition_out=transition_out,
            overlay=overlay,
            background=background,
            metadata=dict(metadata or {}),
        )

    def _validate_timeline(self, timeline: SceneTimeline) -> None:
        if not timeline.scenes:
            raise ValueError("Scene timeline is empty.")

        previous_end = 0.0
        previous_order = 0

        for scene in timeline.scenes:
            if scene.order <= previous_order:
                raise ValueError("Scene order is not strictly increasing.")

            if abs(scene.start_time_seconds - previous_end) > 0.01:
                raise ValueError(
                    f"Timeline gap or overlap detected at {scene.scene_id}."
                )

            if scene.duration_seconds <= 0:
                raise ValueError(
                    f"Scene duration is invalid for {scene.scene_id}."
                )

            previous_order = scene.order
            previous_end = scene.end_time_seconds

        if abs(previous_end - timeline.total_duration_seconds) > 0.01:
            raise ValueError("Timeline total duration is inconsistent.")

    def write_manifest(self, timeline: SceneTimeline) -> Path:
        path = timeline.manifest_path
        if path is None:
            path = (
                self.config.output_dir
                / _slugify(timeline.bulletin_id, "bulletin")
                / self.config.manifest_filename
            )

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                timeline.to_dict(),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return path

    def summarize(
        self,
        timelines: Sequence[SceneTimeline],
    ) -> SceneBuilderSummary:
        return SceneBuilderSummary.from_timelines(timelines)


# =============================================================================
# CONVENIENCE API
# =============================================================================


def build_scene_timeline(
    *,
    bulletin_id: str,
    stories: Iterable[Any],
    config: SceneBuilderConfig | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SceneTimeline:
    return SceneBuilder(config=config).build_timeline(
        bulletin_id=bulletin_id,
        stories=stories,
        metadata=metadata,
    )


# =============================================================================
# SELF-TEST
# =============================================================================


def _run_self_test() -> None:
    with tempfile.TemporaryDirectory(
        prefix="bahuvu_scene_builder_test_"
    ) as temp_dir:
        config = SceneBuilderConfig(
            output_dir=Path(temp_dir) / "scenes",
            intro_duration_seconds=5.0,
            outro_duration_seconds=4.0,
            headline_duration_seconds=4.0,
            photo_duration_seconds=6.0,
            summary_minimum_duration_seconds=6.0,
            transition_duration_seconds=1.0,
            write_manifest=True,
        )

        builder = SceneBuilder(config=config)

        stories = [
            {
                "story_id": "story_weather",
                "order": 2,
                "headline": "తీర ప్రాంతాలకు భారీ వర్ష హెచ్చరిక",
                "summary": (
                    "భారత వాతావరణ శాఖ పలు జిల్లాలకు ఆరెంజ్ అలర్ట్ "
                    "జారీ చేసింది."
                ),
                "category": "weather",
                "image_path": "assets/images/weather.jpg",
                "audio_path": "outputs/audio/story_weather.mp3",
                "audio_duration_seconds": 22.0,
                "map_path": "assets/maps/ap_weather.png",
            },
            {
                "story_id": "story_governance",
                "order": 1,
                "headline": "కొత్త విద్యా కార్యక్రమానికి ఆమోదం",
                "summary": (
                    "రాష్ట్ర మంత్రివర్గం ప్రభుత్వ పాఠశాలల కోసం కొత్త "
                    "విద్యా కార్యక్రమాన్ని ఆమోదించింది."
                ),
                "category": "governance",
                "image_path": "assets/images/education.jpg",
                "audio_path": "outputs/audio/story_governance.mp3",
                "audio_duration_seconds": 18.0,
                "quote": "విద్యార్థులకు మెరుగైన అవకాశాలు కల్పిస్తాం.",
                "data_points": ["50,000 విద్యార్థులు", "మొదటి దశలో 120 పాఠశాలలు"],
            },
        ]

        timeline = builder.build_timeline(
            bulletin_id="bahuvu_july_demo",
            stories=stories,
            metadata={"edition": "July 2026"},
        )

        assert timeline.story_count == 2
        assert timeline.scene_count >= 8
        assert timeline.scenes[0].scene_type == SceneType.INTRO
        assert timeline.scenes[-1].scene_type == SceneType.OUTRO
        assert timeline.scenes[1].story_id == "story_governance"
        assert timeline.total_duration_seconds > 0
        assert timeline.manifest_path is not None
        assert timeline.manifest_path.exists()

        orders = [scene.order for scene in timeline.scenes]
        assert orders == sorted(orders)
        assert len(orders) == len(set(orders))

        for previous, current in zip(
            timeline.scenes,
            timeline.scenes[1:],
        ):
            assert previous.end_time_seconds == current.start_time_seconds

        loaded = json.loads(
            timeline.manifest_path.read_text(encoding="utf-8")
        )
        assert loaded["bulletin_id"] == "bahuvu_july_demo"
        assert loaded["story_count"] == 2
        assert loaded["scene_count"] == timeline.scene_count

        summary = builder.summarize([timeline])
        assert summary.timelines_processed == 1
        assert summary.stories_processed == 2
        assert summary.scenes_created == timeline.scene_count

        print("Graphics scene builder initialized successfully.")
        print()
        print(f"Stories processed       : {timeline.story_count}")
        print(f"Scenes created          : {timeline.scene_count}")
        print(
            f"Total timeline duration : "
            f"{timeline.total_duration_seconds:.2f} seconds"
        )
        print(
            f"Blocked scenes          : "
            f"{summary.blocked_scenes}"
        )
        print(f"Manifest written        : {timeline.manifest_path.exists()}")
        print(f"Production ready        : {timeline.production_ready}")
        print()
        print("Graphics scene builder self-test passed.")


if __name__ == "__main__":
    _run_self_test()