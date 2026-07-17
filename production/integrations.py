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


def _bulletin_to_polisher_input(bulletin: Any) -> Any:
    """Convert a generated Bulletin into EditorialPolisher input.

    The script generator returns a structured Bulletin containing title,
    opening, sections, segments, closing, and full_script. The editorial
    polisher expects headline, intro, body, closing, language, and metadata.

    This adapter preserves the structured bulletin while assembling only the
    central bulletin content into the body, avoiding duplicated opening and
    closing text.
    """

    from news.editorial_polisher import PolishedScriptInput

    mapping = _mapping(bulletin)

    title = _safe_text(
        _first_nonempty(
            mapping,
            (
                "headline",
                "title",
            ),
        )
        or "BAHUVU NEWS"
    )

    opening = _safe_text(
        _first_nonempty(
            mapping,
            (
                "intro",
                "opening",
                "lead",
            ),
        )
        or ""
    )

    closing = _safe_text(
        _first_nonempty(
            mapping,
            (
                "closing",
                "outro",
                "signoff",
            ),
        )
        or ""
    )

    language = _safe_text(
        _first_nonempty(
            mapping,
            (
                "language",
                "language_code",
            ),
        )
        or "en"
    )

    bulletin_id = _safe_text(
        _first_nonempty(
            mapping,
            (
                "bulletin_id",
                "script_id",
                "id",
            ),
        )
        or ""
    )

    body_parts: list[str] = []

    headlines = _as_list(mapping.get("headlines"))

    if headlines:
        body_parts.append("TOP HEADLINES")

        for index, headline in enumerate(headlines, start=1):
            headline_text = _safe_text(headline).strip()

            if headline_text:
                body_parts.append(f"{index}. {headline_text}")

    sections = _as_list(mapping.get("sections"))

    for section in sections:
        section_mapping = _mapping(section)

        section_title = _safe_text(
            _first_nonempty(
                section_mapping,
                (
                    "title",
                    "section_title",
                    "section_type",
                ),
            )
            or ""
        ).strip()

        if section_title:
            body_parts.append(section_title.upper())

        segments = _as_list(section_mapping.get("segments"))

        if segments:
            ordered_segments = sorted(
                segments,
                key=lambda item: int(
                    _mapping(item).get("sequence") or 0
                ),
            )

            for segment in ordered_segments:
                segment_mapping = _mapping(segment)
                text = _safe_text(
                    _first_nonempty(
                        segment_mapping,
                        (
                            "text",
                            "body",
                            "content",
                            "narration",
                        ),
                    )
                    or ""
                ).strip()

                if text:
                    body_parts.append(text)

            continue

        stories = _as_list(section_mapping.get("stories"))

        for story in stories:
            story_mapping = _mapping(story)

            for field_name in (
                "anchor_intro",
                "body",
                "context",
            ):
                text = _safe_text(
                    story_mapping.get(field_name)
                ).strip()

                if text:
                    body_parts.append(text)

    body = "\n\n".join(
        part.strip()
        for part in body_parts
        if part and part.strip()
    )

    if not body:
        full_script = _safe_text(
            mapping.get("full_script")
        ).strip()

        if full_script:
            body = full_script

            if opening and body.startswith(opening):
                body = body[len(opening):].strip()

            if closing and body.endswith(closing):
                body = body[:-len(closing)].strip()

    if not body:
        raise ValueError(
            "The generated bulletin could not be converted into a "
            "non-empty editorial script body."
        )

    metadata = dict(mapping.get("metadata") or {})
    metadata["bulletin_adapter"] = {
        "source_type": type(bulletin).__name__,
        "source_bulletin_id": bulletin_id,
        "headlines_preserved": len(headlines),
        "sections_preserved": len(sections),
        "body_character_count": len(body),
        "structured_conversion": bool(sections),
    }

    return PolishedScriptInput(
        headline=title,
        intro=opening,
        body=body,
        closing=closing,
        language=language,
        source_script_id=bulletin_id,
        metadata=metadata,
    )

def _remove_newsroom_boilerplate(value: str) -> str:
    """Remove known publisher subscription and navigation boilerplate."""

    markers = (
        "subscribed with another email",
        "logout and login",
        "account subscription benefits",
        "premium stories",
        "unlock these with subscription",
        "the view from india",
        "first day first show",
        "today's cache",
        "your download of the top 5 technology stories",
        "science for",
    )

    cleaned_parts: list[str] = []

    for part in value.split("\n\n"):
        normalized = part.strip()

        prefix, separator, remainder = normalized.partition(" ")

        if (
            separator
            and prefix.endswith(".")
            and prefix[:-1].isdigit()
        ):
            normalized = remainder.strip()

        lowered = normalized.casefold()

        if not normalized:
            continue

        if any(marker in lowered for marker in markers):
            continue

        cleaned_parts.append(normalized)

    return "\n\n".join(cleaned_parts)


def _translate_polishing_result(polished: Any) -> Any:
    """Translate a PolishingResult into a Telugu PolishedScript.

    The editorial stage returns PolishingResult, while the Telugu translation
    backend accepts TranslationRequest. This adapter translates the headline,
    intro, body, and closing, validates the output, preserves editorial
    metadata, and refuses to silently pass English through.
    """

    from news.editorial_polisher import PolishedScript
    from news.telugu_editorial_desk import edit_telugu_bulletin
    from news.telugu_translator import TranslationRequest
    from news.translator_factory import create_translator

    polished_mapping = _mapping(polished)

    script_value = polished_mapping.get("script")

    if script_value is None and hasattr(polished, "script"):
        script_value = getattr(polished, "script")

    script_mapping = _mapping(script_value)

    if not script_mapping:
        raise ValueError(
            "Translation stage received no polished script."
        )

    headline = _safe_text(
        script_mapping.get("headline")
    ).strip()

    intro = _safe_text(
        script_mapping.get("intro")
    ).strip()

    body = _remove_newsroom_boilerplate(
        _safe_text(
            script_mapping.get("body")
        ).strip()
    )

    closing = _safe_text(
        script_mapping.get("closing")
    ).strip()

    source_script_id = _safe_text(
        script_mapping.get("source_script_id")
    ).strip()

    if not headline:
        raise ValueError(
            "Translation stage received an empty headline."
        )

    if not body:
        raise ValueError(
            "Translation stage received an empty script body."
        )

    translator = create_translator()

    backend = getattr(translator, "backend", None)
    validator = getattr(translator, "validator", None)

    if backend is None or not callable(
        getattr(backend, "translate", None)
    ):
        raise RuntimeError(
            "The configured Telugu translator does not expose a "
            "callable translation backend."
        )

    main_request = TranslationRequest(
        article_id=source_script_id or "bahuvu_bulletin",
        headline=headline,
        summary=intro,
        script=body,
        category="news bulletin",
        publisher="BAHUVU NEWS",
        source_name="BAHUVU NEWS",
        published_at="",
        keywords=(),
        style=(
            "natural professional Telugu television news; preserve all "
            "facts, names, numbers and section order; avoid literal or "
            "mechanical translation"
        ),
    )

    main_result = backend.translate(main_request)

    if validator is not None and callable(
        getattr(validator, "validate", None)
    ):
        main_warnings = validator.validate(
            main_request,
            main_result,
        )
    else:
        main_warnings = list(
            getattr(main_result, "warnings", []) or []
        )

    translated_closing = ""

    if closing:
        closing_request = TranslationRequest(
            article_id=(
                f"{source_script_id}_closing"
                if source_script_id
                else "bahuvu_bulletin_closing"
            ),
            headline="BAHUVU NEWS",
            summary=closing,
            script=closing,
            category="news bulletin closing",
            publisher="BAHUVU NEWS",
            source_name="BAHUVU NEWS",
            published_at="",
            keywords=(),
            style=(
                "natural professional Telugu television news closing; "
                "warm, concise and suitable for an anchor"
            ),
        )

        closing_result = backend.translate(closing_request)

        if validator is not None and callable(
            getattr(validator, "validate", None)
        ):
            closing_warnings = validator.validate(
                closing_request,
                closing_result,
            )
        else:
            closing_warnings = list(
                getattr(closing_result, "warnings", []) or []
            )

        translated_closing = _safe_text(
            getattr(closing_result, "telugu_script", "")
        ).strip()
    else:
        closing_result = None
        closing_warnings = []

    translated_headline = _safe_text(
        getattr(main_result, "telugu_headline", "")
    ).strip()

    translated_intro = _safe_text(
        getattr(main_result, "telugu_summary", "")
    ).strip()

    translated_body = _safe_text(
        getattr(main_result, "telugu_script", "")
    ).strip()

    if not translated_headline:
        raise ValueError(
            "Telugu translation produced an empty headline."
        )

    if not translated_body:
        raise ValueError(
            "Telugu translation produced an empty body."
        )

    telugu_character_count = sum(
        1
        for character in (
            translated_headline
            + translated_intro
            + translated_body
            + translated_closing
        )
        if "\u0c00" <= character <= "\u0c7f"
    )

    if telugu_character_count == 0:
        raise ValueError(
            "Translation backend returned no Telugu characters."
        )

    metadata = dict(
        script_mapping.get("metadata") or {}
    )

    editorial_result = edit_telugu_bulletin(
        headline=translated_headline,
        intro=translated_intro,
        body=translated_body,
        closing=translated_closing,
        strict=False,
        source_id=source_script_id,
        metadata=metadata,
    )

    translated_headline = editorial_result.headline
    translated_intro = editorial_result.intro
    translated_body = editorial_result.body
    translated_closing = editorial_result.closing

    metadata["telugu_editorial_desk"] = {
        "approved": editorial_result.approved,
        "changes_applied": len(editorial_result.changes),
        "quality_issues": len(editorial_result.issues),
        "changes": list(editorial_result.changes),
        "issues": [
            {
                "code": issue.code,
                "severity": issue.severity.value,
                "field": issue.field_name,
                "message": issue.message,
                "detail": issue.detail,
            }
            for issue in editorial_result.issues
        ],
        "strict_mode": False,
    }

    metadata["translation"] = {
        "source_language": (
            _safe_text(
                script_mapping.get("language")
            ).strip()
            or "en"
        ),
        "target_language": "te",
        "provider": _safe_text(
            getattr(main_result, "provider", "")
        ),
        "model": _safe_text(
            getattr(main_result, "model", "")
        ),
        "closing_provider": _safe_text(
            getattr(closing_result, "provider", "")
            if closing_result is not None
            else ""
        ),
        "closing_model": _safe_text(
            getattr(closing_result, "model", "")
            if closing_result is not None
            else ""
        ),
        "telugu_character_count": telugu_character_count,
        "main_warnings": list(main_warnings),
        "closing_warnings": list(closing_warnings),
        "validated": True,
        "english_passthrough": False,
    }

    return PolishedScript(
        headline=translated_headline,
        intro=translated_intro,
        body=translated_body,
        closing=translated_closing,
        language="te",
        source_script_id=source_script_id,
        metadata=metadata,
    )

# =============================================================================
# NORMALIZATION HELPERS
# =============================================================================


def _story_to_audio_input(story: Any, order: int) -> dict[str, Any]:
    mapping = _mapping(story)

    story_id = _safe_text(
        _first_nonempty(mapping, ("story_id", "article_id", "id"))
        or f"story_{order:03d}"
    )
    headline = _safe_text(
        _first_nonempty(
            mapping,
            (
                "display_headline",
                "headline",
                "translated_headline",
                "telugu_headline",
                "title",
            ),
        )
        or ""
    ).strip()
    narration = _safe_text(
        _first_nonempty(
            mapping,
            (
                "speech_text",
                "anchor_narration",
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
    ).strip()

    if not narration:
        raise ValueError(
            f"Directed story '{story_id}' has no speech narration."
        )

    metadata = dict(mapping.get("metadata") or {})
    metadata["broadcast_director"] = {
        "display_summary": _safe_text(
            mapping.get("display_summary") or ""
        ),
        "anchor_narration": _safe_text(
            mapping.get("anchor_narration") or ""
        ),
        "speech_text": narration,
        "production_ready": bool(
            mapping.get("production_ready", True)
        ),
        "warnings": list(mapping.get("warnings") or []),
        "blocking_errors": list(
            mapping.get("blocking_errors") or []
        ),
    }

    return {
        "story_id": story_id,
        "order": int(
            _first_nonempty(mapping, ("order", "position", "rank"))
            or order
        ),
        "headline": headline,
        "intro": "",
        "body": narration,
        "text": narration,
        "closing": "",
        "language": "te",
        "category": _safe_text(mapping.get("category") or ""),
        "metadata": metadata,
    }



def _story_to_scene_input(
    story: Any,
    order: int,
    audio_item: Any | None = None,
) -> dict[str, Any]:
    mapping = _mapping(story)
    audio_mapping = _mapping(audio_item) if audio_item is not None else {}

    story_id = _safe_text(
        _first_nonempty(mapping, ("story_id", "article_id", "id"))
        or f"story_{order:03d}"
    )
    headline = _safe_text(
        _first_nonempty(
            mapping,
            (
                "display_headline",
                "headline",
                "translated_headline",
                "telugu_headline",
                "title",
            ),
        )
        or ""
    ).strip()
    summary = _safe_text(
        _first_nonempty(
            mapping,
            (
                "display_summary",
                "summary",
                "translated_summary",
                "anchor_narration",
                "body",
                "translated_body",
                "content",
                "translated_text",
            ),
        )
        or ""
    ).strip()

    preferred_path = _safe_text(
        _first_nonempty(
            mapping,
            (
                "preferred_image_path",
                "image_path",
                "photo_path",
            ),
        )
        or ""
    ).strip()
    preferred_url = _safe_text(
        _first_nonempty(
            mapping,
            (
                "preferred_image_url",
                "image_url",
            ),
        )
        or ""
    ).strip()

    directed_scenes = list(mapping.get("scenes") or [])
    metadata = dict(mapping.get("metadata") or {})
    metadata["broadcast_director_scenes"] = directed_scenes
    metadata["visual_search_terms"] = list(
        mapping.get("visual_search_terms") or []
    )
    metadata["fallback_visual"] = next(
        (
            _safe_text(_mapping(scene).get("fallback_visual"))
            for scene in directed_scenes
            if _safe_text(
                _mapping(scene).get("fallback_visual")
            ).strip()
        ),
        "assets/images/bahuvu_newsroom_background.png",
    )

    return {
        "story_id": story_id,
        "order": int(
            _first_nonempty(mapping, ("order", "position", "rank"))
            or order
        ),
        "headline": headline,
        "summary": summary,
        "category": _safe_text(mapping.get("category") or ""),
        "image_path": preferred_path or preferred_url,
        "audio_path": _safe_text(
            audio_mapping.get("audio_path")
            or audio_mapping.get("path")
            or ""
        ),
        "audio_duration_seconds": float(
            audio_mapping.get("duration_seconds") or 0.0
        ),
        "quote": "",
        "data_points": [],
        "map_path": "",
        "metadata": metadata,
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

        final_score = float(score_result.final_score)
        scoring_confidence = float(score_result.confidence)

        # Keep both legacy and canonical score fields synchronized.
        # NewsArticle uses editorial_score, while some compatibility
        # models may expose score directly.
        if hasattr(article, "editorial_score"):
            article.editorial_score = final_score

        if hasattr(article, "score"):
            article.score = final_score

        if hasattr(article, "confidence"):
            article.confidence = scoring_confidence

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
        from news.script_generator_factory import (
            create_script_generator,
        )
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(
            "The Bahuvu script-generator factory could not be loaded."
        ) from exc

    # The script generator accepts a sequence of NewsArticle objects or
    # article mappings. The bulletin stage returns a wrapper containing
    # those stories, so extract them before invoking the generator.
    bulletin_mapping = _mapping(bulletin)

    stories = bulletin_mapping.get("stories")

    if stories is None and hasattr(bulletin, "stories"):
        stories = getattr(bulletin, "stories")

    article_values = _as_list(stories)

    if not article_values:
        raise ValueError(
            "The bulletin contains no stories for script generation."
        )

    generator = create_script_generator()

    try:
        generate_method = getattr(generator, "generate", None)

        if not callable(generate_method):
            raise TypeError(
                "The configured script generator has no callable "
                "'generate' method."
            )

        return generate_method(article_values)

    finally:
        close_method = getattr(generator, "close", None)

        if callable(close_method):
            close_method()

def polish_handler(
    context: dict[str, Any],
    request: ProductionRequest,
) -> Any:
    bulletin = _require_context(
        context,
        PipelineStage.SCRIPT.value,
    )

    from news.editorial_polisher import EditorialPolisher

    polisher = EditorialPolisher()

    if isinstance(bulletin, list):
        normalized_scripts = [
            _bulletin_to_polisher_input(item)
            for item in bulletin
        ]
        return polisher.polish_many(normalized_scripts)

    normalized_script = _bulletin_to_polisher_input(bulletin)

    result = polisher.polish(normalized_script)

    if not result.script.body.strip():
        raise ValueError(
            "Editorial polishing unexpectedly produced an empty body."
        )

    return result

def translate_handler(
    context: dict[str, Any],
    request: ProductionRequest,
) -> Any:
    _require_context(context, PipelineStage.POLISH.value)
    bulletin = _require_context(context, PipelineStage.BULLETIN.value)

    from production.broadcast_director import (
        BroadcastDirector,
        DirectorConfiguration,
        PlanStatus,
    )

    configuration = DirectorConfiguration(
        use_ai=bool(request.metadata.get("broadcast_director_ai", True)),
        require_ai=bool(
            request.metadata.get("broadcast_director_require_ai", False)
        ),
        min_telugu_ratio=float(
            request.metadata.get("minimum_telugu_ratio", 0.72)
        ),
        max_latin_words=int(
            request.metadata.get("maximum_latin_words", 3)
        ),
        preferred_provider=_safe_text(
            request.metadata.get("broadcast_director_provider")
            or "gemini"
        ),
        preferred_model=_safe_text(
            request.metadata.get("broadcast_director_model")
            or "gemini-flash-latest"
        ),
    )

    director = BroadcastDirector(configuration=configuration)
    plan = director.direct(
        bulletin,
        production_id=request.production_id,
    )

    context["broadcast_plan"] = plan
    context["broadcast_plan_dict"] = plan.to_dict()

    output_root = Path(
        request.metadata.get("output_dir")
        or Path("outputs/production") / request.production_id
    )
    plan_path = output_root / "broadcast_production_plan.json"
    plan.save_json(plan_path)
    context["broadcast_plan_path"] = str(plan_path)

    if plan.status is PlanStatus.BLOCKED:
        details = list(plan.blocking_errors)
        for story in plan.stories:
            details.extend(
                f"{story.story_id}: {error}"
                for error in story.blocking_errors
            )
        raise ValueError(
            "AI Broadcast Director blocked production. "
            + " | ".join(details[:20])
        )

    directed_stories: list[dict[str, Any]] = []
    for story in plan.stories:
        item = story.to_dict()
        item.update(
            {
                "id": story.story_id,
                "article_id": story.story_id,
                "order": story.rank,
                "headline": story.display_headline,
                "summary": story.display_summary,
                "body": story.speech_text,
                "text": story.speech_text,
                "translated_text": story.speech_text,
                "language": "te",
                "image_path": story.preferred_image_path,
                "image_url": story.preferred_image_url,
                "metadata": {
                    "broadcast_plan_path": str(plan_path),
                    "broadcast_plan_status": plan.status.value,
                    "anchor_narration": story.anchor_narration,
                    "speech_text": story.speech_text,
                    "pronunciation_notes": dict(
                        story.pronunciation_notes
                    ),
                    "visual_search_terms": list(
                        story.visual_search_terms
                    ),
                    "directed_scenes": [
                        scene.to_dict() for scene in story.scenes
                    ],
                    "warnings": list(story.warnings),
                },
            }
        )
        directed_stories.append(item)

    if not directed_stories:
        raise ValueError(
            "AI Broadcast Director produced no downstream stories."
        )

    return directed_stories


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
    narration_inputs: list[dict[str, Any]] = []

    for index, story in enumerate(
        _as_list(translated),
        start=1,
    ):
        mapping = _mapping(story)
        story_id = _safe_text(
            _first_nonempty(
                mapping,
                ("story_id", "article_id", "id"),
            )
            or f"story_{index:03d}"
        )
        speech_text = _safe_text(
            _first_nonempty(
                mapping,
                (
                    "speech_text",
                    "text",
                    "translated_text",
                    "body",
                ),
            )
            or ""
        ).strip()
        if not speech_text:
            raise ValueError(
                f"Directed story '{story_id}' has empty speech text."
            )

        narration_inputs.append(
            {
                "story_id": story_id,
                "title": _safe_text(
                    mapping.get("display_headline")
                    or mapping.get("headline")
                    or ""
                ),
                "text": speech_text,
                "language": "te",
                "metadata": dict(mapping.get("metadata") or {}),
            }
        )

    results = generator.generate_many(narration_inputs)
    failures = [
        result
        for result in results
        if not bool(getattr(result, "success", False))
    ]
    if failures:
        messages = [
            _safe_text(getattr(result, "error", "TTS failed"))
            for result in failures
        ]
        raise RuntimeError(
            "Telugu voice generation failed: "
            + " | ".join(messages[:10])
        )

    return results



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