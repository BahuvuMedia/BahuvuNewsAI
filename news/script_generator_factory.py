"""
BahuvuNewsAI broadcast script generator factory.

This module preserves the existing deterministic script generator while
providing an optional unified-AI enhancement layer.

Supported modes:

* deterministic
* unified

The deterministic generator remains the authoritative source for bulletin
structure, story selection, sections, metadata, and production statistics.

In unified mode, the deterministic bulletin is generated first. Its complete
anchor script is then sent through ``AIManager.generate_script()`` for
broadcast-language enhancement. Structured bulletin data is preserved.

Environment variables
---------------------

BAHUVU_SCRIPT_BACKEND
    "deterministic" or "unified". Default: "unified".

BAHUVU_SCRIPT_INCLUDE_GEMINI
    Enable Gemini in unified mode. Default: "true".

BAHUVU_SCRIPT_INCLUDE_OFFLINE
    Enable deterministic offline fallback. Default: "true".

BAHUVU_SCRIPT_MAX_OUTPUT_TOKENS
    Maximum AI output tokens. Default: "8192".

BAHUVU_SCRIPT_REPLACE_FULL_SCRIPT
    Replace Bulletin.full_script with the AI-enhanced script.
    Default: "true".
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Sequence

from ai.manager import (
    AIManager,
    create_ai_manager,
)
from ai.router import RoutingMode
from news.models import NewsArticle
from news.script_generator import (
    Bulletin,
    ScriptGenerator,
    ScriptGeneratorConfig,
    count_words,
    estimate_seconds,
)


__all__ = [
    "ScriptGeneratorBackendMode",
    "ScriptGeneratorFactoryConfiguration",
    "UnifiedAIScriptGenerator",
    "create_script_generator",
]


MODULE_NAME = "BahuvuNewsAI script generator factory"
MODULE_VERSION = "1.0.0"


class ScriptGeneratorFactoryError(RuntimeError):
    """Raised when script-generator factory configuration is invalid."""


class ScriptGeneratorBackendMode(StrEnum):
    """Available script-generation modes."""

    DETERMINISTIC = "deterministic"
    UNIFIED = "unified"


@dataclass(frozen=True, slots=True)
class ScriptGeneratorFactoryConfiguration:
    """Configuration used to create a script generator."""

    backend: ScriptGeneratorBackendMode = (
        ScriptGeneratorBackendMode.UNIFIED
    )
    include_gemini: bool = True
    include_offline: bool = True
    maximum_output_tokens: int = 8192
    replace_full_script: bool = True
    provider: str | None = None

    def __post_init__(self) -> None:
        if self.maximum_output_tokens < 1:
            raise ValueError(
                "maximum_output_tokens must be at least 1"
            )

        if (
            self.backend is ScriptGeneratorBackendMode.UNIFIED
            and not self.include_gemini
            and not self.include_offline
        ):
            raise ValueError(
                "Unified script generation requires at least one provider"
            )

        if self.provider is not None and not self.provider.strip():
            raise ValueError(
                "provider cannot be an empty string"
            )

    @classmethod
    def from_environment(
        cls,
    ) -> "ScriptGeneratorFactoryConfiguration":
        """Build factory settings from environment variables."""

        backend_text = os.getenv(
            "BAHUVU_SCRIPT_BACKEND",
            ScriptGeneratorBackendMode.UNIFIED.value,
        ).strip().lower()

        try:
            backend = ScriptGeneratorBackendMode(backend_text)
        except ValueError as error:
            supported = ", ".join(
                item.value for item in ScriptGeneratorBackendMode
            )
            raise ScriptGeneratorFactoryError(
                (
                    f"Unsupported script backend '{backend_text}'. "
                    f"Supported backends: {supported}."
                )
            ) from error

        include_gemini = _environment_boolean(
            "BAHUVU_SCRIPT_INCLUDE_GEMINI",
            default=True,
        )
        include_offline = _environment_boolean(
            "BAHUVU_SCRIPT_INCLUDE_OFFLINE",
            default=True,
        )
        replace_full_script = _environment_boolean(
            "BAHUVU_SCRIPT_REPLACE_FULL_SCRIPT",
            default=True,
        )

        maximum_tokens_text = os.getenv(
            "BAHUVU_SCRIPT_MAX_OUTPUT_TOKENS",
            "8192",
        ).strip()

        try:
            maximum_output_tokens = int(maximum_tokens_text)
        except ValueError as error:
            raise ScriptGeneratorFactoryError(
                (
                    "BAHUVU_SCRIPT_MAX_OUTPUT_TOKENS "
                    "must be an integer"
                )
            ) from error

        provider = (
            os.getenv(
                "BAHUVU_SCRIPT_PROVIDER",
                "",
            ).strip()
            or None
        )

        return cls(
            backend=backend,
            include_gemini=include_gemini,
            include_offline=include_offline,
            maximum_output_tokens=maximum_output_tokens,
            replace_full_script=replace_full_script,
            provider=provider,
        )


def _environment_boolean(
    name: str,
    *,
    default: bool,
) -> bool:
    """Read a boolean environment variable."""

    default_text = "true" if default else "false"
    value = os.getenv(name, default_text).strip().lower()

    return value not in {
        "0",
        "false",
        "no",
        "off",
    }


def _build_ai_prompt(bulletin: Bulletin) -> str:
    """Build a fact-preserving broadcast script prompt."""

    return f"""
You are the senior English broadcast editor for BAHUVU NEWS.

Improve the following deterministic news bulletin for professional television
delivery.

Mandatory rules:

1. Preserve every factual claim, name, number, date, place, quotation,
   attribution, and source reference.
2. Do not add facts, assumptions, predictions, opinions, or unsupported
   context.
3. Preserve the bulletin's story order.
4. Preserve the opening, headline roundup, story sections, and closing.
5. Improve clarity, flow, transitions, sentence rhythm, and anchor readability.
6. Use neutral, accurate, contemporary broadcast English.
7. Avoid sensationalism, repetition, promotional language, and exaggeration.
8. Return only the completed broadcast script.
9. Do not return JSON, Markdown fences, analysis, notes, or explanations.

BULLETIN INFORMATION

Title: {bulletin.title}
Edition: {bulletin.edition}
Date: {bulletin.bulletin_date}
Language: {bulletin.language}
Stories: {bulletin.statistics.selected_articles}

DETERMINISTIC SCRIPT

{bulletin.full_script}
""".strip()


class UnifiedAIScriptGenerator:
    """
    Enhance deterministic bulletins through the unified AI manager.

    The existing ScriptGenerator remains responsible for:

    * article filtering
    * ranking
    * bulletin structure
    * sections
    * story metadata
    * canonical compatibility
    * baseline production statistics

    The AI manager only enhances the rendered anchor script.
    """

    def __init__(
        self,
        *,
        script_config: ScriptGeneratorConfig | None = None,
        factory_config: (
            ScriptGeneratorFactoryConfiguration | None
        ) = None,
        manager: AIManager | None = None,
    ) -> None:
        self.script_config = (
            script_config or ScriptGeneratorConfig()
        )
        self.factory_config = (
            factory_config
            or ScriptGeneratorFactoryConfiguration.from_environment()
        )

        self.deterministic_generator = ScriptGenerator(
            self.script_config
        )

        self._owns_manager = manager is None
        self.manager = manager or self._create_manager()

    def _create_manager(self) -> AIManager:
        """Create a manager matching configured provider availability."""

        include_gemini = self.factory_config.include_gemini
        include_offline = self.factory_config.include_offline

        if include_gemini:
            routing_mode = RoutingMode.AUTOMATIC
            default_provider = "gemini"
        else:
            routing_mode = RoutingMode.OFFLINE_ONLY
            default_provider = "offline"

        fallback_provider = (
            "offline"
            if include_offline
            else None
        )

        return create_ai_manager(
            include_gemini=include_gemini,
            include_offline=include_offline,
            routing_mode=routing_mode,
            default_provider=default_provider,
            fallback_provider=fallback_provider,
            allow_fallback=include_offline,
        )

    def generate(
        self,
        articles: Sequence[
            NewsArticle | Mapping[str, Any]
        ],
        bulletin_date: Any = None,
    ) -> Bulletin:
        """
        Generate a deterministic bulletin and optionally enhance its script.
        """

        bulletin = self.deterministic_generator.generate(
            articles=articles,
            bulletin_date=bulletin_date,
        )

        original_word_count = bulletin.statistics.total_words
        original_duration = bulletin.statistics.estimated_seconds

        result = self.manager.generate_script(
            _build_ai_prompt(bulletin),
            provider=self.factory_config.provider,
            max_output_tokens=(
                self.factory_config.maximum_output_tokens
            ),
            metadata={
                "bulletin_id": bulletin.bulletin_id,
                "bulletin_title": bulletin.title,
                "edition": bulletin.edition,
                "bulletin_date": bulletin.bulletin_date,
                "source": MODULE_NAME,
                "source_version": MODULE_VERSION,
                "deterministic_word_count": original_word_count,
            },
        )

        if not result.success:
            raise ScriptGeneratorFactoryError(
                (
                    "Unified AI script generation failed with "
                    f"status '{result.status}'."
                )
            )

        enhanced_script = str(result.text or "").strip()

        if not enhanced_script:
            raise ScriptGeneratorFactoryError(
                "Unified AI manager returned an empty script."
            )

        if not enhanced_script.endswith("\n"):
            enhanced_script += "\n"

        if self.factory_config.replace_full_script:
            bulletin.full_script = enhanced_script

            total_words = count_words(enhanced_script)
            total_seconds = estimate_seconds(
                total_words,
                self.script_config.words_per_minute,
            )

            bulletin.statistics.total_words = total_words
            bulletin.statistics.estimated_seconds = total_seconds
            bulletin.statistics.estimated_minutes = round(
                total_seconds / 60.0,
                2,
            )

        bulletin.metadata = dict(bulletin.metadata or {})
        bulletin.metadata["script_generation"] = {
            "mode": ScriptGeneratorBackendMode.UNIFIED.value,
            "provider": result.provider,
            "model": result.model,
            "used_fallback": result.used_fallback,
            "routing_attempts": result.routing_attempts,
            "request_id": result.request_id,
            "created_at": result.created_at,
            "replace_full_script": (
                self.factory_config.replace_full_script
            ),
            "deterministic_word_count": original_word_count,
            "deterministic_estimated_seconds": original_duration,
            "final_word_count": bulletin.statistics.total_words,
            "final_estimated_seconds": (
                bulletin.statistics.estimated_seconds
            ),
            "structured_sections_preserved": True,
            "requires_editorial_review": True,
        }

        return bulletin

    def close(self) -> None:
        """Close the owned AI manager."""

        if self._owns_manager:
            self.manager.stop()

    def __enter__(self) -> "UnifiedAIScriptGenerator":
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: Any,
    ) -> None:
        del exception_type, exception, traceback
        self.close()


def create_script_generator(
    configuration: (
        ScriptGeneratorFactoryConfiguration | None
    ) = None,
    *,
    script_config: ScriptGeneratorConfig | None = None,
    manager: AIManager | None = None,
) -> ScriptGenerator | UnifiedAIScriptGenerator:
    """Create the configured script generator."""

    config = (
        configuration
        or ScriptGeneratorFactoryConfiguration.from_environment()
    )

    if config.backend is ScriptGeneratorBackendMode.DETERMINISTIC:
        return ScriptGenerator(
            script_config or ScriptGeneratorConfig()
        )

    if config.backend is ScriptGeneratorBackendMode.UNIFIED:
        return UnifiedAIScriptGenerator(
            script_config=script_config,
            factory_config=config,
            manager=manager,
        )

    raise ScriptGeneratorFactoryError(
        f"Unsupported script backend: {config.backend}"
    )


def _run_self_test() -> None:
    """Run deterministic and offline-unified factory tests."""

    from news.script_generator import _build_sample_articles

    articles = _build_sample_articles()

    script_config = ScriptGeneratorConfig(
        max_stories=10,
        max_headlines=5,
        minimum_score=50.0,
        words_per_minute=145,
    )

    deterministic_config = ScriptGeneratorFactoryConfiguration(
        backend=ScriptGeneratorBackendMode.DETERMINISTIC,
        include_gemini=False,
        include_offline=True,
    )

    deterministic_generator = create_script_generator(
        deterministic_config,
        script_config=script_config,
    )

    deterministic_bulletin = deterministic_generator.generate(
        articles,
        bulletin_date="2026-07-11",
    )

    unified_config = ScriptGeneratorFactoryConfiguration(
        backend=ScriptGeneratorBackendMode.UNIFIED,
        include_gemini=False,
        include_offline=True,
        maximum_output_tokens=8192,
        replace_full_script=True,
        provider="offline",
    )

    unified_generator = create_script_generator(
        unified_config,
        script_config=script_config,
    )

    try:
        unified_bulletin = unified_generator.generate(
            articles,
            bulletin_date="2026-07-11",
        )
    finally:
        close_method = getattr(
            unified_generator,
            "close",
            None,
        )
        if callable(close_method):
            close_method()

    assert isinstance(
        deterministic_generator,
        ScriptGenerator,
    )
    assert isinstance(
        unified_generator,
        UnifiedAIScriptGenerator,
    )

    assert deterministic_bulletin.statistics.selected_articles == 5
    assert unified_bulletin.statistics.selected_articles == 5
    assert unified_bulletin.full_script.strip()

    generation_metadata = unified_bulletin.metadata[
        "script_generation"
    ]

    assert generation_metadata["mode"] == "unified"
    assert generation_metadata["provider"] == "offline"
    assert generation_metadata["structured_sections_preserved"] is True
    assert unified_bulletin.sections
    assert unified_bulletin.sections[0].stories

    print(MODULE_NAME)
    print(f"Module version          : {MODULE_VERSION}")
    print(
        "Deterministic generator: "
        f"{type(deterministic_generator).__name__}"
    )
    print(
        "Unified generator      : "
        f"{type(unified_generator).__name__}"
    )
    print(
        "Unified provider       : "
        f"{generation_metadata['provider']}"
    )
    print(
        "Fallback used          : "
        f"{generation_metadata['used_fallback']}"
    )
    print(
        "Selected stories       : "
        f"{unified_bulletin.statistics.selected_articles}"
    )
    print(
        "Final script words     : "
        f"{unified_bulletin.statistics.total_words}"
    )
    print("Script generator factory self-test passed.")


if __name__ == "__main__":
    _run_self_test()