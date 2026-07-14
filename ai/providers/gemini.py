"""
BahuvuNewsAI Gemini AI provider.

This module implements the production Gemini adapter for the unified
BahuvuNewsAI AI subsystem.

The provider:

* Inherits from ``BaseAIProvider``.
* Accepts canonical AI request objects, dictionaries, and dataclasses.
* Supports text generation, Telugu translation, summarization, classification,
  script generation, editorial polishing, and structured JSON output.
* Supports both Google Gemini Python SDK generations:
    - ``google-genai`` using ``from google import genai``
    - ``google-generativeai`` using ``import google.generativeai``
* Reads credentials safely from environment variables.
* Avoids network calls during the executable module self-test.
* Normalizes Gemini output into the canonical response type when available.
* Provides token usage, finish-reason, safety, latency, and model metadata.
* Uses the retry, timeout, metrics, rate-limiting, and health framework from
  ``ai.providers.base``.

Environment variables:

    GEMINI_API_KEY
    GOOGLE_API_KEY
    BAHUVU_GEMINI_API_KEY
    GEMINI_MODEL
    BAHUVU_GEMINI_MODEL

The provider never prints or exposes the API key.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from ai.providers.base import (
    BaseAIProvider,
    ProviderAuthenticationError,
    ProviderCapability,
    ProviderConfigurationError,
    ProviderExecutionContext,
    ProviderMetadata,
    ProviderOperationalStatus,
    ProviderResponseError,
    ProviderUnavailableError,
    RateLimitPolicy,
    RetryPolicy,
    object_to_mapping,
    read_object_field,
    safe_float,
    safe_int,
    utc_now_iso,
)


__all__ = [
    "GeminiSDK",
    "GeminiConfiguration",
    "GeminiGenerationSettings",
    "GeminiUsage",
    "GeminiResponse",
    "GeminiProvider",
    "create_gemini_provider",
]


MODULE_NAME = "BahuvuNewsAI Gemini AI provider"
MODULE_VERSION = "1.0.0"

DEFAULT_GEMINI_MODEL = "gemini-flash-latest"
DEFAULT_TIMEOUT_SECONDS = 90.0

API_KEY_ENVIRONMENT_VARIABLES = (
    "BAHUVU_GEMINI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
)

MODEL_ENVIRONMENT_VARIABLES = (
    "BAHUVU_GEMINI_MODEL",
    "GEMINI_MODEL",
)


class GeminiSDK(str, Enum):
    """Supported Google Gemini Python SDK implementations."""

    AUTO = "auto"
    GOOGLE_GENAI = "google-genai"
    GOOGLE_GENERATIVE_AI = "google-generativeai"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class GeminiGenerationSettings:
    """Generation parameters sent to Gemini."""

    temperature: float = 0.2
    top_p: float = 0.95
    top_k: int = 40
    maximum_output_tokens: int = 4096
    candidate_count: int = 1
    stop_sequences: tuple[str, ...] = ()
    response_mime_type: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError("temperature must be between 0.0 and 2.0")

        if not 0.0 <= self.top_p <= 1.0:
            raise ValueError("top_p must be between 0.0 and 1.0")

        if self.top_k < 1:
            raise ValueError("top_k must be at least 1")

        if self.maximum_output_tokens < 1:
            raise ValueError(
                "maximum_output_tokens must be at least 1"
            )

        if self.candidate_count < 1:
            raise ValueError("candidate_count must be at least 1")

    def with_overrides(
        self,
        *,
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        maximum_output_tokens: int | None = None,
        candidate_count: int | None = None,
        stop_sequences: Sequence[str] | None = None,
        response_mime_type: str | None = None,
    ) -> GeminiGenerationSettings:
        """Return a copy with selected request-level overrides."""

        return GeminiGenerationSettings(
            temperature=(
                self.temperature
                if temperature is None
                else float(temperature)
            ),
            top_p=self.top_p if top_p is None else float(top_p),
            top_k=self.top_k if top_k is None else int(top_k),
            maximum_output_tokens=(
                self.maximum_output_tokens
                if maximum_output_tokens is None
                else int(maximum_output_tokens)
            ),
            candidate_count=(
                self.candidate_count
                if candidate_count is None
                else int(candidate_count)
            ),
            stop_sequences=(
                self.stop_sequences
                if stop_sequences is None
                else tuple(str(item) for item in stop_sequences)
            ),
            response_mime_type=(
                self.response_mime_type
                if response_mime_type is None
                else response_mime_type
            ),
        )


@dataclass(frozen=True, slots=True)
class GeminiConfiguration:
    """Gemini provider runtime configuration."""

    api_key: str | None = None
    model: str = DEFAULT_GEMINI_MODEL
    sdk: GeminiSDK = GeminiSDK.AUTO
    enabled: bool = True
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    generation: GeminiGenerationSettings = field(
        default_factory=GeminiGenerationSettings
    )
    system_instruction: str | None = None
    safety_settings: tuple[Mapping[str, Any], ...] = ()
    validate_credentials_on_startup: bool = False

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("Gemini model cannot be empty")

        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

    @classmethod
    def from_environment(
        cls,
        *,
        model: str | None = None,
        sdk: GeminiSDK | str = GeminiSDK.AUTO,
        enabled: bool = True,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        generation: GeminiGenerationSettings | None = None,
        system_instruction: str | None = None,
        safety_settings: Sequence[Mapping[str, Any]] | None = None,
        validate_credentials_on_startup: bool = False,
    ) -> GeminiConfiguration:
        """Create configuration from BahuvuNewsAI environment variables."""

        resolved_api_key: str | None = None

        for variable_name in API_KEY_ENVIRONMENT_VARIABLES:
            value = os.getenv(variable_name, "").strip()
            if value:
                resolved_api_key = value
                break

        resolved_model = model

        if not resolved_model:
            for variable_name in MODEL_ENVIRONMENT_VARIABLES:
                value = os.getenv(variable_name, "").strip()
                if value:
                    resolved_model = value
                    break

        if isinstance(sdk, str):
            sdk = GeminiSDK(sdk)

        return cls(
            api_key=resolved_api_key,
            model=resolved_model or DEFAULT_GEMINI_MODEL,
            sdk=sdk,
            enabled=enabled,
            timeout_seconds=timeout_seconds,
            generation=generation or GeminiGenerationSettings(),
            system_instruction=system_instruction,
            safety_settings=tuple(safety_settings or ()),
            validate_credentials_on_startup=(
                validate_credentials_on_startup
            ),
        )


@dataclass(frozen=True, slots=True)
class GeminiUsage:
    """Normalized Gemini token usage."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0

    def __post_init__(self) -> None:
        if min(
            self.input_tokens,
            self.output_tokens,
            self.total_tokens,
            self.cached_tokens,
        ) < 0:
            raise ValueError("Token counts cannot be negative")


@dataclass(frozen=True, slots=True)
class GeminiResponse:
    """Normalized response returned by ``GeminiProvider``."""

    request_id: str
    status: str
    provider: str
    model: str
    task: str
    text: str
    created_at: str
    usage: GeminiUsage = field(default_factory=GeminiUsage)
    finish_reason: str | None = None
    structured_data: Any = None
    safety_ratings: tuple[Mapping[str, Any], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def success(self) -> bool:
        """Return whether generation completed successfully."""

        return self.status.lower() == "success"

    @property
    def content(self) -> str:
        """Compatibility alias for canonical response models."""

        return self.text

    @property
    def output_text(self) -> str:
        """Compatibility alias used by some AI clients."""

        return self.text

    @property
    def token_usage(self) -> GeminiUsage:
        """Compatibility alias for the common provider foundation."""

        return self.usage


def _enum_value(value: Any) -> Any:
    """Return the primitive value of an enum when applicable."""

    if isinstance(value, Enum):
        return value.value

    return value


def _first_non_empty(
    source: Any,
    names: Sequence[str],
    default: Any = None,
) -> Any:
    """Return the first available non-empty field."""

    for name in names:
        value = read_object_field(source, name, default=None)

        if value is not None and value != "":
            return value

    return default


def _mapping_without_none(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a mapping excluding values that are ``None``."""

    return {
        str(key): item
        for key, item in value.items()
        if item is not None
    }


def _json_safe(value: Any) -> Any:
    """Convert arbitrary SDK objects into JSON-compatible values."""

    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]

    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _json_safe(model_dump())
        except Exception:
            pass

    instance_dict = getattr(value, "__dict__", None)
    if isinstance(instance_dict, dict):
        return {
            str(key): _json_safe(item)
            for key, item in instance_dict.items()
            if not str(key).startswith("_")
        }

    return str(value)


def _extract_json_from_text(text: str) -> Any:
    """
    Parse JSON from plain text or a fenced Markdown JSON block.

    Returns ``None`` when the output is not valid JSON.
    """

    stripped = text.strip()

    if not stripped:
        return None

    fenced_match = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```",
        stripped,
        flags=re.DOTALL | re.IGNORECASE,
    )

    if fenced_match:
        stripped = fenced_match.group(1).strip()

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    object_start = stripped.find("{")
    object_end = stripped.rfind("}")

    if object_start >= 0 and object_end > object_start:
        candidate = stripped[object_start : object_end + 1]

        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    array_start = stripped.find("[")
    array_end = stripped.rfind("]")

    if array_start >= 0 and array_end > array_start:
        candidate = stripped[array_start : array_end + 1]

        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    return None


class GeminiProvider(BaseAIProvider[Any, GeminiResponse]):
    """
    Production Google Gemini provider for BahuvuNewsAI.

    Client initialization is lazy. Importing or constructing this class does
    not establish a network connection.
    """

    def __init__(
        self,
        configuration: GeminiConfiguration | None = None,
        *,
        logger: logging.Logger | None = None,
        client: Any = None,
    ) -> None:
        self.configuration = (
            configuration or GeminiConfiguration.from_environment()
        )

        metadata = ProviderMetadata(
            name="gemini",
            display_name="Google Gemini",
            version=MODULE_VERSION,
            provider_type="remote",
            default_model=self.configuration.model,
            capabilities=frozenset(
                {
                    ProviderCapability.TEXT_GENERATION,
                    ProviderCapability.TRANSLATION,
                    ProviderCapability.SUMMARIZATION,
                    ProviderCapability.CLASSIFICATION,
                    ProviderCapability.EDITORIAL_POLISHING,
                    ProviderCapability.SCRIPT_GENERATION,
                    ProviderCapability.STRUCTURED_OUTPUT,
                    ProviderCapability.VISION,
                }
            ),
            description=(
                "Google Gemini adapter for BahuvuNewsAI unified AI tasks"
            ),
        )

        super().__init__(
            metadata,
            enabled=self.configuration.enabled,
            timeout_seconds=self.configuration.timeout_seconds,
            retry_policy=RetryPolicy(
                max_attempts=3,
                initial_delay_seconds=1.0,
                maximum_delay_seconds=12.0,
                exponential_base=2.0,
                jitter_seconds=0.25,
                retry_unknown_errors=False,
            ),
            rate_limit_policy=RateLimitPolicy(
                requests_per_window=45,
                window_seconds=60.0,
                enabled=True,
            ),
            logger=logger,
        )

        self._client = client
        self._sdk: GeminiSDK | None = None
        self._client_lock = threading.RLock()

        if client is not None:
            self._sdk = (
                self.configuration.sdk
                if self.configuration.sdk is not GeminiSDK.AUTO
                else GeminiSDK.GOOGLE_GENERATIVE_AI
            )

        if self.configuration.validate_credentials_on_startup:
            self.validate_configuration()

    @property
    def sdk(self) -> GeminiSDK:
        """Return the selected or detected SDK."""

        if self._sdk is not None:
            return self._sdk

        return self._detect_sdk()

    @property
    def has_api_key(self) -> bool:
        """Return whether a non-empty API key is configured."""

        return bool((self.configuration.api_key or "").strip())

    def _detect_sdk(self) -> GeminiSDK:
        """Detect the available Gemini SDK without creating a client."""

        requested = self.configuration.sdk

        if requested in {
            GeminiSDK.GOOGLE_GENAI,
            GeminiSDK.GOOGLE_GENERATIVE_AI,
        }:
            if self._sdk_available(requested):
                return requested

            return GeminiSDK.UNAVAILABLE

        if self._sdk_available(GeminiSDK.GOOGLE_GENAI):
            return GeminiSDK.GOOGLE_GENAI

        if self._sdk_available(GeminiSDK.GOOGLE_GENERATIVE_AI):
            return GeminiSDK.GOOGLE_GENERATIVE_AI

        return GeminiSDK.UNAVAILABLE

    @staticmethod
    def _sdk_available(sdk: GeminiSDK) -> bool:
        """Return whether a requested Gemini SDK can be imported."""

        try:
            if sdk is GeminiSDK.GOOGLE_GENAI:
                from google import genai  # noqa: F401

                return True

            if sdk is GeminiSDK.GOOGLE_GENERATIVE_AI:
                import google.generativeai  # noqa: F401

                return True

        except (ImportError, ModuleNotFoundError):
            return False

        return False

    def validate_configuration(self) -> None:
        """Validate provider activation, credentials, and SDK availability."""

        super().validate_configuration()

        if not self.has_api_key and self._client is None:
            variable_names = ", ".join(
                API_KEY_ENVIRONMENT_VARIABLES
            )

            raise ProviderAuthenticationError(
                (
                    "Gemini API key is not configured. Set one of: "
                    f"{variable_names}"
                ),
                provider=self.name,
            )

        detected_sdk = self._detect_sdk()

        if detected_sdk is GeminiSDK.UNAVAILABLE and self._client is None:
            raise ProviderConfigurationError(
                (
                    "No supported Gemini SDK is installed. Install "
                    "'google-genai' or 'google-generativeai'."
                ),
                provider=self.name,
            )

    def validate_request(self, request: Any) -> None:
        """Validate the canonical or dictionary-style AI request."""

        super().validate_request(request)

        prompt = self._request_prompt(request)

        if not prompt.strip():
            raise ProviderConfigurationError(
                "Gemini request prompt cannot be empty",
                provider=self.name,
                request_id=self._request_id(request),
            )

    def _create_client(self) -> Any:
        """Create the appropriate Google Gemini client lazily."""

        with self._client_lock:
            if self._client is not None:
                return self._client

            self.validate_configuration()
            selected_sdk = self._detect_sdk()

            if selected_sdk is GeminiSDK.GOOGLE_GENAI:
                from google import genai

                self._client = genai.Client(
                    api_key=self.configuration.api_key
                )
                self._sdk = selected_sdk
                return self._client

            if selected_sdk is GeminiSDK.GOOGLE_GENERATIVE_AI:
                import google.generativeai as generative_ai

                generative_ai.configure(
                    api_key=self.configuration.api_key
                )
                self._client = generative_ai
                self._sdk = selected_sdk
                return self._client

            raise ProviderUnavailableError(
                "Gemini client could not be initialized",
                provider=self.name,
            )

    def _request_task(self, request: Any) -> str:
        task = _first_non_empty(
            request,
            ("task", "task_type", "operation", "purpose"),
            default="text_generation",
        )

        task = _enum_value(task)
        return str(task).strip().lower() or "text_generation"

    def _request_prompt(self, request: Any) -> str:
        """Extract the main prompt from common request shapes."""

        prompt = _first_non_empty(
            request,
            (
                "prompt",
                "input_text",
                "text",
                "content",
                "source_text",
                "instruction",
            ),
            default="",
        )

        if isinstance(prompt, str):
            return prompt

        if isinstance(prompt, Sequence) and not isinstance(
            prompt,
            (bytes, bytearray),
        ):
            return "\n".join(str(item) for item in prompt)

        return str(prompt or "")

    def _request_system_instruction(
        self,
        request: Any,
    ) -> str | None:
        instruction = _first_non_empty(
            request,
            (
                "system_instruction",
                "system_prompt",
                "system_message",
            ),
            default=self.configuration.system_instruction,
        )

        if instruction is None:
            return None

        return str(instruction).strip() or None

    def _request_model_name(self, request: Any) -> str:
        model = _first_non_empty(
            request,
            ("model", "model_name"),
            default=self.configuration.model,
        )

        return str(_enum_value(model)).strip()

    def _request_metadata(self, request: Any) -> dict[str, Any]:
        metadata = read_object_field(
            request,
            "metadata",
            "context",
            default={},
        )

        if isinstance(metadata, Mapping):
            return dict(metadata)

        return {}

    def _expects_structured_output(self, request: Any) -> bool:
        explicit = _first_non_empty(
            request,
            (
                "structured_output",
                "json_output",
                "expect_json",
            ),
            default=None,
        )

        if explicit is not None:
            return bool(explicit)

        response_format = _first_non_empty(
            request,
            ("response_format", "output_format"),
            default=None,
        )

        response_format = str(
            _enum_value(response_format) or ""
        ).lower()

        return response_format in {
            "json",
            "application/json",
            "structured",
            "structured_output",
        }

    def _generation_settings(
        self,
        request: Any,
    ) -> GeminiGenerationSettings:
        """Resolve request overrides against provider defaults."""

        base = self.configuration.generation
        structured = self._expects_structured_output(request)

        temperature = read_object_field(
            request,
            "temperature",
            default=None,
        )
        top_p = read_object_field(request, "top_p", default=None)
        top_k = read_object_field(request, "top_k", default=None)
        maximum_tokens = _first_non_empty(
            request,
            (
                "maximum_output_tokens",
                "max_output_tokens",
                "max_tokens",
            ),
            default=None,
        )
        candidate_count = read_object_field(
            request,
            "candidate_count",
            default=None,
        )
        stop_sequences = _first_non_empty(
            request,
            ("stop_sequences", "stop"),
            default=None,
        )

        if isinstance(stop_sequences, str):
            stop_sequences = (stop_sequences,)

        return base.with_overrides(
            temperature=(
                None
                if temperature is None
                else safe_float(temperature, base.temperature)
            ),
            top_p=(
                None
                if top_p is None
                else safe_float(top_p, base.top_p)
            ),
            top_k=(
                None
                if top_k is None
                else safe_int(top_k, base.top_k)
            ),
            maximum_output_tokens=(
                None
                if maximum_tokens is None
                else safe_int(
                    maximum_tokens,
                    base.maximum_output_tokens,
                )
            ),
            candidate_count=(
                None
                if candidate_count is None
                else safe_int(
                    candidate_count,
                    base.candidate_count,
                )
            ),
            stop_sequences=stop_sequences,
            response_mime_type=(
                "application/json"
                if structured
                else base.response_mime_type
            ),
        )

    def _build_instruction_prompt(self, request: Any) -> str:
        """
        Construct an explicit task-aware prompt.

        The canonical request prompt remains authoritative. Task instructions
        only improve consistency across providers.
        """

        task = self._request_task(request)
        prompt = self._request_prompt(request).strip()
        source_language = _first_non_empty(
            request,
            ("source_language", "input_language"),
            default=None,
        )
        target_language = _first_non_empty(
            request,
            ("target_language", "output_language", "language"),
            default=None,
        )
        metadata = self._request_metadata(request)

        task_instructions: dict[str, str] = {
            "translation": (
                "Translate the supplied news content accurately. Preserve "
                "names, facts, numbers, dates, quotations, and journalistic "
                "meaning. Do not add unsupported information."
            ),
            "summarization": (
                "Summarize the supplied news content accurately and concisely. "
                "Retain the most important facts and avoid speculation."
            ),
            "classification": (
                "Classify the supplied news content according to the requested "
                "categories. Return only the requested classification result."
            ),
            "editorial_polishing": (
                "Polish the supplied news script for professional broadcast. "
                "Correct grammar, clarity, flow, punctuation, and repetition "
                "without changing verified facts."
            ),
            "script_generation": (
                "Create a clear broadcast-news script from the supplied facts. "
                "Use professional journalistic language and do not invent "
                "details."
            ),
            "text_generation": (
                "Complete the requested text-generation task accurately and "
                "follow all supplied constraints."
            ),
        }

        instruction = task_instructions.get(
            task,
            task_instructions["text_generation"],
        )

        sections = [
            f"Task: {task}",
            f"Instruction: {instruction}",
        ]

        if source_language:
            sections.append(
                f"Source language: {_enum_value(source_language)}"
            )

        if target_language:
            sections.append(
                f"Target language: {_enum_value(target_language)}"
            )

        style = metadata.get("style")
        audience = metadata.get("audience")
        constraints = metadata.get("constraints")

        if style:
            sections.append(f"Required style: {style}")

        if audience:
            sections.append(f"Audience: {audience}")

        if constraints:
            if isinstance(constraints, Sequence) and not isinstance(
                constraints,
                str,
            ):
                constraint_text = "; ".join(
                    str(item) for item in constraints
                )
            else:
                constraint_text = str(constraints)

            sections.append(f"Additional constraints: {constraint_text}")

        if self._expects_structured_output(request):
            sections.append(
                "Output format: Return valid JSON only, without Markdown "
                "fences or explanatory text."
            )

        sections.extend(
            [
                "",
                "Input:",
                prompt,
            ]
        )

        return "\n".join(sections)

    def _legacy_generation_config(
        self,
        settings: GeminiGenerationSettings,
    ) -> dict[str, Any]:
        """Build generation config for ``google-generativeai``."""

        return _mapping_without_none(
            {
                "temperature": settings.temperature,
                "top_p": settings.top_p,
                "top_k": settings.top_k,
                "max_output_tokens": (
                    settings.maximum_output_tokens
                ),
                "candidate_count": settings.candidate_count,
                "stop_sequences": list(settings.stop_sequences),
                "response_mime_type": settings.response_mime_type,
            }
        )

    def _new_sdk_generation_config(
        self,
        settings: GeminiGenerationSettings,
        system_instruction: str | None,
    ) -> Any:
        """Build config for ``google-genai``."""

        try:
            from google.genai import types

            values = _mapping_without_none(
                {
                    "temperature": settings.temperature,
                    "top_p": settings.top_p,
                    "top_k": settings.top_k,
                    "max_output_tokens": (
                        settings.maximum_output_tokens
                    ),
                    "candidate_count": settings.candidate_count,
                    "stop_sequences": list(
                        settings.stop_sequences
                    ),
                    "response_mime_type": (
                        settings.response_mime_type
                    ),
                    "system_instruction": system_instruction,
                }
            )

            if self.configuration.safety_settings:
                values["safety_settings"] = [
                    dict(item)
                    for item in self.configuration.safety_settings
                ]

            return types.GenerateContentConfig(**values)

        except (ImportError, AttributeError, TypeError):
            return _mapping_without_none(
                {
                    "temperature": settings.temperature,
                    "top_p": settings.top_p,
                    "top_k": settings.top_k,
                    "max_output_tokens": (
                        settings.maximum_output_tokens
                    ),
                    "candidate_count": settings.candidate_count,
                    "stop_sequences": list(
                        settings.stop_sequences
                    ),
                    "response_mime_type": (
                        settings.response_mime_type
                    ),
                    "system_instruction": system_instruction,
                }
            )

    def _generate_with_new_sdk(
        self,
        client: Any,
        *,
        model_name: str,
        prompt: str,
        system_instruction: str | None,
        settings: GeminiGenerationSettings,
    ) -> Any:
        config = self._new_sdk_generation_config(
            settings,
            system_instruction,
        )

        return client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=config,
        )

    def _generate_with_legacy_sdk(
        self,
        sdk_module: Any,
        *,
        model_name: str,
        prompt: str,
        system_instruction: str | None,
        settings: GeminiGenerationSettings,
    ) -> Any:
        model_arguments: dict[str, Any] = {
            "model_name": model_name,
            "generation_config": self._legacy_generation_config(
                settings
            ),
        }

        if system_instruction:
            model_arguments["system_instruction"] = (
                system_instruction
            )

        if self.configuration.safety_settings:
            model_arguments["safety_settings"] = [
                dict(item)
                for item in self.configuration.safety_settings
            ]

        model = sdk_module.GenerativeModel(**model_arguments)
        return model.generate_content(prompt)

    def _extract_response_text(self, response: Any) -> str:
        """Extract generated text from either Gemini SDK."""

        direct_text = read_object_field(
            response,
            "text",
            "output_text",
            default=None,
        )

        if direct_text:
            return str(direct_text).strip()

        candidates = read_object_field(
            response,
            "candidates",
            default=(),
        ) or ()

        text_parts: list[str] = []

        for candidate in candidates:
            content = read_object_field(
                candidate,
                "content",
                default=None,
            )

            parts = read_object_field(
                content,
                "parts",
                default=(),
            ) or ()

            for part in parts:
                part_text = read_object_field(
                    part,
                    "text",
                    default=None,
                )

                if part_text:
                    text_parts.append(str(part_text))

        return "\n".join(text_parts).strip()

    def _extract_finish_reason(self, response: Any) -> str | None:
        candidates = read_object_field(
            response,
            "candidates",
            default=(),
        ) or ()

        if not candidates:
            return None

        reason = read_object_field(
            candidates[0],
            "finish_reason",
            "finishReason",
            default=None,
        )

        if reason is None:
            return None

        return str(_enum_value(reason))

    def _extract_usage_metadata(
        self,
        response: Any,
    ) -> GeminiUsage:
        usage = read_object_field(
            response,
            "usage_metadata",
            "usageMetadata",
            "usage",
            default=None,
        )

        if usage is None:
            return GeminiUsage()

        input_tokens = safe_int(
            _first_non_empty(
                usage,
                (
                    "prompt_token_count",
                    "promptTokenCount",
                    "input_tokens",
                    "prompt_tokens",
                ),
                default=0,
            )
        )
        output_tokens = safe_int(
            _first_non_empty(
                usage,
                (
                    "candidates_token_count",
                    "candidatesTokenCount",
                    "output_tokens",
                    "completion_tokens",
                ),
                default=0,
            )
        )
        total_tokens = safe_int(
            _first_non_empty(
                usage,
                (
                    "total_token_count",
                    "totalTokenCount",
                    "total_tokens",
                ),
                default=input_tokens + output_tokens,
            )
        )
        cached_tokens = safe_int(
            _first_non_empty(
                usage,
                (
                    "cached_content_token_count",
                    "cachedContentTokenCount",
                    "cached_tokens",
                ),
                default=0,
            )
        )

        if total_tokens <= 0:
            total_tokens = input_tokens + output_tokens

        return GeminiUsage(
            input_tokens=max(0, input_tokens),
            output_tokens=max(0, output_tokens),
            total_tokens=max(0, total_tokens),
            cached_tokens=max(0, cached_tokens),
        )

    def _extract_safety_ratings(
        self,
        response: Any,
    ) -> tuple[Mapping[str, Any], ...]:
        candidates = read_object_field(
            response,
            "candidates",
            default=(),
        ) or ()

        ratings: list[Mapping[str, Any]] = []

        for candidate in candidates:
            candidate_ratings = read_object_field(
                candidate,
                "safety_ratings",
                "safetyRatings",
                default=(),
            ) or ()

            for rating in candidate_ratings:
                normalized = _json_safe(rating)

                if isinstance(normalized, Mapping):
                    ratings.append(dict(normalized))
                else:
                    ratings.append({"value": normalized})

        return tuple(ratings)

    def _generate_once(
        self,
        request: Any,
        context: ProviderExecutionContext,
    ) -> GeminiResponse:
        """Execute one Gemini generation attempt."""

        client = self._create_client()
        model_name = self._request_model_name(request)
        prompt = self._build_instruction_prompt(request)
        system_instruction = self._request_system_instruction(request)
        settings = self._generation_settings(request)
        task = self._request_task(request)

        attempt_started = time.monotonic()

        try:
            selected_sdk = self.sdk

            if selected_sdk is GeminiSDK.GOOGLE_GENAI:
                raw_response = self._generate_with_new_sdk(
                    client,
                    model_name=model_name,
                    prompt=prompt,
                    system_instruction=system_instruction,
                    settings=settings,
                )

            elif (
                selected_sdk
                is GeminiSDK.GOOGLE_GENERATIVE_AI
            ):
                raw_response = self._generate_with_legacy_sdk(
                    client,
                    model_name=model_name,
                    prompt=prompt,
                    system_instruction=system_instruction,
                    settings=settings,
                )

            else:
                raise ProviderUnavailableError(
                    "No usable Gemini SDK is available",
                    provider=self.name,
                    request_id=context.request_id,
                )

        except Exception as error:
            self._raise_normalized_sdk_error(
                error,
                request_id=context.request_id,
            )
            raise AssertionError("Unreachable error normalization path")

        text = self._extract_response_text(raw_response)

        if not text:
            prompt_feedback = read_object_field(
                raw_response,
                "prompt_feedback",
                "promptFeedback",
                default=None,
            )

            raise ProviderResponseError(
                (
                    "Gemini returned an empty response"
                    + (
                        f"; prompt_feedback={_json_safe(prompt_feedback)}"
                        if prompt_feedback is not None
                        else ""
                    )
                ),
                provider=self.name,
                request_id=context.request_id,
            )

        structured_data = (
            _extract_json_from_text(text)
            if self._expects_structured_output(request)
            else None
        )

        if (
            self._expects_structured_output(request)
            and structured_data is None
        ):
            raise ProviderResponseError(
                "Gemini did not return valid structured JSON",
                provider=self.name,
                request_id=context.request_id,
            )

        elapsed = time.monotonic() - attempt_started
        usage = self._extract_usage_metadata(raw_response)

        return GeminiResponse(
            request_id=context.request_id,
            status="success",
            provider=self.name,
            model=model_name,
            task=task,
            text=text,
            created_at=utc_now_iso(),
            usage=usage,
            finish_reason=self._extract_finish_reason(
                raw_response
            ),
            structured_data=structured_data,
            safety_ratings=self._extract_safety_ratings(
                raw_response
            ),
            metadata={
                "sdk": self.sdk.value,
                "latency_seconds": elapsed,
                "temperature": settings.temperature,
                "top_p": settings.top_p,
                "top_k": settings.top_k,
                "maximum_output_tokens": (
                    settings.maximum_output_tokens
                ),
                "response_mime_type": (
                    settings.response_mime_type
                ),
            },
        )

    def _raise_normalized_sdk_error(
        self,
        error: Exception,
        *,
        request_id: str,
    ) -> None:
        """Translate SDK-specific failures into provider exceptions."""

        error_type = type(error).__name__.lower()
        message = str(error)
        normalized_message = message.lower()

        common_arguments = {
            "provider": self.name,
            "request_id": request_id,
            "cause": error,
        }

        if any(
            marker in normalized_message
            for marker in (
                "api key",
                "api_key",
                "authentication",
                "unauthenticated",
                "permission denied",
                "401",
                "403",
            )
        ):
            raise ProviderAuthenticationError(
                f"Gemini authentication failed: {message}",
                **common_arguments,
            ) from error

        if any(
            marker in normalized_message
            for marker in (
                "quota",
                "rate limit",
                "rate_limit",
                "resource exhausted",
                "429",
                "too many requests",
            )
        ):
            from ai.providers.base import ProviderRateLimitError

            raise ProviderRateLimitError(
                f"Gemini rate limit reached: {message}",
                **common_arguments,
            ) from error

        if any(
            marker in normalized_message
            for marker in (
                "timeout",
                "deadline exceeded",
                "timed out",
            )
        ) or "timeout" in error_type:
            from ai.providers.base import ProviderTimeoutError

            raise ProviderTimeoutError(
                f"Gemini request timed out: {message}",
                **common_arguments,
            ) from error

        if any(
            marker in normalized_message
            for marker in (
                "connection",
                "network",
                "dns",
                "unavailable",
                "503",
                "502",
                "500",
            )
        ):
            from ai.providers.base import ProviderConnectionError

            raise ProviderConnectionError(
                f"Gemini connection failed: {message}",
                **common_arguments,
            ) from error

        if any(
            marker in normalized_message
            for marker in (
                "invalid argument",
                "invalid_argument",
                "model not found",
                "404",
            )
        ):
            raise ProviderConfigurationError(
                f"Gemini request configuration failed: {message}",
                **common_arguments,
            ) from error

        raise ProviderResponseError(
            f"Gemini generation failed: {message}",
            provider=self.name,
            request_id=request_id,
            cause=error,
            retryable=False,
        ) from error

    def extract_usage(
        self,
        response: GeminiResponse,
    ) -> tuple[int, int, int]:
        """Return normalized token usage to the provider metrics layer."""

        return (
            response.usage.input_tokens,
            response.usage.output_tokens,
            response.usage.total_tokens,
        )

    def _perform_health_check(
        self,
    ) -> tuple[bool, str, dict[str, Any]]:
        """
        Validate Gemini readiness without consuming generation quota.

        This verifies configuration, SDK availability, and client
        initialization. It deliberately avoids making a billable API call.
        """

        self.validate_configuration()
        client = self._create_client()

        return (
            client is not None,
            "Gemini provider configuration and client are ready",
            {
                "sdk": self.sdk.value,
                "model": self.configuration.model,
                "api_key_configured": self.has_api_key,
                "network_probe_performed": False,
            },
        )

    def describe(self) -> dict[str, Any]:
        """Return a safe serializable Gemini provider description."""

        description = super().describe()

        description.update(
            {
                "sdk": self.sdk.value,
                "api_key_configured": self.has_api_key,
                "generation": asdict(
                    self.configuration.generation
                ),
                "system_instruction_configured": bool(
                    self.configuration.system_instruction
                ),
                "safety_settings_count": len(
                    self.configuration.safety_settings
                ),
            }
        )

        return description

    def close(self) -> None:
        """Release supported Gemini client resources."""

        with self._client_lock:
            client = self._client

            if client is None:
                return

            close_method = getattr(client, "close", None)

            if callable(close_method):
                try:
                    close_method()
                except Exception:
                    self.logger.debug(
                        "Gemini client close failed",
                        exc_info=True,
                    )

            self._client = None


def create_gemini_provider(
    *,
    api_key: str | None = None,
    model: str | None = None,
    sdk: GeminiSDK | str = GeminiSDK.AUTO,
    enabled: bool = True,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    generation: GeminiGenerationSettings | None = None,
    system_instruction: str | None = None,
    safety_settings: Sequence[Mapping[str, Any]] | None = None,
    logger: logging.Logger | None = None,
) -> GeminiProvider:
    """Create a configured Gemini provider."""

    if isinstance(sdk, str):
        sdk = GeminiSDK(sdk)

    environment_configuration = (
        GeminiConfiguration.from_environment(
            model=model,
            sdk=sdk,
            enabled=enabled,
            timeout_seconds=timeout_seconds,
            generation=generation,
            system_instruction=system_instruction,
            safety_settings=safety_settings,
        )
    )

    configuration = GeminiConfiguration(
        api_key=api_key or environment_configuration.api_key,
        model=environment_configuration.model,
        sdk=environment_configuration.sdk,
        enabled=environment_configuration.enabled,
        timeout_seconds=environment_configuration.timeout_seconds,
        generation=environment_configuration.generation,
        system_instruction=(
            environment_configuration.system_instruction
        ),
        safety_settings=(
            environment_configuration.safety_settings
        ),
    )

    return GeminiProvider(
        configuration,
        logger=logger,
    )


@dataclass(frozen=True, slots=True)
class _SelfTestRequest:
    request_id: str
    task: str
    prompt: str
    source_language: str
    target_language: str
    model: str
    temperature: float = 0.1
    max_output_tokens: int = 256
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _FakeUsageMetadata:
    prompt_token_count: int
    candidates_token_count: int
    total_token_count: int


@dataclass(frozen=True, slots=True)
class _FakePart:
    text: str


@dataclass(frozen=True, slots=True)
class _FakeContent:
    parts: tuple[_FakePart, ...]


@dataclass(frozen=True, slots=True)
class _FakeCandidate:
    content: _FakeContent
    finish_reason: str
    safety_ratings: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class _FakeRawResponse:
    text: str
    candidates: tuple[_FakeCandidate, ...]
    usage_metadata: _FakeUsageMetadata


class _FakeLegacyModel:
    """Offline fake of the legacy Gemini model object."""

    def __init__(
        self,
        *,
        model_name: str,
        generation_config: Mapping[str, Any],
        system_instruction: str | None = None,
        safety_settings: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        self.model_name = model_name
        self.generation_config = dict(generation_config)
        self.system_instruction = system_instruction
        self.safety_settings = tuple(safety_settings or ())

    def generate_content(self, prompt: str) -> _FakeRawResponse:
        if "Translate" not in prompt and "translation" not in prompt:
            raise ValueError(
                "Self-test expected a translation instruction"
            )

        output = "భారీ వర్షాలపై అధికారులు హెచ్చరిక జారీ చేశారు."

        return _FakeRawResponse(
            text=output,
            candidates=(
                _FakeCandidate(
                    content=_FakeContent(
                        parts=(_FakePart(text=output),)
                    ),
                    finish_reason="STOP",
                ),
            ),
            usage_metadata=_FakeUsageMetadata(
                prompt_token_count=18,
                candidates_token_count=9,
                total_token_count=27,
            ),
        )


class _FakeLegacySDK:
    """Offline fake of ``google.generativeai``."""

    GenerativeModel = _FakeLegacyModel


class _SelfTestGeminiProvider(GeminiProvider):
    """Gemini provider configured with an offline deterministic client."""

    def _detect_sdk(self) -> GeminiSDK:
        return GeminiSDK.GOOGLE_GENERATIVE_AI


def _run_self_test() -> None:
    """Execute the Gemini adapter self-test without network access."""

    configuration = GeminiConfiguration(
        api_key="offline-self-test-key",
        model="gemini-flash-latest",
        sdk=GeminiSDK.GOOGLE_GENERATIVE_AI,
        enabled=True,
        timeout_seconds=5.0,
        generation=GeminiGenerationSettings(
            temperature=0.1,
            top_p=0.9,
            top_k=32,
            maximum_output_tokens=256,
        ),
        system_instruction=(
            "You are the Telugu translation assistant for BAHUVU NEWS."
        ),
    )

    provider = _SelfTestGeminiProvider(
        configuration,
        client=_FakeLegacySDK(),
    )

    request = _SelfTestRequest(
        request_id="gemini_provider_self_test_0001",
        task="translation",
        prompt=(
            "Officials issued a warning over continuing heavy rainfall."
        ),
        source_language="en",
        target_language="te",
        model="gemini-flash-latest",
        metadata={
            "style": "professional Telugu television news",
            "audience": "general Telugu-speaking audience",
        },
    )

    response = provider.generate(request)
    health = provider.health_check()
    metrics = provider.get_metrics()
    description = provider.describe()

    assert response.status == "success"
    assert response.provider == "gemini"
    assert response.model == "gemini-flash-latest"
    assert response.task == "translation"
    assert response.text.startswith("భారీ వర్షాలపై")
    assert response.usage.input_tokens == 18
    assert response.usage.output_tokens == 9
    assert response.usage.total_tokens == 27
    assert response.finish_reason == "STOP"

    assert health.status is ProviderOperationalStatus.HEALTHY
    assert metrics.total_requests == 1
    assert metrics.successful_requests == 1
    assert metrics.failed_requests == 0
    assert metrics.total_tokens == 27
    assert metrics.success_rate == 100.0

    assert provider.supports(ProviderCapability.TRANSLATION)
    assert provider.supports(
        ProviderCapability.STRUCTURED_OUTPUT
    )
    assert description["api_key_configured"] is True
    assert description["sdk"] == "google-generativeai"

    print(MODULE_NAME)
    print(f"Module version : {MODULE_VERSION}")
    print(f"Provider       : {response.provider}")
    print(f"SDK            : {provider.sdk.value}")
    print(f"Model          : {response.model}")
    print(f"Task           : {response.task}")
    print(f"Response status: {response.status}")
    print(f"Response text  : {response.text}")
    print(f"Tokens         : {response.usage.total_tokens}")
    print(f"Finish reason  : {response.finish_reason}")
    print(f"Health status  : {health.status.value}")
    print(f"Success rate   : {metrics.success_rate:.2f}%")
    print("Gemini AI provider self-test passed.")


if __name__ == "__main__":
    _run_self_test()