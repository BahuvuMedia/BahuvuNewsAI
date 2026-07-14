"""
BahuvuNewsAI Telugu translator backend factory.

This module centralizes translation backend selection without changing the
existing ``news.telugu_translator`` implementation.

Supported backend modes:

* deterministic
* google
* unified

The unified backend uses the new AI manager and automatically routes work to
Gemini with offline fallback.

Keeping this logic in a separate factory allows the existing translator module
to remain stable while production integration proceeds incrementally.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from news.ai_translation_backend import (
    UnifiedAITranslationBackend,
    create_ai_translation_backend,
)
from news.telugu_translator import (
    DeterministicTeluguBackend,
    GoogleGenerativeAIBackend,
    TeluguTranslationBackend,
    TeluguTranslator,
    TranslationConfigurationError,
    TranslationSettings,
)


__all__ = [
    "TranslatorBackendMode",
    "TranslatorFactoryConfiguration",
    "create_translation_backend",
    "create_telugu_translator",
]


MODULE_NAME = "BahuvuNewsAI Telugu translator factory"
MODULE_VERSION = "1.0.0"


class TranslatorBackendMode(StrEnum):
    """Available Telugu translation backend modes."""

    DETERMINISTIC = "deterministic"
    GOOGLE = "google"
    UNIFIED = "unified"


@dataclass(frozen=True, slots=True)
class TranslatorFactoryConfiguration:
    """Configuration used to create a Telugu translation backend."""

    backend: TranslatorBackendMode = TranslatorBackendMode.UNIFIED
    model: str = "gemini-flash-latest"
    temperature: float = 0.2
    maximum_output_tokens: int = 4096
    include_gemini: bool = True
    include_offline: bool = True
    google_api_key: str | None = None

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("model cannot be empty")

        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError(
                "temperature must be between 0.0 and 2.0"
            )

        if self.maximum_output_tokens < 1:
            raise ValueError(
                "maximum_output_tokens must be at least 1"
            )

        if (
            self.backend is TranslatorBackendMode.UNIFIED
            and not self.include_gemini
            and not self.include_offline
        ):
            raise ValueError(
                "Unified backend requires at least one provider"
            )

    @classmethod
    def from_environment(
        cls,
    ) -> "TranslatorFactoryConfiguration":
        """Build factory configuration from environment variables."""

        backend_text = os.getenv(
            "BAHUVU_TRANSLATION_BACKEND",
            TranslatorBackendMode.UNIFIED.value,
        ).strip().lower()

        try:
            backend = TranslatorBackendMode(backend_text)
        except ValueError as error:
            supported = ", ".join(
                item.value for item in TranslatorBackendMode
            )
            raise TranslationConfigurationError(
                (
                    f"Unsupported translation backend '{backend_text}'. "
                    f"Supported backends: {supported}."
                )
            ) from error

        model = os.getenv(
            "BAHUVU_TRANSLATION_MODEL",
            "gemini-flash-latest",
        ).strip()

        temperature_text = os.getenv(
            "BAHUVU_TRANSLATION_TEMPERATURE",
            "0.2",
        ).strip()

        maximum_tokens_text = os.getenv(
            "BAHUVU_TRANSLATION_MAX_OUTPUT_TOKENS",
            "4096",
        ).strip()

        include_gemini = os.getenv(
            "BAHUVU_TRANSLATION_INCLUDE_GEMINI",
            "true",
        ).strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }

        include_offline = os.getenv(
            "BAHUVU_TRANSLATION_INCLUDE_OFFLINE",
            "true",
        ).strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }

        try:
            temperature = float(temperature_text)
        except ValueError as error:
            raise TranslationConfigurationError(
                (
                    "BAHUVU_TRANSLATION_TEMPERATURE must be "
                    "a valid number"
                )
            ) from error

        try:
            maximum_output_tokens = int(maximum_tokens_text)
        except ValueError as error:
            raise TranslationConfigurationError(
                (
                    "BAHUVU_TRANSLATION_MAX_OUTPUT_TOKENS "
                    "must be an integer"
                )
            ) from error

        api_key = (
            os.getenv("BAHUVU_GEMINI_API_KEY", "").strip()
            or os.getenv("GEMINI_API_KEY", "").strip()
            or os.getenv("GOOGLE_API_KEY", "").strip()
            or None
        )

        return cls(
            backend=backend,
            model=model,
            temperature=temperature,
            maximum_output_tokens=maximum_output_tokens,
            include_gemini=include_gemini,
            include_offline=include_offline,
            google_api_key=api_key,
        )


def create_translation_backend(
    configuration: TranslatorFactoryConfiguration | None = None,
) -> TeluguTranslationBackend:
    """
    Create a translation backend from explicit or environment configuration.
    """

    config = (
        configuration
        or TranslatorFactoryConfiguration.from_environment()
    )

    if config.backend is TranslatorBackendMode.DETERMINISTIC:
        return DeterministicTeluguBackend()

    if config.backend is TranslatorBackendMode.GOOGLE:
        if not config.google_api_key:
            raise TranslationConfigurationError(
                (
                    "Google translation backend requires an API key. "
                    "Set BAHUVU_GEMINI_API_KEY, GEMINI_API_KEY, "
                    "or GOOGLE_API_KEY."
                )
            )

        return GoogleGenerativeAIBackend(
            api_key=config.google_api_key,
            model_name=config.model,
            temperature=config.temperature,
            max_output_tokens=config.maximum_output_tokens,
        )

    if config.backend is TranslatorBackendMode.UNIFIED:
        return create_ai_translation_backend(
            include_gemini=config.include_gemini,
            include_offline=config.include_offline,
            model=config.model,
        )

    raise TranslationConfigurationError(
        f"Unsupported translation backend: {config.backend}"
    )


def create_telugu_translator(
    configuration: TranslatorFactoryConfiguration | None = None,
    *,
    settings: TranslationSettings | None = None,
) -> TeluguTranslator:
    """
    Create a ``TeluguTranslator`` using the selected backend.

    Existing translator settings remain supported. When settings are omitted,
    the translator's standard settings model is used.
    """

    config = (
        configuration
        or TranslatorFactoryConfiguration.from_environment()
    )
    backend = create_translation_backend(config)

    resolved_settings = settings

    if resolved_settings is None:
        try:
            resolved_settings = TranslationSettings(
                provider=config.backend.value,
                model=config.model,
            )
        except (TypeError, ValueError):
            resolved_settings = TranslationSettings.from_environment()

    return TeluguTranslator(
        backend,
        settings=resolved_settings,
    )


def _backend_name(backend: Any) -> str:
    """Return a stable backend identifier for diagnostics."""

    value = getattr(backend, "provider_name", None)

    if value:
        return str(value)

    return type(backend).__name__


def _run_self_test() -> None:
    """Execute factory validation without network access."""

    deterministic_config = TranslatorFactoryConfiguration(
        backend=TranslatorBackendMode.DETERMINISTIC,
        model="offline-self-test-v1",
        include_gemini=False,
        include_offline=True,
    )

    deterministic_backend = create_translation_backend(
        deterministic_config
    )

    unified_config = TranslatorFactoryConfiguration(
        backend=TranslatorBackendMode.UNIFIED,
        model="bahuvu-offline-rules-v1",
        include_gemini=False,
        include_offline=True,
    )

    unified_backend = create_translation_backend(
        unified_config
    )

    translator = create_telugu_translator(
        deterministic_config
    )

    assert isinstance(
        deterministic_backend,
        DeterministicTeluguBackend,
    )
    assert isinstance(
        unified_backend,
        UnifiedAITranslationBackend,
    )
    assert isinstance(translator, TeluguTranslator)

    assert _backend_name(deterministic_backend) in {
        "deterministic",
        "DeterministicTeluguBackend",
    }
    assert _backend_name(unified_backend) == "unified"

    print(MODULE_NAME)
    print(f"Module version        : {MODULE_VERSION}")
    print(
        "Deterministic backend : "
        f"{_backend_name(deterministic_backend)}"
    )
    print(
        "Unified backend       : "
        f"{_backend_name(unified_backend)}"
    )
    print(
        "Translator type       : "
        f"{type(translator).__name__}"
    )
    print("Telugu translator factory self-test passed.")

    close_method = getattr(unified_backend, "close", None)

    if callable(close_method):
        close_method()


if __name__ == "__main__":
    _run_self_test()