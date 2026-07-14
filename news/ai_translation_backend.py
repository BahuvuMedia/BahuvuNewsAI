"""
BahuvuNewsAI unified AI translation backend.

This module connects the existing Telugu translation subsystem to the unified
AI manager without modifying the proven ``news.telugu_translator`` module.

Routing behavior:

    Gemini -> deterministic offline provider

The adapter translates the headline, summary, and script independently,
preserves the translator's existing request/result contract, records which
provider and model handled each field, and warns when offline fallback is used.

The executable self-test runs entirely offline and does not require API keys or
network connectivity.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from ai.manager import AIManager, create_ai_manager
from ai.router import RoutingMode
from news.telugu_translator import (
    TranslationProviderError,
    TranslationRequest,
    TranslationResult,
)


__all__ = [
    "AITranslationBackendConfiguration",
    "UnifiedAITranslationBackend",
    "create_ai_translation_backend",
]


MODULE_NAME = "BahuvuNewsAI unified AI translation backend"
MODULE_VERSION = "1.0.0"


def normalize_text(value: Any) -> str:
    """Normalize a value into clean single-line text."""

    if value is None:
        return ""

    return " ".join(str(value).split()).strip()


def normalize_multiline(value: Any) -> str:
    """Normalize text while preserving meaningful paragraph boundaries."""

    if value is None:
        return ""

    lines = [
        " ".join(line.split()).strip()
        for line in str(value).splitlines()
    ]

    return "\n".join(line for line in lines if line).strip()


def deduplicate_strings(values: list[str]) -> list[str]:
    """Return non-empty strings in first-seen order."""

    output: list[str] = []
    seen: set[str] = set()

    for value in values:
        normalized = normalize_text(value)

        if not normalized:
            continue

        key = normalized.casefold()

        if key in seen:
            continue

        seen.add(key)
        output.append(normalized)

    return output


def request_field(
    request: TranslationRequest,
    field_name: str,
    default: Any = "",
) -> Any:
    """Read a field safely from a translation request."""

    return getattr(request, field_name, default)


@dataclass(frozen=True, slots=True)
class AITranslationBackendConfiguration:
    """Unified AI translation backend configuration."""

    include_gemini: bool = True
    include_offline: bool = True
    default_provider: str = "gemini"
    fallback_provider: str = "offline"
    model: str | None = None
    source_language: str = "en"
    target_language: str = "te"
    temperature: float = 0.2
    maximum_output_tokens: int = 4096
    require_editorial_review_after_fallback: bool = True

    def __post_init__(self) -> None:
        if not self.include_gemini and not self.include_offline:
            raise ValueError(
                "At least one AI translation provider must be enabled"
            )

        if not self.source_language.strip():
            raise ValueError("source_language cannot be empty")

        if not self.target_language.strip():
            raise ValueError("target_language cannot be empty")

        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError(
                "temperature must be between 0.0 and 2.0"
            )

        if self.maximum_output_tokens < 1:
            raise ValueError(
                "maximum_output_tokens must be at least 1"
            )


class UnifiedAITranslationBackend:
    """
    Telugu translation backend powered by the unified AI manager.

    This class satisfies the existing translator backend protocol by exposing
    a single ``translate(request)`` method returning ``TranslationResult``.
    """

    provider_name = "unified"

    def __init__(
        self,
        configuration: AITranslationBackendConfiguration | None = None,
        *,
        manager: AIManager | None = None,
    ) -> None:
        self.configuration = (
            configuration or AITranslationBackendConfiguration()
        )

        self._owns_manager = manager is None

        self.manager = manager or create_ai_manager(
            include_gemini=self.configuration.include_gemini,
            include_offline=self.configuration.include_offline,
            auto_start=True,
            routing_mode=RoutingMode.AUTOMATIC,
            default_provider=self.configuration.default_provider,
            fallback_provider=self.configuration.fallback_provider,
            allow_fallback=True,
            perform_startup_health_checks=False,
        )

    @property
    def model_name(self) -> str:
        """Return the configured model or automatic-selection marker."""

        return self.configuration.model or "automatic"

    def _translation_metadata(
        self,
        request: TranslationRequest,
        *,
        field_name: str,
    ) -> dict[str, Any]:
        """Build task metadata used by Gemini and diagnostics."""

        keywords = request_field(request, "keywords", ())

        if isinstance(keywords, str):
            normalized_keywords = [keywords]
        else:
            try:
                normalized_keywords = [
                    str(item) for item in keywords
                ]
            except TypeError:
                normalized_keywords = []

        return {
            "translation_field": field_name,
            "article_id": str(
                request_field(request, "article_id", "")
            ),
            "category": str(
                request_field(request, "category", "")
            ),
            "publisher": str(
                request_field(request, "publisher", "")
            ),
            "source_name": str(
                request_field(request, "source_name", "")
            ),
            "published_at": str(
                request_field(request, "published_at", "")
            ),
            "keywords": normalized_keywords,
            "style": str(
                request_field(
                    request,
                    "style",
                    "professional Telugu television news",
                )
            ),
            "temperature": self.configuration.temperature,
            "maximum_output_tokens": (
                self.configuration.maximum_output_tokens
            ),
            "accuracy_rules": [
                "Preserve all verified facts.",
                "Preserve names, numbers, dates and quotations.",
                "Use natural professional Telugu news language.",
                "Do not add unsupported information.",
                "Do not include explanations outside the translation.",
            ],
        }

    def _translate_field(
        self,
        request: TranslationRequest,
        *,
        field_name: str,
        source_text: str,
    ) -> dict[str, Any]:
        """Translate one request field through the AI manager."""

        normalized_source = normalize_multiline(source_text)

        if not normalized_source:
            return {
                "text": "",
                "provider": "",
                "model": "",
                "used_fallback": False,
                "routing_attempts": 0,
            }

        try:
            result = self.manager.translate(
                normalized_source,
                source_language=self.configuration.source_language,
                target_language=self.configuration.target_language,
                model=self.configuration.model,
                metadata=self._translation_metadata(
                    request,
                    field_name=field_name,
                ),
            )

        except Exception as error:
            raise TranslationProviderError(
                (
                    "Unified AI translation failed for "
                    f"'{field_name}': {error}"
                )
            ) from error

        translated_text = normalize_multiline(result.text)

        if not translated_text:
            raise TranslationProviderError(
                (
                    "Unified AI manager returned empty translation "
                    f"for '{field_name}'"
                )
            )

        return {
            "text": translated_text,
            "provider": normalize_text(result.provider),
            "model": normalize_text(result.model),
            "used_fallback": bool(result.used_fallback),
            "routing_attempts": int(result.routing_attempts),
        }

    def translate(
        self,
        request: TranslationRequest,
    ) -> TranslationResult:
        """Translate headline, summary, and script into Telugu."""

        if request is None:
            raise TranslationProviderError(
                "Translation request cannot be None"
            )

        headline = self._translate_field(
            request,
            field_name="headline",
            source_text=str(
                request_field(request, "headline", "")
            ),
        )

        summary = self._translate_field(
            request,
            field_name="summary",
            source_text=str(
                request_field(request, "summary", "")
            ),
        )

        script = self._translate_field(
            request,
            field_name="script",
            source_text=str(
                request_field(request, "script", "")
            ),
        )

        providers = deduplicate_strings(
            [
                headline["provider"],
                summary["provider"],
                script["provider"],
            ]
        )

        models = deduplicate_strings(
            [
                headline["model"],
                summary["model"],
                script["model"],
            ]
        )

        fallback_used = any(
            bool(item["used_fallback"])
            for item in (headline, summary, script)
        )

        offline_used = any(
            provider.casefold() == "offline"
            for provider in providers
        )

        warnings: list[str] = []

        if (
            fallback_used or offline_used
        ) and self.configuration.require_editorial_review_after_fallback:
            warnings.append(
                "Offline AI fallback was used; editorial review is "
                "required before publication."
            )

        provider_value = (
            providers[0]
            if len(providers) == 1
            else "+".join(providers)
        ) or self.provider_name

        model_value = (
            models[0]
            if len(models) == 1
            else "+".join(models)
        ) or self.model_name

        raw_response = json.dumps(
            {
                "backend": self.provider_name,
                "backend_version": MODULE_VERSION,
                "telugu_headline": headline["text"],
                "telugu_summary": summary["text"],
                "telugu_script": script["text"],
                "providers": providers,
                "models": models,
                "fallback_used": fallback_used,
                "routing_attempts": {
                    "headline": headline["routing_attempts"],
                    "summary": summary["routing_attempts"],
                    "script": script["routing_attempts"],
                },
                "warnings": warnings,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

        result = TranslationResult(
            telugu_headline=headline["text"],
            telugu_summary=summary["text"],
            telugu_script=script["text"],
            provider=provider_value,
            model=model_value,
            raw_response=raw_response,
            warnings=warnings,
        )

        normalized_method = getattr(result, "normalized", None)

        if callable(normalized_method):
            return normalized_method()

        return result

    def health_report(self) -> Mapping[str, Any]:
        """Return unified AI manager health information."""

        return self.manager.health_report()

    def metrics(self) -> Mapping[str, Any]:
        """Return manager, router, and provider metrics."""

        return self.manager.metrics()

    def close(self) -> None:
        """Close the owned AI manager."""

        if self._owns_manager:
            self.manager.stop()

    def __enter__(self) -> "UnifiedAITranslationBackend":
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: Any,
    ) -> None:
        del exception_type, exception, traceback
        self.close()


def create_ai_translation_backend(
    *,
    include_gemini: bool = True,
    include_offline: bool = True,
    model: str | None = None,
    manager: AIManager | None = None,
) -> UnifiedAITranslationBackend:
    """Create the standard unified AI translation backend."""

    configuration = AITranslationBackendConfiguration(
        include_gemini=include_gemini,
        include_offline=include_offline,
        default_provider=(
            "gemini" if include_gemini else "offline"
        ),
        fallback_provider="offline",
        model=model,
    )

    return UnifiedAITranslationBackend(
        configuration,
        manager=manager,
    )


def _build_self_test_request() -> TranslationRequest:
    """Build a request compatible with the existing translator model."""

    return TranslationRequest(
        article_id="ai_translation_backend_test",
        headline="Heavy rain continues in Andhra Pradesh.",
        summary=(
            "Officials issued a warning over continuing heavy rainfall."
        ),
        script=(
            "Heavy rain continues in several districts. "
            "Officials advised people to remain cautious."
        ),
        category="weather",
        publisher="BAHUVU NEWS",
        source_name="offline-self-test",
        published_at="2026-07-15T00:00:00+00:00",
        keywords=("rain", "weather", "warning"),
        style="professional Telugu television news",
    )

    try:
        return TranslationRequest(**request_values)

    except TypeError:
        minimal_values = {
            "article_id": request_values["article_id"],
            "headline": request_values["headline"],
            "summary": request_values["summary"],
            "script": request_values["script"],
        }

        return TranslationRequest(**minimal_values)


def _run_self_test() -> None:
    """Run deterministic offline adapter validation."""

    manager = create_ai_manager(
        include_gemini=False,
        include_offline=True,
        auto_start=True,
        routing_mode=RoutingMode.OFFLINE_ONLY,
        default_provider="offline",
        fallback_provider="offline",
        allow_fallback=True,
    )

    backend = UnifiedAITranslationBackend(
        AITranslationBackendConfiguration(
            include_gemini=False,
            include_offline=True,
            default_provider="offline",
            fallback_provider="offline",
            model=None,
        ),
        manager=manager,
    )

    request = _build_self_test_request()
    result = backend.translate(request)
    health = backend.health_report()
    metrics = backend.metrics()

    assert result.telugu_headline
    assert result.telugu_summary
    assert result.telugu_script
    assert result.provider == "offline"
    assert result.model == "bahuvu-offline-rules-v1"
    assert health["overall_status"] == "healthy"
    assert health["healthy_provider_count"] == 1
    assert metrics["manager"]["generation_count"] == 3
    assert metrics["manager"]["successful_count"] == 3
    assert metrics["manager"]["failed_count"] == 0

    raw_response = json.loads(result.raw_response)

    assert raw_response["backend"] == "unified"
    assert raw_response["providers"] == ["offline"]
    assert raw_response["fallback_used"] is False

    print(MODULE_NAME)
    print(f"Module version  : {MODULE_VERSION}")
    print(f"Backend         : {backend.provider_name}")
    print(f"Selected provider: {result.provider}")
    print(f"Model           : {result.model}")
    print(f"Telugu headline : {result.telugu_headline}")
    print(f"Telugu summary  : {result.telugu_summary}")
    print(f"Telugu script   : {result.telugu_script}")
    print(
        "Health status   : "
        f"{health['overall_status']}"
    )
    print(
        "Success rate    : "
        f"{metrics['manager']['success_rate']:.2f}%"
    )
    print("Unified AI translation backend self-test passed.")

    manager.stop()


if __name__ == "__main__":
    _run_self_test()