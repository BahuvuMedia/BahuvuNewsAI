"""
BahuvuNewsAI unified AI subsystem models.

This module contains provider-independent data structures used by:

- AI providers
- provider health checks
- intelligent routing
- retries and fallback handling
- cache management
- usage statistics
- production manifests

The module has no third-party dependencies.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4


MODULE_VERSION = "1.0.0"


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def new_identifier(prefix: str) -> str:
    """Create a compact, traceable identifier."""
    timestamp = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    random_part = uuid4().hex[:8]
    return f"{prefix}_{timestamp}_{random_part}"


class AIModelError(ValueError):
    """Raised when an AI model object contains invalid data."""


class AIProvider(str, Enum):
    """AI providers supported by the unified AI subsystem."""

    GEMINI = "gemini"
    GROQ = "groq"
    OPENROUTER = "openrouter"
    OFFLINE = "offline"


class AITask(str, Enum):
    """Types of work that can be routed through the AI subsystem."""

    GENERAL = "general"
    SCRIPT_GENERATION = "script_generation"
    TRANSLATION = "translation"
    EDITORIAL_POLISH = "editorial_polish"
    HEADLINE_GENERATION = "headline_generation"
    SUMMARIZATION = "summarization"
    CLASSIFICATION = "classification"
    FACT_EXTRACTION = "fact_extraction"
    METADATA_GENERATION = "metadata_generation"


class AIResponseStatus(str, Enum):
    """Final outcome of an AI generation request."""

    SUCCESS = "success"
    FALLBACK_SUCCESS = "fallback_success"
    FAILED = "failed"
    SKIPPED = "skipped"


class AIHealthStatus(str, Enum):
    """Operational health of an AI provider."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"
    UNKNOWN = "unknown"


class AIFailureCategory(str, Enum):
    """Normalized failure categories across providers."""

    AUTHENTICATION = "authentication"
    QUOTA = "quota"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    INVALID_REQUEST = "invalid_request"
    CONTENT_BLOCKED = "content_blocked"
    EMPTY_RESPONSE = "empty_response"
    PROVIDER_ERROR = "provider_error"
    CONFIGURATION = "configuration"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class AIGenerationOptions:
    """Provider-independent generation options."""

    temperature: float = 0.2
    max_output_tokens: int = 2048
    top_p: float | None = None
    stop_sequences: tuple[str, ...] = ()
    response_format: str = "text"

    def __post_init__(self) -> None:
        if not 0.0 <= self.temperature <= 2.0:
            raise AIModelError("temperature must be between 0.0 and 2.0.")

        if self.max_output_tokens <= 0:
            raise AIModelError("max_output_tokens must be greater than zero.")

        if self.top_p is not None and not 0.0 <= self.top_p <= 1.0:
            raise AIModelError("top_p must be between 0.0 and 1.0.")

        if not self.response_format.strip():
            raise AIModelError("response_format cannot be empty.")

        self.response_format = self.response_format.strip().lower()

        cleaned_sequences: list[str] = []
        for sequence in self.stop_sequences:
            cleaned = str(sequence).strip()
            if cleaned:
                cleaned_sequences.append(cleaned)

        self.stop_sequences = tuple(cleaned_sequences)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return asdict(self)


@dataclass(slots=True)
class AIRequest:
    """A provider-independent request sent to the AI manager."""

    prompt: str
    task: AITask = AITask.GENERAL
    system_prompt: str = ""
    preferred_provider: AIProvider | None = None
    preferred_model: str = ""
    options: AIGenerationOptions = field(default_factory=AIGenerationOptions)
    metadata: dict[str, Any] = field(default_factory=dict)
    cache_enabled: bool = True
    request_id: str = field(default_factory=lambda: new_identifier("ai_request"))
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.prompt = self.prompt.strip()
        self.system_prompt = self.system_prompt.strip()
        self.preferred_model = self.preferred_model.strip()

        if not self.prompt:
            raise AIModelError("AI request prompt cannot be empty.")

        if not isinstance(self.task, AITask):
            self.task = AITask(str(self.task))

        if (
            self.preferred_provider is not None
            and not isinstance(self.preferred_provider, AIProvider)
        ):
            self.preferred_provider = AIProvider(str(self.preferred_provider))

        if not self.request_id.strip():
            raise AIModelError("request_id cannot be empty.")

        if not isinstance(self.metadata, dict):
            self.metadata = dict(self.metadata)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "request_id": self.request_id,
            "created_at": self.created_at.isoformat(),
            "task": self.task.value,
            "prompt": self.prompt,
            "system_prompt": self.system_prompt,
            "preferred_provider": (
                self.preferred_provider.value
                if self.preferred_provider is not None
                else None
            ),
            "preferred_model": self.preferred_model,
            "options": self.options.to_dict(),
            "metadata": dict(self.metadata),
            "cache_enabled": self.cache_enabled,
        }


@dataclass(slots=True)
class AIAttempt:
    """One provider attempt made while processing an AI request."""

    provider: AIProvider
    model: str
    success: bool
    started_at: datetime
    completed_at: datetime
    latency_ms: float
    failure_category: AIFailureCategory | None = None
    error: str = ""
    retryable: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.provider, AIProvider):
            self.provider = AIProvider(str(self.provider))

        self.model = self.model.strip()
        self.error = self.error.strip()

        if self.latency_ms < 0:
            raise AIModelError("latency_ms cannot be negative.")

        if (
            self.failure_category is not None
            and not isinstance(self.failure_category, AIFailureCategory)
        ):
            self.failure_category = AIFailureCategory(
                str(self.failure_category)
            )

        if self.success:
            self.failure_category = None
            self.error = ""
            self.retryable = False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "provider": self.provider.value,
            "model": self.model,
            "success": self.success,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "latency_ms": round(self.latency_ms, 3),
            "failure_category": (
                self.failure_category.value
                if self.failure_category is not None
                else None
            ),
            "error": self.error,
            "retryable": self.retryable,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class AITokenUsage:
    """Normalized token usage returned by an AI provider."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        if self.input_tokens < 0:
            raise AIModelError("input_tokens cannot be negative.")

        if self.output_tokens < 0:
            raise AIModelError("output_tokens cannot be negative.")

        if self.total_tokens < 0:
            raise AIModelError("total_tokens cannot be negative.")

        calculated_total = self.input_tokens + self.output_tokens

        if self.total_tokens == 0 and calculated_total:
            self.total_tokens = calculated_total

        if self.total_tokens < calculated_total:
            self.total_tokens = calculated_total

    def to_dict(self) -> dict[str, int]:
        """Return a JSON-compatible representation."""
        return asdict(self)


@dataclass(slots=True)
class AIResponse:
    """Final normalized response produced by the AI manager."""

    request_id: str
    status: AIResponseStatus
    text: str = ""
    provider: AIProvider | None = None
    model: str = ""
    latency_ms: float = 0.0
    token_usage: AITokenUsage = field(default_factory=AITokenUsage)
    attempts: list[AIAttempt] = field(default_factory=list)
    cache_hit: bool = False
    fallback_used: bool = False
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    response_id: str = field(
        default_factory=lambda: new_identifier("ai_response")
    )
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.request_id = self.request_id.strip()
        self.text = self.text.strip()
        self.model = self.model.strip()
        self.error = self.error.strip()

        if not self.request_id:
            raise AIModelError("response request_id cannot be empty.")

        if not isinstance(self.status, AIResponseStatus):
            self.status = AIResponseStatus(str(self.status))

        if self.provider is not None and not isinstance(
            self.provider,
            AIProvider,
        ):
            self.provider = AIProvider(str(self.provider))

        if self.latency_ms < 0:
            raise AIModelError("response latency_ms cannot be negative.")

        if self.status in {
            AIResponseStatus.SUCCESS,
            AIResponseStatus.FALLBACK_SUCCESS,
        }:
            if not self.text:
                raise AIModelError(
                    "A successful AI response must contain text."
                )

            if self.provider is None:
                raise AIModelError(
                    "A successful AI response must identify its provider."
                )

            self.error = ""

        if self.status == AIResponseStatus.FALLBACK_SUCCESS:
            self.fallback_used = True

    @property
    def successful(self) -> bool:
        """Return whether generation ultimately succeeded."""
        return self.status in {
            AIResponseStatus.SUCCESS,
            AIResponseStatus.FALLBACK_SUCCESS,
        }

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "response_id": self.response_id,
            "request_id": self.request_id,
            "created_at": self.created_at.isoformat(),
            "status": self.status.value,
            "successful": self.successful,
            "text": self.text,
            "provider": (
                self.provider.value if self.provider is not None else None
            ),
            "model": self.model,
            "latency_ms": round(self.latency_ms, 3),
            "token_usage": self.token_usage.to_dict(),
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "cache_hit": self.cache_hit,
            "fallback_used": self.fallback_used,
            "error": self.error,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class AIProviderHealth:
    """Health-check result for one AI provider."""

    provider: AIProvider
    status: AIHealthStatus
    configured: bool
    available: bool
    model: str = ""
    checked_at: datetime = field(default_factory=utc_now)
    latency_ms: float | None = None
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.provider, AIProvider):
            self.provider = AIProvider(str(self.provider))

        if not isinstance(self.status, AIHealthStatus):
            self.status = AIHealthStatus(str(self.status))

        self.model = self.model.strip()
        self.message = self.message.strip()

        if self.latency_ms is not None and self.latency_ms < 0:
            raise AIModelError("health latency_ms cannot be negative.")

        if self.status == AIHealthStatus.HEALTHY:
            self.available = True

        if self.status in {
            AIHealthStatus.UNAVAILABLE,
            AIHealthStatus.DISABLED,
        }:
            self.available = False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "provider": self.provider.value,
            "status": self.status.value,
            "configured": self.configured,
            "available": self.available,
            "model": self.model,
            "checked_at": self.checked_at.isoformat(),
            "latency_ms": (
                round(self.latency_ms, 3)
                if self.latency_ms is not None
                else None
            ),
            "message": self.message,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class AIUsageRecord:
    """One accounting record for reporting and diagnostics."""

    provider: AIProvider
    model: str
    task: AITask
    success: bool
    latency_ms: float
    token_usage: AITokenUsage = field(default_factory=AITokenUsage)
    fallback_used: bool = False
    cache_hit: bool = False
    request_id: str = ""
    response_id: str = ""
    timestamp: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.provider, AIProvider):
            self.provider = AIProvider(str(self.provider))

        if not isinstance(self.task, AITask):
            self.task = AITask(str(self.task))

        self.model = self.model.strip()
        self.request_id = self.request_id.strip()
        self.response_id = self.response_id.strip()

        if self.latency_ms < 0:
            raise AIModelError("usage latency_ms cannot be negative.")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "provider": self.provider.value,
            "model": self.model,
            "task": self.task.value,
            "success": self.success,
            "latency_ms": round(self.latency_ms, 3),
            "token_usage": self.token_usage.to_dict(),
            "fallback_used": self.fallback_used,
            "cache_hit": self.cache_hit,
            "request_id": self.request_id,
            "response_id": self.response_id,
            "timestamp": self.timestamp.isoformat(),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class AIProviderConfig:
    """Runtime configuration for one AI provider."""

    provider: AIProvider
    enabled: bool = True
    api_key_env: str = ""
    default_model: str = ""
    priority: int = 100
    timeout_seconds: float = 60.0
    max_retries: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.provider, AIProvider):
            self.provider = AIProvider(str(self.provider))

        self.api_key_env = self.api_key_env.strip()
        self.default_model = self.default_model.strip()

        if self.priority < 0:
            raise AIModelError("provider priority cannot be negative.")

        if self.timeout_seconds <= 0:
            raise AIModelError(
                "provider timeout_seconds must be greater than zero."
            )

        if self.max_retries < 0:
            raise AIModelError("provider max_retries cannot be negative.")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        return {
            "provider": self.provider.value,
            "enabled": self.enabled,
            "api_key_env": self.api_key_env,
            "default_model": self.default_model,
            "priority": self.priority,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "metadata": dict(self.metadata),
        }


def normalize_metadata(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return a safe mutable metadata dictionary."""
    if metadata is None:
        return {}

    return dict(metadata)


def run_self_test() -> None:
    """Run deterministic model validation tests."""
    print("BahuvuNewsAI unified AI models")
    print(f"Module version : {MODULE_VERSION}")

    request = AIRequest(
        prompt="Translate this headline into broadcast Telugu.",
        task=AITask.TRANSLATION,
        preferred_provider=AIProvider.GEMINI,
        preferred_model="gemini-flash-latest",
        metadata={"story_id": "story_001"},
    )

    started_at = utc_now()
    completed_at = utc_now()

    attempt = AIAttempt(
        provider=AIProvider.GEMINI,
        model="gemini-flash-latest",
        success=True,
        started_at=started_at,
        completed_at=completed_at,
        latency_ms=125.5,
    )

    response = AIResponse(
        request_id=request.request_id,
        status=AIResponseStatus.SUCCESS,
        text="ఇది నమూనా తెలుగు వార్తా శీర్షిక.",
        provider=AIProvider.GEMINI,
        model="gemini-flash-latest",
        latency_ms=125.5,
        token_usage=AITokenUsage(
            input_tokens=20,
            output_tokens=12,
        ),
        attempts=[attempt],
    )

    health = AIProviderHealth(
        provider=AIProvider.GEMINI,
        status=AIHealthStatus.HEALTHY,
        configured=True,
        available=True,
        model="gemini-flash-latest",
        latency_ms=125.5,
        message="Provider self-test succeeded.",
    )

    usage = AIUsageRecord(
        provider=response.provider or AIProvider.OFFLINE,
        model=response.model,
        task=request.task,
        success=response.successful,
        latency_ms=response.latency_ms,
        token_usage=response.token_usage,
        fallback_used=response.fallback_used,
        cache_hit=response.cache_hit,
        request_id=request.request_id,
        response_id=response.response_id,
    )

    assert request.task == AITask.TRANSLATION
    assert response.successful is True
    assert response.token_usage.total_tokens == 32
    assert response.provider == AIProvider.GEMINI
    assert health.status == AIHealthStatus.HEALTHY
    assert usage.success is True
    assert usage.to_dict()["task"] == "translation"

    print(f"Request ID     : {request.request_id}")
    print(f"Task           : {request.task.value}")
    print(f"Provider       : {response.provider.value}")
    print(f"Model          : {response.model}")
    print(f"Response status: {response.status.value}")
    print(f"Tokens         : {response.token_usage.total_tokens}")
    print(f"Health status  : {health.status.value}")
    print("AI model self-test passed.")


if __name__ == "__main__":
    run_self_test()