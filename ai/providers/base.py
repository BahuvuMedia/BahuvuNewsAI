"""
BahuvuNewsAI unified AI provider foundation.

This module defines the common runtime contract used by every AI provider in
BahuvuNewsAI. Provider implementations such as Gemini, offline deterministic
processing, OpenAI, Anthropic, or local models should inherit from
``BaseAIProvider``.

The provider foundation supplies:

* A consistent synchronous and asynchronous generation interface.
* Provider capabilities and metadata.
* Retry handling with exponential backoff.
* Timeout enforcement.
* Thread-safe rate limiting.
* Health monitoring.
* Request lifecycle hooks.
* Usage and latency metrics.
* Structured error handling.
* Safe request and response inspection.
* A deterministic executable self-test.

This module intentionally avoids depending on specific request and response
class names from ``ai.models``. That keeps the provider layer compatible with
the canonical models while also allowing dictionaries, dataclasses, and custom
typed objects during testing and future migrations.
"""

from __future__ import annotations

import abc
import asyncio
import inspect
import logging
import random
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Callable, Generic, Mapping, Sequence, TypeVar


__all__ = [
    "AIProviderError",
    "ProviderAuthenticationError",
    "ProviderConfigurationError",
    "ProviderConnectionError",
    "ProviderRateLimitError",
    "ProviderResponseError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "ProviderCapability",
    "ProviderOperationalStatus",
    "RetryPolicy",
    "RateLimitPolicy",
    "ProviderMetadata",
    "ProviderMetrics",
    "ProviderHealth",
    "ProviderExecutionContext",
    "BaseAIProvider",
]


MODULE_NAME = "BahuvuNewsAI unified AI provider foundation"
MODULE_VERSION = "1.0.0"

RequestT = TypeVar("RequestT")
ResponseT = TypeVar("ResponseT")


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""

    return datetime.now(UTC)


def utc_now_iso() -> str:
    """Return the current UTC datetime in ISO-8601 format."""

    return utc_now().isoformat()


def safe_float(value: Any, default: float = 0.0) -> float:
    """Convert a value to float without propagating conversion errors."""

    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """Convert a value to int without propagating conversion errors."""

    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def object_to_mapping(value: Any) -> dict[str, Any]:
    """
    Convert an arbitrary request or response object into a shallow dictionary.

    Supported values include mappings, dataclasses, Pydantic-style objects,
    named tuples, and regular objects with ``__dict__``.
    """

    if value is None:
        return {}

    if isinstance(value, Mapping):
        return dict(value)

    if is_dataclass(value) and not isinstance(value, type):
        try:
            return dict(asdict(value))
        except (TypeError, ValueError):
            pass

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump()
            if isinstance(dumped, Mapping):
                return dict(dumped)
        except Exception:
            pass

    dict_method = getattr(value, "dict", None)
    if callable(dict_method):
        try:
            dumped = dict_method()
            if isinstance(dumped, Mapping):
                return dict(dumped)
        except Exception:
            pass

    asdict_method = getattr(value, "_asdict", None)
    if callable(asdict_method):
        try:
            dumped = asdict_method()
            if isinstance(dumped, Mapping):
                return dict(dumped)
        except Exception:
            pass

    instance_dict = getattr(value, "__dict__", None)
    if isinstance(instance_dict, dict):
        return dict(instance_dict)

    return {"value": value}


def read_object_field(
    value: Any,
    *names: str,
    default: Any = None,
) -> Any:
    """
    Read the first available field from a mapping or object.

    This utility allows the provider foundation to work with canonical
    ``ai.models`` objects without tightly coupling this module to one exact
    model implementation.
    """

    if value is None:
        return default

    for name in names:
        if isinstance(value, Mapping) and name in value:
            return value[name]

        if hasattr(value, name):
            try:
                return getattr(value, name)
            except Exception:
                continue

    return default


def response_is_successful(response: Any) -> bool:
    """
    Determine whether a provider response represents success.

    Responses without an explicit status field are considered successful when
    they are not ``None``. This supports simple provider implementations while
    still respecting canonical status fields.
    """

    if response is None:
        return False

    status = read_object_field(
        response,
        "status",
        "response_status",
        "state",
        default=None,
    )

    if status is None:
        success = read_object_field(
            response,
            "success",
            "is_success",
            default=None,
        )
        if success is None:
            return True
        return bool(success)

    if isinstance(status, Enum):
        status = status.value

    normalized = str(status).strip().lower()

    return normalized in {
        "success",
        "successful",
        "completed",
        "complete",
        "ok",
        "ready",
        "healthy",
    }


class AIProviderError(RuntimeError):
    """Base exception for all provider-related failures."""

    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        request_id: str | None = None,
        retryable: bool | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.request_id = request_id
        self.cause = cause

        if retryable is not None:
            self.retryable = retryable

    def __str__(self) -> str:
        details: list[str] = [super().__str__()]

        if self.provider:
            details.append(f"provider={self.provider}")

        if self.request_id:
            details.append(f"request_id={self.request_id}")

        return " | ".join(details)


class ProviderConfigurationError(AIProviderError):
    """Raised when a provider is incorrectly configured."""

    retryable = False


class ProviderAuthenticationError(AIProviderError):
    """Raised when provider credentials are missing or rejected."""

    retryable = False


class ProviderConnectionError(AIProviderError):
    """Raised when a provider cannot be reached."""

    retryable = True


class ProviderTimeoutError(AIProviderError):
    """Raised when provider execution exceeds its configured timeout."""

    retryable = True


class ProviderRateLimitError(AIProviderError):
    """Raised when a provider rejects work because of rate limiting."""

    retryable = True


class ProviderUnavailableError(AIProviderError):
    """Raised when a provider is temporarily unavailable."""

    retryable = True


class ProviderResponseError(AIProviderError):
    """Raised when a provider returns an invalid or unusable response."""

    retryable = False


class ProviderCapability(str, Enum):
    """Capabilities that an AI provider may advertise."""

    TEXT_GENERATION = "text_generation"
    TRANSLATION = "translation"
    SUMMARIZATION = "summarization"
    CLASSIFICATION = "classification"
    EDITORIAL_POLISHING = "editorial_polishing"
    SCRIPT_GENERATION = "script_generation"
    STRUCTURED_OUTPUT = "structured_output"
    STREAMING = "streaming"
    TOOL_CALLING = "tool_calling"
    VISION = "vision"
    EMBEDDINGS = "embeddings"
    OFFLINE = "offline"


class ProviderOperationalStatus(str, Enum):
    """Current runtime health state of a provider."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Configuration for retrying transient provider failures."""

    max_attempts: int = 3
    initial_delay_seconds: float = 1.0
    maximum_delay_seconds: float = 20.0
    exponential_base: float = 2.0
    jitter_seconds: float = 0.25
    retry_unknown_errors: bool = False

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

        if self.initial_delay_seconds < 0:
            raise ValueError("initial_delay_seconds cannot be negative")

        if self.maximum_delay_seconds < 0:
            raise ValueError("maximum_delay_seconds cannot be negative")

        if self.exponential_base < 1:
            raise ValueError("exponential_base must be at least 1")

        if self.jitter_seconds < 0:
            raise ValueError("jitter_seconds cannot be negative")

    def delay_for_attempt(self, attempt_number: int) -> float:
        """Calculate the delay before the next attempt."""

        if attempt_number < 1:
            raise ValueError("attempt_number must be at least 1")

        delay = self.initial_delay_seconds * (
            self.exponential_base ** (attempt_number - 1)
        )
        delay = min(delay, self.maximum_delay_seconds)

        if self.jitter_seconds:
            delay += random.uniform(0.0, self.jitter_seconds)

        return max(0.0, delay)


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    """Local sliding-window request throttling configuration."""

    requests_per_window: int = 60
    window_seconds: float = 60.0
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.requests_per_window < 1:
            raise ValueError("requests_per_window must be at least 1")

        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be greater than zero")


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    """Static provider identification and capability information."""

    name: str
    display_name: str
    version: str = "1.0.0"
    provider_type: str = "remote"
    default_model: str | None = None
    capabilities: frozenset[ProviderCapability] = field(
        default_factory=frozenset
    )
    description: str = ""
    documentation_url: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Provider name cannot be empty")

        if not self.display_name.strip():
            raise ValueError("Provider display name cannot be empty")

    def supports(self, capability: ProviderCapability | str) -> bool:
        """Return whether this provider advertises a capability."""

        if isinstance(capability, str):
            try:
                capability = ProviderCapability(capability)
            except ValueError:
                return False

        return capability in self.capabilities


@dataclass(slots=True)
class ProviderMetrics:
    """Thread-safe provider execution metrics snapshot."""

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    retried_requests: int = 0
    rate_limit_waits: int = 0
    timeout_failures: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_latency_seconds: float = 0.0
    last_latency_seconds: float = 0.0
    last_request_at: str | None = None
    last_success_at: str | None = None
    last_failure_at: str | None = None
    last_error: str | None = None

    @property
    def success_rate(self) -> float:
        """Return the successful request percentage."""

        if self.total_requests == 0:
            return 0.0

        return (self.successful_requests / self.total_requests) * 100.0

    @property
    def average_latency_seconds(self) -> float:
        """Return mean provider latency."""

        if self.total_requests == 0:
            return 0.0

        return self.total_latency_seconds / self.total_requests

    def copy(self) -> ProviderMetrics:
        """Return a detached metrics snapshot."""

        return ProviderMetrics(**asdict(self))


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    """Provider health-check result."""

    provider: str
    status: ProviderOperationalStatus
    checked_at: str
    message: str = ""
    latency_seconds: float = 0.0
    model: str | None = None
    consecutive_failures: int = 0
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        """Return whether the provider is currently healthy."""

        return self.status is ProviderOperationalStatus.HEALTHY


@dataclass(slots=True)
class ProviderExecutionContext:
    """Mutable lifecycle context for one provider request."""

    provider: str
    request_id: str
    model: str | None
    started_at: str
    attempt: int = 1
    maximum_attempts: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


class SlidingWindowRateLimiter:
    """Thread-safe sliding-window rate limiter."""

    def __init__(self, policy: RateLimitPolicy) -> None:
        self.policy = policy
        self._timestamps: deque[float] = deque()
        self._condition = threading.Condition(threading.RLock())

    def _remove_expired(self, now: float) -> None:
        cutoff = now - self.policy.window_seconds

        while self._timestamps and self._timestamps[0] <= cutoff:
            self._timestamps.popleft()

    def acquire(self) -> float:
        """
        Wait until a request slot is available.

        Returns the number of seconds spent waiting.
        """

        if not self.policy.enabled:
            return 0.0

        wait_started = time.monotonic()

        with self._condition:
            while True:
                now = time.monotonic()
                self._remove_expired(now)

                if len(self._timestamps) < self.policy.requests_per_window:
                    self._timestamps.append(now)
                    self._condition.notify_all()
                    return time.monotonic() - wait_started

                oldest = self._timestamps[0]
                wait_seconds = max(
                    0.001,
                    self.policy.window_seconds - (now - oldest),
                )
                self._condition.wait(timeout=wait_seconds)

    async def acquire_async(self) -> float:
        """Asynchronous wrapper around the thread-safe limiter."""

        return await asyncio.to_thread(self.acquire)


class BaseAIProvider(
    Generic[RequestT, ResponseT],
    abc.ABC,
):
    """
    Abstract base class for all BahuvuNewsAI AI providers.

    Subclasses must implement ``_generate_once``. They may additionally
    override health checking, response validation, token extraction, lifecycle
    hooks, and asynchronous execution.
    """

    def __init__(
        self,
        metadata: ProviderMetadata,
        *,
        enabled: bool = True,
        timeout_seconds: float = 60.0,
        retry_policy: RetryPolicy | None = None,
        rate_limit_policy: RateLimitPolicy | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

        self.metadata = metadata
        self.enabled = bool(enabled)
        self.timeout_seconds = float(timeout_seconds)
        self.retry_policy = retry_policy or RetryPolicy()
        self.rate_limit_policy = rate_limit_policy or RateLimitPolicy()

        self.logger = logger or logging.getLogger(
            f"BahuvuNewsAI.ai.providers.{metadata.name}"
        )

        self._rate_limiter = SlidingWindowRateLimiter(
            self.rate_limit_policy
        )
        self._metrics = ProviderMetrics()
        self._metrics_lock = threading.RLock()

        self._health_status = (
            ProviderOperationalStatus.UNKNOWN
            if self.enabled
            else ProviderOperationalStatus.DISABLED
        )
        self._consecutive_failures = 0
        self._last_health: ProviderHealth | None = None

    @property
    def name(self) -> str:
        """Return the provider's canonical name."""

        return self.metadata.name

    @property
    def display_name(self) -> str:
        """Return the provider's display name."""

        return self.metadata.display_name

    @property
    def default_model(self) -> str | None:
        """Return the provider's configured default model."""

        return self.metadata.default_model

    @property
    def status(self) -> ProviderOperationalStatus:
        """Return the provider's current operational status."""

        if not self.enabled:
            return ProviderOperationalStatus.DISABLED

        return self._health_status

    @property
    def last_health(self) -> ProviderHealth | None:
        """Return the latest health-check result."""

        return self._last_health

    def supports(self, capability: ProviderCapability | str) -> bool:
        """Return whether the provider supports a capability."""

        return self.metadata.supports(capability)

    def get_metrics(self) -> ProviderMetrics:
        """Return a detached, thread-safe metrics snapshot."""

        with self._metrics_lock:
            return self._metrics.copy()

    def reset_metrics(self) -> None:
        """Reset provider metrics."""

        with self._metrics_lock:
            self._metrics = ProviderMetrics()

    def validate_configuration(self) -> None:
        """
        Validate provider configuration before execution.

        Provider implementations should override this method and raise
        ``ProviderConfigurationError`` or ``ProviderAuthenticationError`` when
        configuration is unusable.
        """

        if not self.enabled:
            raise ProviderUnavailableError(
                "Provider is disabled",
                provider=self.name,
            )

    def validate_request(self, request: RequestT) -> None:
        """Validate a request before provider execution."""

        if request is None:
            raise ProviderConfigurationError(
                "AI request cannot be None",
                provider=self.name,
            )

    def validate_response(
        self,
        response: ResponseT,
        request: RequestT,
    ) -> None:
        """Validate the response returned by the provider."""

        del request

        if response is None:
            raise ProviderResponseError(
                "Provider returned no response",
                provider=self.name,
            )

        if not response_is_successful(response):
            status = read_object_field(
                response,
                "status",
                "response_status",
                default="unknown",
            )
            error = read_object_field(
                response,
                "error",
                "error_message",
                "message",
                default="Provider returned an unsuccessful response",
            )

            raise ProviderResponseError(
                f"{error}; status={status}",
                provider=self.name,
            )

    @abc.abstractmethod
    def _generate_once(
        self,
        request: RequestT,
        context: ProviderExecutionContext,
    ) -> ResponseT:
        """
        Execute one provider request attempt.

        Retry handling, timeout enforcement, metrics, and lifecycle processing
        are managed by ``generate``.
        """

        raise NotImplementedError

    async def _generate_once_async(
        self,
        request: RequestT,
        context: ProviderExecutionContext,
    ) -> ResponseT:
        """
        Execute one asynchronous provider attempt.

        The default implementation safely runs the synchronous provider method
        in a worker thread. Native asynchronous providers may override it.
        """

        return await asyncio.to_thread(
            self._generate_once,
            request,
            context,
        )

    def before_request(
        self,
        request: RequestT,
        context: ProviderExecutionContext,
    ) -> None:
        """Lifecycle hook executed before the first attempt."""

        del request, context

    def before_attempt(
        self,
        request: RequestT,
        context: ProviderExecutionContext,
    ) -> None:
        """Lifecycle hook executed before every attempt."""

        del request, context

    def after_success(
        self,
        request: RequestT,
        response: ResponseT,
        context: ProviderExecutionContext,
    ) -> None:
        """Lifecycle hook executed following a successful response."""

        del request, response, context

    def after_failure(
        self,
        request: RequestT,
        error: BaseException,
        context: ProviderExecutionContext,
    ) -> None:
        """Lifecycle hook executed following final request failure."""

        del request, error, context

    def extract_usage(
        self,
        response: ResponseT,
    ) -> tuple[int, int, int]:
        """
        Extract input, output, and total token usage from a response.

        The default implementation supports common canonical response shapes.
        """

        usage = read_object_field(
            response,
            "usage",
            "token_usage",
            default=None,
        )

        source = usage if usage is not None else response

        input_tokens = safe_int(
            read_object_field(
                source,
                "input_tokens",
                "prompt_tokens",
                default=0,
            )
        )
        output_tokens = safe_int(
            read_object_field(
                source,
                "output_tokens",
                "completion_tokens",
                default=0,
            )
        )
        total_tokens = safe_int(
            read_object_field(
                source,
                "total_tokens",
                "tokens",
                default=input_tokens + output_tokens,
            )
        )

        if total_tokens <= 0:
            total_tokens = input_tokens + output_tokens

        return input_tokens, output_tokens, total_tokens

    def _request_id(self, request: RequestT) -> str:
        request_id = read_object_field(
            request,
            "request_id",
            "id",
            default=None,
        )

        if request_id:
            return str(request_id)

        timestamp = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
        suffix = random.randint(100000, 999999)
        return f"ai_request_{timestamp}_{suffix}"

    def _request_model(self, request: RequestT) -> str | None:
        model = read_object_field(
            request,
            "model",
            "model_name",
            default=self.default_model,
        )

        return str(model) if model else None

    def _normalize_exception(
        self,
        error: BaseException,
        *,
        request_id: str,
    ) -> AIProviderError:
        if isinstance(error, AIProviderError):
            if error.provider is None:
                error.provider = self.name

            if error.request_id is None:
                error.request_id = request_id

            return error

        if isinstance(error, TimeoutError):
            return ProviderTimeoutError(
                "Provider request timed out",
                provider=self.name,
                request_id=request_id,
                cause=error,
            )

        if isinstance(error, ConnectionError):
            return ProviderConnectionError(
                f"Provider connection failed: {error}",
                provider=self.name,
                request_id=request_id,
                cause=error,
            )

        return AIProviderError(
            f"Unexpected provider error: {error}",
            provider=self.name,
            request_id=request_id,
            retryable=self.retry_policy.retry_unknown_errors,
            cause=error,
        )

    def _should_retry(
        self,
        error: AIProviderError,
        attempt: int,
    ) -> bool:
        if attempt >= self.retry_policy.max_attempts:
            return False

        return bool(error.retryable)

    def _execute_with_timeout(
        self,
        request: RequestT,
        context: ProviderExecutionContext,
    ) -> ResponseT:
        """
        Execute one synchronous attempt with timeout enforcement.

        A daemon thread is used so a blocked third-party SDK call cannot prevent
        application shutdown.
        """

        result_holder: list[ResponseT] = []
        error_holder: list[BaseException] = []
        completed = threading.Event()

        def runner() -> None:
            try:
                result_holder.append(
                    self._generate_once(request, context)
                )
            except BaseException as error:
                error_holder.append(error)
            finally:
                completed.set()

        worker = threading.Thread(
            target=runner,
            name=f"ai-provider-{self.name}",
            daemon=True,
        )
        worker.start()

        if not completed.wait(timeout=self.timeout_seconds):
            raise ProviderTimeoutError(
                (
                    "Provider request exceeded timeout of "
                    f"{self.timeout_seconds:.2f} seconds"
                ),
                provider=self.name,
                request_id=context.request_id,
            )

        if error_holder:
            raise error_holder[0]

        if not result_holder:
            raise ProviderResponseError(
                "Provider completed without returning a response",
                provider=self.name,
                request_id=context.request_id,
            )

        return result_holder[0]

    async def _execute_with_timeout_async(
        self,
        request: RequestT,
        context: ProviderExecutionContext,
    ) -> ResponseT:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                return await self._generate_once_async(
                    request,
                    context,
                )
        except TimeoutError as error:
            raise ProviderTimeoutError(
                (
                    "Provider request exceeded timeout of "
                    f"{self.timeout_seconds:.2f} seconds"
                ),
                provider=self.name,
                request_id=context.request_id,
                cause=error,
            ) from error

    def _record_request_started(self) -> None:
        with self._metrics_lock:
            self._metrics.total_requests += 1
            self._metrics.last_request_at = utc_now_iso()

    def _record_rate_limit_wait(self, waited_seconds: float) -> None:
        if waited_seconds <= 0.001:
            return

        with self._metrics_lock:
            self._metrics.rate_limit_waits += 1

    def _record_retry(self) -> None:
        with self._metrics_lock:
            self._metrics.retried_requests += 1

    def _record_success(
        self,
        response: ResponseT,
        latency_seconds: float,
    ) -> None:
        input_tokens, output_tokens, total_tokens = self.extract_usage(
            response
        )

        with self._metrics_lock:
            self._metrics.successful_requests += 1
            self._metrics.total_latency_seconds += latency_seconds
            self._metrics.last_latency_seconds = latency_seconds
            self._metrics.total_input_tokens += input_tokens
            self._metrics.total_output_tokens += output_tokens
            self._metrics.total_tokens += total_tokens
            self._metrics.last_success_at = utc_now_iso()
            self._metrics.last_error = None

        self._consecutive_failures = 0
        self._health_status = ProviderOperationalStatus.HEALTHY

    def _record_failure(
        self,
        error: AIProviderError,
        latency_seconds: float,
    ) -> None:
        with self._metrics_lock:
            self._metrics.failed_requests += 1
            self._metrics.total_latency_seconds += latency_seconds
            self._metrics.last_latency_seconds = latency_seconds
            self._metrics.last_failure_at = utc_now_iso()
            self._metrics.last_error = str(error)

            if isinstance(error, ProviderTimeoutError):
                self._metrics.timeout_failures += 1

        self._consecutive_failures += 1

        if self._consecutive_failures >= 3:
            self._health_status = ProviderOperationalStatus.UNAVAILABLE
        else:
            self._health_status = ProviderOperationalStatus.DEGRADED

    def generate(self, request: RequestT) -> ResponseT:
        """
        Generate one AI response synchronously.

        This method owns configuration validation, request validation, rate
        limiting, timeout handling, retries, lifecycle hooks, metrics, and
        health-state updates.
        """

        self.validate_configuration()
        self.validate_request(request)

        request_id = self._request_id(request)
        context = ProviderExecutionContext(
            provider=self.name,
            request_id=request_id,
            model=self._request_model(request),
            started_at=utc_now_iso(),
            maximum_attempts=self.retry_policy.max_attempts,
        )

        self._record_request_started()
        operation_started = time.monotonic()

        self.before_request(request, context)

        final_error: AIProviderError | None = None

        for attempt in range(1, self.retry_policy.max_attempts + 1):
            context.attempt = attempt

            waited = self._rate_limiter.acquire()
            self._record_rate_limit_wait(waited)

            try:
                self.before_attempt(request, context)

                response = self._execute_with_timeout(
                    request,
                    context,
                )
                self.validate_response(response, request)

                latency = time.monotonic() - operation_started
                self._record_success(response, latency)
                self.after_success(request, response, context)

                self.logger.debug(
                    "AI request completed",
                    extra={
                        "provider": self.name,
                        "request_id": request_id,
                        "model": context.model,
                        "attempt": attempt,
                        "latency_seconds": latency,
                    },
                )

                return response

            except BaseException as raw_error:
                error = self._normalize_exception(
                    raw_error,
                    request_id=request_id,
                )
                final_error = error

                if not self._should_retry(error, attempt):
                    break

                self._record_retry()

                delay = self.retry_policy.delay_for_attempt(attempt)

                self.logger.warning(
                    "AI provider request failed; retrying",
                    extra={
                        "provider": self.name,
                        "request_id": request_id,
                        "attempt": attempt,
                        "maximum_attempts": (
                            self.retry_policy.max_attempts
                        ),
                        "retry_delay_seconds": delay,
                        "error": str(error),
                    },
                )

                if delay > 0:
                    time.sleep(delay)

        if final_error is None:
            final_error = AIProviderError(
                "Provider execution failed without an exception",
                provider=self.name,
                request_id=request_id,
            )

        latency = time.monotonic() - operation_started
        self._record_failure(final_error, latency)
        self.after_failure(request, final_error, context)

        self.logger.error(
            "AI provider request failed",
            extra={
                "provider": self.name,
                "request_id": request_id,
                "model": context.model,
                "attempts": context.attempt,
                "latency_seconds": latency,
                "error": str(final_error),
            },
        )

        raise final_error

    async def generate_async(
        self,
        request: RequestT,
    ) -> ResponseT:
        """Generate one AI response asynchronously."""

        self.validate_configuration()
        self.validate_request(request)

        request_id = self._request_id(request)
        context = ProviderExecutionContext(
            provider=self.name,
            request_id=request_id,
            model=self._request_model(request),
            started_at=utc_now_iso(),
            maximum_attempts=self.retry_policy.max_attempts,
        )

        self._record_request_started()
        operation_started = time.monotonic()

        self.before_request(request, context)

        final_error: AIProviderError | None = None

        for attempt in range(1, self.retry_policy.max_attempts + 1):
            context.attempt = attempt

            waited = await self._rate_limiter.acquire_async()
            self._record_rate_limit_wait(waited)

            try:
                self.before_attempt(request, context)

                response = await self._execute_with_timeout_async(
                    request,
                    context,
                )
                self.validate_response(response, request)

                latency = time.monotonic() - operation_started
                self._record_success(response, latency)
                self.after_success(request, response, context)

                return response

            except BaseException as raw_error:
                error = self._normalize_exception(
                    raw_error,
                    request_id=request_id,
                )
                final_error = error

                if not self._should_retry(error, attempt):
                    break

                self._record_retry()
                delay = self.retry_policy.delay_for_attempt(attempt)

                if delay > 0:
                    await asyncio.sleep(delay)

        if final_error is None:
            final_error = AIProviderError(
                "Provider execution failed without an exception",
                provider=self.name,
                request_id=request_id,
            )

        latency = time.monotonic() - operation_started
        self._record_failure(final_error, latency)
        self.after_failure(request, final_error, context)

        raise final_error

    def generate_batch(
        self,
        requests: Sequence[RequestT],
        *,
        stop_on_error: bool = False,
    ) -> list[ResponseT | AIProviderError]:
        """
        Generate responses for a sequence of requests.

        When ``stop_on_error`` is false, failures are returned in their
        corresponding output positions.
        """

        results: list[ResponseT | AIProviderError] = []

        for request in requests:
            try:
                results.append(self.generate(request))
            except AIProviderError as error:
                if stop_on_error:
                    raise
                results.append(error)

        return results

    async def generate_batch_async(
        self,
        requests: Sequence[RequestT],
        *,
        maximum_concurrency: int = 4,
        stop_on_error: bool = False,
    ) -> list[ResponseT | AIProviderError]:
        """Generate a request batch with bounded asynchronous concurrency."""

        if maximum_concurrency < 1:
            raise ValueError(
                "maximum_concurrency must be at least 1"
            )

        semaphore = asyncio.Semaphore(maximum_concurrency)

        async def run_one(
            request: RequestT,
        ) -> ResponseT | AIProviderError:
            async with semaphore:
                try:
                    return await self.generate_async(request)
                except AIProviderError as error:
                    if stop_on_error:
                        raise
                    return error

        return list(
            await asyncio.gather(
                *(run_one(request) for request in requests)
            )
        )

    def stream(self, request: RequestT) -> Any:
        """
        Return a streaming provider result.

        Providers advertising streaming support should override this method.
        """

        del request

        raise ProviderConfigurationError(
            f"Provider '{self.name}' does not implement streaming",
            provider=self.name,
        )

    def _perform_health_check(self) -> tuple[bool, str, dict[str, Any]]:
        """
        Perform the provider-specific health probe.

        Subclasses may override this method. The default implementation
        validates configuration only.
        """

        self.validate_configuration()
        return True, "Provider configuration is valid", {}

    def health_check(self) -> ProviderHealth:
        """Run and record a provider health check."""

        started = time.monotonic()

        if not self.enabled:
            health = ProviderHealth(
                provider=self.name,
                status=ProviderOperationalStatus.DISABLED,
                checked_at=utc_now_iso(),
                message="Provider is disabled",
                latency_seconds=0.0,
                model=self.default_model,
                consecutive_failures=self._consecutive_failures,
            )
            self._health_status = health.status
            self._last_health = health
            return health

        try:
            healthy, message, details = self._perform_health_check()
            latency = time.monotonic() - started

            status = (
                ProviderOperationalStatus.HEALTHY
                if healthy
                else ProviderOperationalStatus.DEGRADED
            )

            if healthy:
                self._consecutive_failures = 0
            else:
                self._consecutive_failures += 1

            health = ProviderHealth(
                provider=self.name,
                status=status,
                checked_at=utc_now_iso(),
                message=message,
                latency_seconds=latency,
                model=self.default_model,
                consecutive_failures=self._consecutive_failures,
                details=dict(details),
            )

        except BaseException as raw_error:
            latency = time.monotonic() - started
            error = self._normalize_exception(
                raw_error,
                request_id="health-check",
            )
            self._consecutive_failures += 1

            health = ProviderHealth(
                provider=self.name,
                status=ProviderOperationalStatus.UNAVAILABLE,
                checked_at=utc_now_iso(),
                message=str(error),
                latency_seconds=latency,
                model=self.default_model,
                consecutive_failures=self._consecutive_failures,
                details={
                    "error_type": type(error).__name__,
                    "retryable": error.retryable,
                },
            )

        self._health_status = health.status
        self._last_health = health
        return health

    def describe(self) -> dict[str, Any]:
        """Return a serializable provider description."""

        metrics = self.get_metrics()

        return {
            "name": self.name,
            "display_name": self.display_name,
            "version": self.metadata.version,
            "provider_type": self.metadata.provider_type,
            "enabled": self.enabled,
            "status": self.status.value,
            "default_model": self.default_model,
            "timeout_seconds": self.timeout_seconds,
            "capabilities": sorted(
                capability.value
                for capability in self.metadata.capabilities
            ),
            "retry_policy": asdict(self.retry_policy),
            "rate_limit_policy": asdict(self.rate_limit_policy),
            "metrics": asdict(metrics),
        }

    def close(self) -> None:
        """Release provider resources."""

    def __enter__(self) -> BaseAIProvider[RequestT, ResponseT]:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: Any,
    ) -> None:
        del exception_type, exception, traceback
        self.close()

    async def __aenter__(
        self,
    ) -> BaseAIProvider[RequestT, ResponseT]:
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: Any,
    ) -> None:
        del exception_type, exception, traceback

        result = self.close()
        if inspect.isawaitable(result):
            await result


@dataclass(frozen=True, slots=True)
class _SelfTestRequest:
    request_id: str
    task: str
    prompt: str
    model: str


@dataclass(frozen=True, slots=True)
class _SelfTestUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass(frozen=True, slots=True)
class _SelfTestResponse:
    status: str
    text: str
    provider: str
    model: str
    usage: _SelfTestUsage


class _SelfTestProvider(
    BaseAIProvider[_SelfTestRequest, _SelfTestResponse]
):
    """Deterministic provider used by the executable module self-test."""

    def __init__(self) -> None:
        super().__init__(
            ProviderMetadata(
                name="self-test",
                display_name="Self-Test Provider",
                version=MODULE_VERSION,
                provider_type="offline",
                default_model="self-test-model-v1",
                capabilities=frozenset(
                    {
                        ProviderCapability.TEXT_GENERATION,
                        ProviderCapability.TRANSLATION,
                        ProviderCapability.OFFLINE,
                    }
                ),
                description="Deterministic provider foundation self-test",
            ),
            timeout_seconds=5.0,
            retry_policy=RetryPolicy(
                max_attempts=2,
                initial_delay_seconds=0.01,
                maximum_delay_seconds=0.01,
                jitter_seconds=0.0,
            ),
            rate_limit_policy=RateLimitPolicy(
                requests_per_window=100,
                window_seconds=1.0,
            ),
        )
        self.execution_count = 0

    def _generate_once(
        self,
        request: _SelfTestRequest,
        context: ProviderExecutionContext,
    ) -> _SelfTestResponse:
        self.execution_count += 1

        if not request.prompt.strip():
            raise ProviderResponseError(
                "Prompt cannot be empty",
                provider=self.name,
                request_id=context.request_id,
            )

        return _SelfTestResponse(
            status="success",
            text=f"Processed: {request.prompt}",
            provider=self.name,
            model=context.model or self.default_model or "unknown",
            usage=_SelfTestUsage(
                input_tokens=5,
                output_tokens=4,
                total_tokens=9,
            ),
        )

    def _perform_health_check(
        self,
    ) -> tuple[bool, str, dict[str, Any]]:
        return (
            True,
            "Deterministic self-test provider is healthy",
            {"mode": "offline"},
        )


def _run_self_test() -> None:
    """Execute deterministic provider foundation validation."""

    provider = _SelfTestProvider()

    request = _SelfTestRequest(
        request_id="provider_base_self_test_0001",
        task="translation",
        prompt="Translate this news headline into Telugu.",
        model="self-test-model-v1",
    )

    response = provider.generate(request)
    health = provider.health_check()
    metrics = provider.get_metrics()
    description = provider.describe()

    assert response.status == "success"
    assert response.provider == "self-test"
    assert response.usage.total_tokens == 9
    assert provider.execution_count == 1

    assert health.healthy
    assert health.provider == "self-test"

    assert metrics.total_requests == 1
    assert metrics.successful_requests == 1
    assert metrics.failed_requests == 0
    assert metrics.total_input_tokens == 5
    assert metrics.total_output_tokens == 4
    assert metrics.total_tokens == 9
    assert metrics.success_rate == 100.0

    assert provider.supports(
        ProviderCapability.TEXT_GENERATION
    )
    assert provider.supports("translation")
    assert not provider.supports("vision")

    assert description["enabled"] is True
    assert description["status"] == "healthy"
    assert description["default_model"] == "self-test-model-v1"

    print(MODULE_NAME)
    print(f"Module version : {MODULE_VERSION}")
    print(f"Provider       : {provider.name}")
    print(f"Display name   : {provider.display_name}")
    print(f"Model          : {provider.default_model}")
    print(f"Capabilities   : {len(provider.metadata.capabilities)}")
    print(f"Request status : {response.status}")
    print(f"Response text  : {response.text}")
    print(f"Tokens         : {response.usage.total_tokens}")
    print(f"Health status  : {health.status.value}")
    print(f"Success rate   : {metrics.success_rate:.2f}%")
    print("AI provider foundation self-test passed.")


if __name__ == "__main__":
    _run_self_test()