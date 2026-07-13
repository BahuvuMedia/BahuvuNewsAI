"""
BahuvuNewsAI - Production Integrations
=====================================

Connects the master production pipeline to the concrete BahuvuNewsAI modules.

This module provides real stage handlers for:

    intake
    editorial
    bulletin
    script
    polish
    translate
    voice
    audio
    scenes
    graphics
    video
    thumbnail
    upload

The integration layer is intentionally conservative. It preserves module
boundaries, validates required outputs between stages, and supports dry-run and
render-only execution without contacting YouTube.

Run:

    python -m py_compile production/integrations.py
    python -m production.integrations
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
import tempfile
from typing import Any, Iterable, Mapping, Sequence

from production.pipeline import (
    PipelineStage,
    ProductionMode,
    ProductionRequest,
    StageHandler,
)


# =============================================================================
# GENERIC HELPERS
# =============================================================================


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict"):
        converted = value.to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return list(value)
    return [value]


def _first_nonempty(mapping: Mapping[str, Any], names: Sequence[str]) -> Any:
    for name in names:
        if name in mapping and mapping[name] not in (None, "", [], {}):
            return mapping[name]
    return None


def _require_context(context: Mapping[str, Any], key: str) -> Any:
    if key not in context:
        raise ValueError(f"Required production context '{key}' is missing.")
    return context[key]


def _extract_output_path(value: Any) -> Path | None:
    if value is None:
        return None

    if isinstance(value, Path):
        return value

    mapping = _mapping(value)
    for key in (
        "output_path",
        "bulletin_audio_path",
        "path",
        "video_path",
        "thumbnail_path",
    ):
        candidate = mapping.get(key)
        if candidate:
            return Path(str(candidate))

    artifact = mapping.get("artifact")
    if artifact:
        artifact_mapping = _mapping(artifact)
        candidate = artifact_mapping.get("path")
        if candidate:
            return Path(str(candidate))

    return None


# =============================================================================
# NORMALIZATION HELPERS
# =============================================================================


def _story_to_audio_input(story: Any, order: int) -> dict[str, Any]:
    mapping = _mapping(story)

    return {
        "story_id": _safe_text(
            _first_nonempty(mapping, ("story_id", "article_id", "id"))
            or f"story_{order:03d}"
        ),
        "order": int(
            _first_nonempty(mapping, ("order", "position", "rank"))
            or order
        ),
        "headline": _safe_text(
            _first_nonempty(
                mapping,
                (
                    "headline",
                    "translated_headline",
                    "telugu_headline",
                    "title",
                ),
            )
            or ""
        ),
        "intro": _safe_text(
            _first_nonempty(
                mapping,
                (
                    "intro",
                    "translated_intro",
                    "telugu_intro",
                ),
            )
            or ""
        ),
        "body": _safe_text(
            _first_nonempty(
                mapping,
                (
                    "body",
                    "translated_body",
                    "telugu_body",
                    "content",
                    "translated_text",
                    "text",
                    "script",
                ),
            )
            or ""
        ),
        "closing": _safe_text(
            _first_nonempty(
                mapping,
                (
                    "closing",
                    "translated_closing",
                    "telugu_closing",
                    "outro",
                ),
            )
            or ""
        ),
        "language": _safe_text(
            _first_nonempty(mapping, ("language", "language_code"))
            or "te"
        ),
        "category": _safe_text(mapping.get("category") or ""),
        "metadata": dict(mapping.get("metadata") or {}),
    }


def _story_to_scene_input(
    story: Any,
    order: int,
    audio_item: Any | None = None,
) -> dict[str, Any]:
    mapping = _mapping(story)
    audio_mapping = _mapping(audio_item) if audio_item is not None else {}

    return {
        "story_id": _safe_text(
            _first_nonempty(mapping, ("story_id", "article_id", "id"))
            or f"story_{order:03d}"
        ),
        "order": int(
            _first_nonempty(mapping, ("order", "position", "rank"))
            or order
        ),
        "headline": _safe_text(
            _first_nonempty(
                mapping,
                (
                    "headline",
                    "translated_headline",
                    "telugu_headline",
                    "title",
                ),
            )
            or ""
        ),
        "summary": _safe_text(
            _first_nonempty(
                mapping,
                (
                    "summary",
                    "translated_summary",
                    "body",
                    "translated_body",
                    "content",
                    "translated_text",
                ),
            )
            or ""
        ),
        "category": _safe_text(mapping.get("category") or ""),
        "image_path": _safe_text(
            _first_nonempty(
                mapping,
                (
                    "image_path",
                    "photo_path",
                    "image_url",
                ),
            )
            or ""
        ),
        "audio_path": _safe_text(
            audio_mapping.get("audio_path")
            or audio_mapping.get("path")
            or ""
        ),
        "audio_duration_seconds": float(
            audio_mapping.get("duration_seconds") or 0.0
        ),
        "quote": _safe_text(mapping.get("quote") or ""),
        "data_points": list(mapping.get("data_points") or []),
        "map_path": _safe_text(mapping.get("map_path") or ""),
        "metadata": dict(mapping.get("metadata") or {}),
    }


# =============================================================================
# STAGE HANDLERS
# =============================================================================


def intake_handler(
    context: dict[str, Any],
    request: ProductionRequest,
) -> Any:
    stories = list(context.get("stories") or request.stories)

    if not stories:
        raise ValueError("Production intake received no stories.")

    return stories

def editorial_handler(
    context: dict[str, Any],
    request: ProductionRequest,
) -> Any:
    """Run the complete Bahuvu editorial selection workflow.

    Workflow:
        intake
        -> deduplication
        -> article scoring
        -> editorial validation
        -> story ranking
        -> selected production stories

    The handler deliberately returns the original NewsArticle objects after
    enriching them with scoring and validation information. This preserves
    compatibility with BulletinBuilder and all downstream production stages.
    """

    stories = _as_list(
        _require_context(context, PipelineStage.INTAKE.value)
    )

    if not stories:
        raise ValueError(
            "Editorial stage received no stories from production intake."
        )

    try:
        from news.article_scorer import score_articles
        from news.deduplicator import deduplicate_articles
        from news.editorial_validator import validate_articles
        from news.models import ArticleStatus
        from news.story_ranker import rank_stories
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(
            "The Bahuvu editorial modules could not be loaded."
        ) from exc

    # ---------------------------------------------------------------------
    # 1. DEDUPLICATION
    # ---------------------------------------------------------------------

    deduplication_result = deduplicate_articles(stories)
    unique_articles = list(deduplication_result.unique_articles)

    if not unique_articles:
        raise ValueError(
            "Editorial deduplication removed every incoming story."
        )

    # ---------------------------------------------------------------------
    # 2. ARTICLE SCORING
    # ---------------------------------------------------------------------

    score_results = score_articles(
        unique_articles,
        sort_descending=True,
    )

    score_by_article_id = {
        str(result.article_id): result
        for result in score_results
    }

    # Attach scoring results to their original article objects so the story
    # ranker receives the complete editorial information.
    for article in unique_articles:
        article_id = str(
            getattr(article, "article_id", "")
            or getattr(article, "id", "")
            or ""
        )
        score_result = score_by_article_id.get(article_id)

        if score_result is None:
            continue

        if hasattr(article, "score"):
            article.score = float(score_result.final_score)

        if hasattr(article, "confidence"):
            article.confidence = float(score_result.confidence)

        if hasattr(article, "decision"):
            article.decision = str(
                getattr(
                    score_result.decision,
                    "value",
                    score_result.decision,
                )
            )

        metadata = dict(getattr(article, "metadata", {}) or {})
        metadata["editorial_score"] = float(
            score_result.final_score
        )
        metadata["base_score"] = float(
            score_result.base_score
        )
        metadata["scoring_confidence"] = float(
            score_result.confidence
        )
        metadata["scoring_decision"] = str(
            getattr(
                score_result.decision,
                "value",
                score_result.decision,
            )
        )
        metadata["scoring_band"] = str(
            getattr(
                score_result.band,
                "value",
                score_result.band,
            )
        )
        metadata["scoring_reasons"] = list(
            score_result.reasons
        )
        metadata["scoring_warnings"] = list(
            score_result.warnings
        )

        if hasattr(article, "metadata"):
            article.metadata = metadata

    # ---------------------------------------------------------------------
    # 3. EDITORIAL VALIDATION
    # ---------------------------------------------------------------------

    validation_results = validate_articles(
        unique_articles,
        score_results=score_results,
        sort_by_score=True,
    )

    validation_by_article_id = {
        str(result.article_id): result
        for result in validation_results
    }

    production_ready_articles = []

    for article in unique_articles:
        article_id = str(
            getattr(article, "article_id", "")
            or getattr(article, "id", "")
            or ""
        )
        validation_result = validation_by_article_id.get(
            article_id
        )

        if validation_result is None:
            continue

        metadata = dict(getattr(article, "metadata", {}) or {})
        metadata["validation_score"] = float(
            validation_result.score
        )
        metadata["validation_confidence"] = float(
            validation_result.confidence
        )
        metadata["validation_decision"] = str(
            getattr(
                validation_result.decision,
                "value",
                validation_result.decision,
            )
        )
        metadata["validation_valid"] = bool(
            validation_result.valid
        )
        metadata["production_ready"] = bool(
            validation_result.production_ready
        )
        metadata["validation_reasons"] = list(
            validation_result.reasons
        )
        metadata["validation_warnings"] = list(
            validation_result.warnings
        )
        metadata["validation_errors"] = list(
            validation_result.errors
        )

        if hasattr(article, "metadata"):
            article.metadata = metadata

        if validation_result.production_ready:
            if hasattr(article, "status"):
                article.status = ArticleStatus.VALIDATED

            production_ready_articles.append(article)

    if not production_ready_articles:
        rejection_details: list[str] = []

        for result in validation_results[:5]:
            article_identifier = str(
                getattr(result, "article_id", "unknown")
            )
            decision = str(
                getattr(
                    getattr(result, "decision", ""),
                    "value",
                    getattr(result, "decision", ""),
                )
            )
            score = float(getattr(result, "score", 0.0) or 0.0)
            confidence = float(
                getattr(result, "confidence", 0.0) or 0.0
            )

            reasons = list(
                getattr(result, "reasons", []) or []
            )
            warnings = list(
                getattr(result, "warnings", []) or []
            )
            errors = list(
                getattr(result, "errors", []) or []
            )

            messages = [
                str(value)
                for value in reasons + warnings + errors
                if str(value).strip()
            ]

            valid = bool(
                getattr(result, "valid", False)
            )
            production_ready = bool(
                getattr(result, "production_ready", False)
            )

            detail = (
                f"{article_identifier}: decision={decision}, "
                f"score={score:.2f}, confidence={confidence:.2f}, "
                f"valid={valid}, "
                f"production_ready={production_ready}"
            )

            if messages:
                detail += "; " + " | ".join(messages[:8])

            rejection_details.append(detail)

        diagnostic = (
            " No stories passed editorial validation for production."
        )

        if rejection_details:
            diagnostic += " Details: " + " || ".join(
                rejection_details
            )

        raise ValueError(diagnostic)

    # ---------------------------------------------------------------------
    # 4. STORY RANKING AND BULLETIN SELECTION
    # ---------------------------------------------------------------------

    ranking_result = rank_stories(
        production_ready_articles
    )

    selected_stories = list(
        ranking_result.selected_stories
    )

    if not selected_stories:
        raise ValueError(
            "Story ranking produced no selected bulletin stories."
        )

    # Preserve a compact audit trail for the production manifest.
    context["editorial_audit"] = {
        "input_articles": len(stories),
        "unique_articles": deduplication_result.unique_count,
        "duplicate_articles": deduplication_result.duplicate_count,
        "scored_articles": len(score_results),
        "validated_articles": len(validation_results),
        "production_ready_articles": len(
            production_ready_articles
        ),
        "selected_articles": len(selected_stories),
        "reserve_articles": len(
            ranking_result.reserve_stories
        ),
        "rejected_articles": len(
            ranking_result.rejected_stories
        ),
    }

    return selected_stories


def bulletin_handler(
    context: dict[str, Any],
    request: ProductionRequest,
) -> Any:
    stories = _as_list(
        _require_context(context, PipelineStage.EDITORIAL.value)
    )

    try:
        from news.bulletin import BulletinBuilder  # type: ignore
    except (ImportError, AttributeError):
        return {
            "bulletin_id": request.bulletin_id or request.production_id,
            "stories": stories,
            "metadata": dict(request.metadata),
        }

    builder = BulletinBuilder()
    if hasattr(builder, "build"):
        return builder.build(stories)
    if hasattr(builder, "build_bulletin"):
        return builder.build_bulletin(stories)

    return {
        "bulletin_id": request.bulletin_id or request.production_id,
        "stories": stories,
        "metadata": dict(request.metadata),
    }


def script_handler(
    context: dict[str, Any],
    request: ProductionRequest,
) -> Any:
    bulletin = _require_context(
        context,
        PipelineStage.BULLETIN.value,
    )

    try:
        from news.script_generator import ScriptGenerator  # type: ignore
    except (ImportError, AttributeError):
        return bulletin

    generator = ScriptGenerator()

    for method_name in (
        "generate",
        "generate_script",
        "build",
    ):
        method = getattr(generator, method_name, None)
        if callable(method):
            return method(bulletin)

    return bulletin


def polish_handler(
    context: dict[str, Any],
    request: ProductionRequest,
) -> Any:
    script = _require_context(
        context,
        PipelineStage.SCRIPT.value,
    )

    from news.editorial_polisher import EditorialPolisher

    polisher = EditorialPolisher()

    if isinstance(script, list):
        return polisher.polish_many(script)

    return polisher.polish(script)


def translate_handler(
    context: dict[str, Any],
    request: ProductionRequest,
) -> Any:
    polished = _require_context(
        context,
        PipelineStage.POLISH.value,
    )

    try:
        from news.telugu_translator import TeluguTranslator  # type: ignore
    except (ImportError, AttributeError):
        return polished

    translator = TeluguTranslator()

    for method_name in (
        "translate",
        "translate_script",
        "translate_many",
    ):
        method = getattr(translator, method_name, None)
        if callable(method):
            try:
                return method(polished)
            except TypeError:
                continue

    return polished


def voice_handler(
    context: dict[str, Any],
    request: ProductionRequest,
) -> Any:
    translated = _require_context(
        context,
        PipelineStage.TRANSLATE.value,
    )

    from voice.tts_generator import TeluguTTSGenerator

    generator = TeluguTTSGenerator()

    if isinstance(translated, list):
        return generator.generate_many(translated)

    return generator.generate(translated)


def audio_handler(
    context: dict[str, Any],
    request: ProductionRequest,
) -> Any:
    translated = _require_context(
        context,
        PipelineStage.TRANSLATE.value,
    )

    from voice.audio_manager import BulletinAudioManager

    manager = BulletinAudioManager()

    story_values = _as_list(translated)
    normalized = [
        _story_to_audio_input(story, index)
        for index, story in enumerate(story_values, start=1)
    ]

    return manager.generate_bulletin(
        bulletin_id=request.bulletin_id or request.production_id,
        stories=normalized,
        metadata=dict(request.metadata),
    )


def scenes_handler(
    context: dict[str, Any],
    request: ProductionRequest,
) -> Any:
    translated = _require_context(
        context,
        PipelineStage.TRANSLATE.value,
    )
    audio_manifest = _require_context(
        context,
        PipelineStage.AUDIO.value,
    )

    from graphics.scene_builder import SceneBuilder

    manager_stories = _mapping(audio_manifest).get("stories")
    if manager_stories is None and hasattr(audio_manifest, "stories"):
        manager_stories = audio_manifest.stories
    audio_items = _as_list(manager_stories)

    audio_by_story = {
        _safe_text(
            _mapping(item).get("story_id")
            or getattr(item, "story_id", "")
        ): item
        for item in audio_items
    }

    story_values = _as_list(translated)
    scene_stories = []

    for index, story in enumerate(story_values, start=1):
        story_mapping = _mapping(story)
        story_id = _safe_text(
            _first_nonempty(
                story_mapping,
                ("story_id", "article_id", "id"),
            )
            or f"story_{index:03d}"
        )
        scene_stories.append(
            _story_to_scene_input(
                story,
                index,
                audio_by_story.get(story_id),
            )
        )

    builder = SceneBuilder()
    return builder.build_timeline(
        bulletin_id=request.bulletin_id or request.production_id,
        stories=scene_stories,
        metadata=dict(request.metadata),
    )


def graphics_handler(
    context: dict[str, Any],
    request: ProductionRequest,
) -> Any:
    timeline = _require_context(
        context,
        PipelineStage.SCENES.value,
    )

    from graphics.graphics_renderer import GraphicsRenderer

    renderer = GraphicsRenderer()
    return renderer.render_timeline(
        timeline,
        metadata=dict(request.metadata),
    )


def video_handler(
    context: dict[str, Any],
    request: ProductionRequest,
) -> Any:
    timeline = _require_context(
        context,
        PipelineStage.SCENES.value,
    )
    graphics_manifest = _require_context(
        context,
        PipelineStage.GRAPHICS.value,
    )
    audio_manifest = _require_context(
        context,
        PipelineStage.AUDIO.value,
    )

    from video.video_composer import VideoComposer

    audio_path = None
    if hasattr(audio_manifest, "bulletin_audio_path"):
        audio_path = audio_manifest.bulletin_audio_path
    else:
        audio_path = _mapping(audio_manifest).get(
            "bulletin_audio_path"
        )

    composer = VideoComposer()
    return composer.compose_from_manifests(
        timeline=timeline,
        graphics_manifest=graphics_manifest,
        bulletin_audio_path=audio_path,
        metadata=dict(request.metadata),
    )


def thumbnail_handler(
    context: dict[str, Any],
    request: ProductionRequest,
) -> Any:
    translated = _require_context(
        context,
        PipelineStage.TRANSLATE.value,
    )

    stories = _as_list(translated)
    if not stories:
        raise ValueError("No translated story available for thumbnail.")

    lead = _mapping(stories[0])

    from thumbnail.thumbnail_generator import (
        ThumbnailGenerator,
        ThumbnailInput,
    )

    generator = ThumbnailGenerator()

    thumbnail_input = ThumbnailInput(
        headline=_safe_text(
            _first_nonempty(
                lead,
                (
                    "headline",
                    "translated_headline",
                    "telugu_headline",
                    "title",
                ),
            )
            or "BAHUVU NEWS"
        ),
        category=_safe_text(lead.get("category") or "NEWS"),
        image_path=_safe_text(
            _first_nonempty(
                lead,
                (
                    "image_path",
                    "photo_path",
                    "image_url",
                ),
            )
            or ""
        ),
        bulletin_id=request.bulletin_id or request.production_id,
        story_id=_safe_text(
            _first_nonempty(
                lead,
                ("story_id", "article_id", "id"),
            )
            or ""
        ),
        subheadline=_safe_text(
            _first_nonempty(
                lead,
                (
                    "summary",
                    "translated_summary",
                    "body",
                    "translated_body",
                ),
            )
            or ""
        ),
        metadata=dict(request.metadata),
    )

    return generator.generate(thumbnail_input)


def upload_handler(
    context: dict[str, Any],
    request: ProductionRequest,
) -> Any:
    video_result = _require_context(
        context,
        PipelineStage.VIDEO.value,
    )
    thumbnail_result = context.get(
        PipelineStage.THUMBNAIL.value
    )

    from youtube.uploader import (
        PrivacyStatus,
        YouTubeUploader,
        YouTubeVideoMetadata,
    )

    video_path = _extract_output_path(video_result)
    if video_path is None:
        raise ValueError("Video output path is unavailable for upload.")

    thumbnail_path = _extract_output_path(thumbnail_result)

    privacy = (
        PrivacyStatus.PRIVATE
        if request.mode == ProductionMode.UPLOAD_PRIVATE
        else PrivacyStatus.PUBLIC
    )

    title = _safe_text(
        request.metadata.get("youtube_title")
        or request.metadata.get("title")
        or f"BAHUVU NEWS - {request.production_id}"
    )

    description = _safe_text(
        request.metadata.get("youtube_description")
        or request.metadata.get("description")
        or ""
    )

    tags = request.metadata.get("youtube_tags") or [
        "Bahuvu News",
        "Telugu News",
    ]

    metadata = YouTubeVideoMetadata(
        title=title,
        description=description,
        tags=list(tags),
        category_id=_safe_text(
            request.metadata.get("youtube_category_id")
            or "25"
        ),
        privacy_status=privacy,
        default_language="te",
        default_audio_language="te",
        made_for_kids=False,
        playlist_id=_safe_text(
            request.metadata.get("youtube_playlist_id")
            or ""
        ),
    )

    uploader = YouTubeUploader()

    dry_run = request.mode in {
        ProductionMode.DRY_RUN,
        ProductionMode.RENDER_ONLY,
    }

    return uploader.upload(
        video_path=video_path,
        thumbnail_path=thumbnail_path,
        metadata=metadata,
        bulletin_id=request.bulletin_id or request.production_id,
        dry_run=dry_run,
    )


# =============================================================================
# FACTORY
# =============================================================================


def build_integrated_handlers() -> dict[PipelineStage, StageHandler]:
    return {
        PipelineStage.INTAKE: intake_handler,
        PipelineStage.EDITORIAL: editorial_handler,
        PipelineStage.BULLETIN: bulletin_handler,
        PipelineStage.SCRIPT: script_handler,
        PipelineStage.POLISH: polish_handler,
        PipelineStage.TRANSLATE: translate_handler,
        PipelineStage.VOICE: voice_handler,
        PipelineStage.AUDIO: audio_handler,
        PipelineStage.SCENES: scenes_handler,
        PipelineStage.GRAPHICS: graphics_handler,
        PipelineStage.VIDEO: video_handler,
        PipelineStage.THUMBNAIL: thumbnail_handler,
        PipelineStage.UPLOAD: upload_handler,
    }


# =============================================================================
# OFFLINE-SAFE SELF-TEST
# =============================================================================


def _run_self_test() -> None:
    handlers = build_integrated_handlers()

    assert set(handlers) == set(PipelineStage)
    assert callable(handlers[PipelineStage.INTAKE])
    assert callable(handlers[PipelineStage.VIDEO])
    assert callable(handlers[PipelineStage.UPLOAD])

    from datetime import datetime, timezone

    from news.models import (
        ArticleStatus,
        LanguageCode,
        NewsArticle,
        NewsCategory,
    )

    strong_content = """
    The Andhra Pradesh government issued a weather alert after heavy rain
    affected several districts. Officials said emergency teams were deployed
    and local administrations were instructed to monitor reservoirs, roads,
    drainage systems, and low-lying residential areas.

    The India Meteorological Department forecast further rainfall during the
    next twenty-four hours. District authorities advised residents to avoid
    flooded roads, follow official warnings, and report local emergencies to
    control rooms established in affected areas.

    Electricity, municipal, irrigation, and disaster-response teams began
    responding to local reports. Farmers were advised to protect harvested
    crops, livestock, agricultural equipment, and stored produce from
    continuing rain and possible waterlogging.

    Officials said the situation remained under observation and confirmed
    that additional response teams would be deployed if conditions worsened.
    Authorities also said reservoir levels, transport routes, and vulnerable
    communities would continue to be monitored.
    """

    sample_article = NewsArticle(
        article_id="story_001",
        title=(
            "Heavy Rain Alert Issued Across Andhra Pradesh "
            "as Officials Deploy Emergency Teams"
        ),
        url=(
            "https://www.thehindu.com/news/national/"
            "andhra-pradesh/weather-alert"
        ),
        source_id="the_hindu_integration_test",
        source_name="The Hindu",
        publisher="The Hindu",
        author="Staff Reporter",
        status=ArticleStatus.COLLECTED,
        category=NewsCategory.WEATHER,
        language=LanguageCode.ENGLISH,
        description=(
            "Authorities placed several districts on alert as heavy "
            "rainfall continued across Andhra Pradesh."
        ),
        raw_text=strong_content,
        cleaned_text=strong_content,
        summary=(
            "Authorities placed several districts on alert as heavy "
            "rainfall continued across Andhra Pradesh."
        ),
        image_url=(
            "https://images.example.org/rain-alert.jpg"
        ),
        canonical_url=(
            "https://www.thehindu.com/news/national/"
            "andhra-pradesh/weather-alert"
        ),
        published_at=datetime.now(timezone.utc),
        reliability_score=95.0,
        relevance_score=94.0,
        importance_score=92.0,
        editorial_score=91.0,
        tags=[
            "weather",
            "andhra pradesh",
            "heavy rain",
            "emergency",
        ],
        keywords=[
            "Andhra Pradesh",
            "heavy rain",
            "weather alert",
            "emergency teams",
            "IMD",
        ],
        metadata={
            "integration_test": True,
            "country": "India",
            "region": "Andhra Pradesh",
            "location": "Andhra Pradesh, India",
            "source_reliability": 95.0,
            "duplicate": False,
            "duplicate_score": 0.10,
        },
    )

    request = ProductionRequest(
        production_id="bahuvu_integration_demo",
        mode=ProductionMode.DRY_RUN,
        stories=[sample_article],
    )

    context: dict[str, Any] = {
        "stories": list(request.stories),
    }

    intake_output = intake_handler(context, request)
    assert len(intake_output) == 1

    context[PipelineStage.INTAKE.value] = intake_output
    editorial_output = editorial_handler(context, request)
    assert editorial_output == intake_output

    audio_input = _story_to_audio_input(
        {
            "id": "story_001",
            "title": "వార్త శీర్షిక",
            "translated_text": "ఇది వార్త కథనం.",
            "language": "te",
        },
        1,
    )
    assert audio_input["story_id"] == "story_001"
    assert audio_input["headline"] == "వార్త శీర్షిక"
    assert audio_input["body"] == "ఇది వార్త కథనం."

    scene_input = _story_to_scene_input(
        {
            "id": "story_001",
            "title": "వార్త శీర్షిక",
            "summary": "వార్త సారాంశం.",
            "image_path": "assets/images/sample.jpg",
        },
        1,
        {
            "story_id": "story_001",
            "audio_path": "outputs/audio/story_001.mp3",
            "duration_seconds": 12.5,
        },
    )
    assert scene_input["audio_duration_seconds"] == 12.5
    assert scene_input["audio_path"].endswith("story_001.mp3")

    print("Production integrations initialized successfully.")
    print()
    print(f"Handlers registered     : {len(handlers)}")
    print(f"Intake mapping tested   : {len(intake_output)} story")
    print(f"Audio mapping tested    : {audio_input['story_id']}")
    print(f"Scene mapping tested    : {scene_input['story_id']}")
    print(f"Dry-run compatible      : {request.mode.value}")
    print()
    print("Production integrations self-test passed.")


if __name__ == "__main__":
    _run_self_test()