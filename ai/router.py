"""
BahuvuNewsAI unified AI provider router.

This module selects the most appropriate AI provider for each request.

Routing decisions may consider:

* Explicit provider preference.
* Task capability requirements.
* Provider enablement.
* Provider operational health.
* Offline-only execution.
* Remote-provider preference.
* Ordered fallback rules.
* Temporary provider failures.
* Provider metrics and routing history.

The router does not perform model-specific generation itself. It delegates to
providers implementing ``BaseAIProvider`` and returns their normalized response.

Typical provider order:

    Gemini -> Offline

The deterministic offline provider ensures that supported pipeline tasks can
continue when Gemini credentials, connectivity, quota, or service availability
prevent remote generation.
"""

from __future__ import annotations

import asyncio
import threading

import core.config  # Loads the project .env file.
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from ai.providers.base import (
    AIProviderError,
    BaseAIProvider,
    ProviderCapability,
    ProviderConfigurationError,
    ProviderMetadata,
    ProviderOperationalStatus,
    ProviderUnavailableError,
    read_object_field,
    utc_now_iso,
)
__all__ = [
    "RoutingMode",
    "RoutingFailureReason",
    "RouterConfiguration",
    "ProviderRoute",
    "RoutingAttempt",
    "RoutingResult",
    "AIRouterError",
    "NoProviderAvailableError",
    "AllProvidersFailedError",
    "AIProviderRouter",
    "create_default_router",
]


MODULE_NAME = "BahuvuNewsAI unified AI provider router"
MODULE_VERSION = "1.0.0"


class RoutingMode(str, Enum):
    """Supported provider-routing strategies."""

    AUTOMATIC = "automatic"
    PREFER_REMOTE = "prefer_remote"
    PREFER_OFFLINE = "prefer_offline"
    REMOTE_ONLY = "remote_only"
    OFFLINE_ONLY = "offline_only"
    EXPLICIT = "explicit"


class RoutingFailureReason(str, Enum):
    """Reason a provider could not complete a routed request."""

    DISABLED = "disabled"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    UNHEALTHY = "unhealthy"
    EXCLUDED_BY_MODE = "excluded_by_mode"
    EXPLICIT_PROVIDER_MISMATCH = "explicit_provider_mismatch"
    EXECUTION_FAILED = "execution_failed"
    NOT_REGISTERED = "not_registered"


@dataclass(frozen=True, slots=True)
class RouterConfiguration:
    """AI provider router configuration."""

    mode: RoutingMode = RoutingMode.AUTOMATIC
    default_provider: str | None = "gemini"
    fallback_provider: str | None = "offline"
    allow_fallback: bool = True
    check_health_before_routing: bool = False
    allow_unknown_health: bool = True
    allow_degraded_providers: bool = True
    prefer_healthy_providers: bool = True
    retry_next_provider_on_non_retryable_error: bool = True
    maximum_provider_attempts: int | None = None

    def __post_init__(self) -> None:
        if (
            self.maximum_provider_attempts is not None
            and self.maximum_provider_attempts < 1
        ):
            raise ValueError(
                "maximum_provider_attempts must be at least 1"
            )


@dataclass(frozen=True, slots=True)
class ProviderRoute:
    """One eligible provider candidate in a routing plan."""

    provider_name: str
    provider_type: str
    priority: int
    capability: ProviderCapability
    status: ProviderOperationalStatus
    reason: str


@dataclass(frozen=True, slots=True)
class RoutingAttempt:
    """Recorded execution attempt against one provider."""

    provider_name: str
    started_at: str
    completed_at: str
    success: bool
    error_type: str | None = None
    error_message: str | None = None
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class RoutingResult:
    """Detailed result from a routed AI request."""

    response: Any
    selected_provider: str
    requested_provider: str | None
    capability: ProviderCapability
    mode: RoutingMode
    used_fallback: bool
    attempts: tuple[RoutingAttempt, ...]
    routed_at: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Return whether routing produced a response."""

        return self.response is not None


class AIRouterError(RuntimeError):
    """Base exception for router failures."""


class NoProviderAvailableError(AIRouterError):
    """Raised when no registered provider satisfies routing requirements."""

    def __init__(
        self,
        message: str,
        *,
        capability: ProviderCapability,
        requested_provider: str | None = None,
        exclusions: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.capability = capability
        self.requested_provider = requested_provider
        self.exclusions = dict(exclusions or {})


class AllProvidersFailedError(AIRouterError):
    """Raised when every eligible provider fails execution."""

    def __init__(
        self,
        message: str,
        *,
        capability: ProviderCapability,
        attempts: Sequence[RoutingAttempt],
        last_error: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.capability = capability
        self.attempts = tuple(attempts)
        self.last_error = last_error


def _enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _normalize_provider_name(value: Any) -> str | None:
    if value is None:
        return None

    normalized = str(_enum_value(value)).strip().lower()
    return normalized or None


def _task_name(request: Any) -> str:
    task = read_object_field(
        request,
        "task",
        "task_type",
        "operation",
        "purpose",
        default="text_generation",
    )

    return str(_enum_value(task)).strip().lower() or "text_generation"


TASK_CAPABILITY_MAP: Mapping[str, ProviderCapability] = {
    "text_generation": ProviderCapability.TEXT_GENERATION,
    "generation": ProviderCapability.TEXT_GENERATION,
    "generate": ProviderCapability.TEXT_GENERATION,
    "translation": ProviderCapability.TRANSLATION,
    "translate": ProviderCapability.TRANSLATION,
    "summarization": ProviderCapability.SUMMARIZATION,
    "summary": ProviderCapability.SUMMARIZATION,
    "summarize": ProviderCapability.SUMMARIZATION,
    "classification": ProviderCapability.CLASSIFICATION,
    "classify": ProviderCapability.CLASSIFICATION,
    "editorial_polishing": ProviderCapability.EDITORIAL_POLISHING,
    "editorial": ProviderCapability.EDITORIAL_POLISHING,
    "polish": ProviderCapability.EDITORIAL_POLISHING,
    "script_generation": ProviderCapability.SCRIPT_GENERATION,
    "script": ProviderCapability.SCRIPT_GENERATION,
    "structured_output": ProviderCapability.STRUCTURED_OUTPUT,
    "json": ProviderCapability.STRUCTURED_OUTPUT,
    "vision": ProviderCapability.VISION,
    "embeddings": ProviderCapability.EMBEDDINGS,
    "tool_calling": ProviderCapability.TOOL_CALLING,
}


class AIProviderRouter:
    """
    Thread-safe registry and routing engine for AI providers.

    Providers are maintained in insertion order. Explicit configuration and
    routing mode are then used to build an ordered candidate plan.
    """

    def __init__(
        self,
        providers: Iterable[BaseAIProvider[Any, Any]] | None = None,
        *,
        configuration: RouterConfiguration | None = None,
    ) -> None:
        self.configuration = configuration or RouterConfiguration()
        self._providers: dict[str, BaseAIProvider[Any, Any]] = {}
        self._lock = threading.RLock()
        self._routing_count = 0
        self._fallback_count = 0
        self._failure_count = 0
        self._last_result: RoutingResult | None = None

        for provider in providers or ():
            self.register(provider)

    @property
    def last_result(self) -> RoutingResult | None:
        """Return the most recent successful routing result."""

        with self._lock:
            return self._last_result

    def register(
        self,
        provider: BaseAIProvider[Any, Any],
        *,
        replace: bool = False,
    ) -> None:
        """Register an AI provider."""

        if provider is None:
            raise ValueError("provider cannot be None")

        name = _normalize_provider_name(provider.name)

        if not name:
            raise ValueError("provider name cannot be empty")

        with self._lock:
            if name in self._providers and not replace:
                raise ValueError(
                    f"Provider '{name}' is already registered"
                )

            self._providers[name] = provider

    def unregister(
        self,
        provider_name: str,
    ) -> BaseAIProvider[Any, Any] | None:
        """Remove and return a registered provider."""

        normalized = _normalize_provider_name(provider_name)

        if not normalized:
            return None

        with self._lock:
            return self._providers.pop(normalized, None)

    def get_provider(
        self,
        provider_name: str,
    ) -> BaseAIProvider[Any, Any] | None:
        """Return a registered provider by name."""

        normalized = _normalize_provider_name(provider_name)

        if not normalized:
            return None

        with self._lock:
            return self._providers.get(normalized)

    def providers(self) -> tuple[BaseAIProvider[Any, Any], ...]:
        """Return registered providers in registry order."""

        with self._lock:
            return tuple(self._providers.values())

    def provider_names(self) -> tuple[str, ...]:
        """Return registered provider names."""

        with self._lock:
            return tuple(self._providers.keys())

    def required_capability(
        self,
        request: Any,
    ) -> ProviderCapability:
        """Resolve the provider capability required by a request."""

        explicit = read_object_field(
            request,
            "capability",
            "required_capability",
            default=None,
        )

        if explicit is not None:
            if isinstance(explicit, ProviderCapability):
                return explicit

            try:
                return ProviderCapability(str(_enum_value(explicit)))
            except ValueError as error:
                raise ProviderConfigurationError(
                    f"Unsupported AI capability: {explicit}"
                ) from error

        task = _task_name(request)

        return TASK_CAPABILITY_MAP.get(
            task,
            ProviderCapability.TEXT_GENERATION,
        )

    def requested_provider(
        self,
        request: Any,
    ) -> str | None:
        """Extract explicit provider preference from a request."""

        value = read_object_field(
            request,
            "provider",
            "provider_name",
            "preferred_provider",
            default=None,
        )

        return _normalize_provider_name(value)

    def routing_mode(
        self,
        request: Any,
    ) -> RoutingMode:
        """Resolve request-specific or configured routing mode."""

        value = read_object_field(
            request,
            "routing_mode",
            "provider_mode",
            default=None,
        )

        if value is None:
            return self.configuration.mode

        if isinstance(value, RoutingMode):
            return value

        try:
            return RoutingMode(str(_enum_value(value)).lower())
        except ValueError as error:
            raise ProviderConfigurationError(
                f"Unsupported routing mode: {value}"
            ) from error

    def _provider_type(
        self,
        provider: BaseAIProvider[Any, Any],
    ) -> str:
        return str(provider.metadata.provider_type).strip().lower()

    def _is_offline(
        self,
        provider: BaseAIProvider[Any, Any],
    ) -> bool:
        return (
            self._provider_type(provider) == "offline"
            or provider.supports(ProviderCapability.OFFLINE)
        )

    def _provider_status(
        self,
        provider: BaseAIProvider[Any, Any],
    ) -> ProviderOperationalStatus:
        if self.configuration.check_health_before_routing:
            return provider.health_check().status

        return provider.status

    def _status_allowed(
        self,
        status: ProviderOperationalStatus,
    ) -> bool:
        if status is ProviderOperationalStatus.HEALTHY:
            return True

        if status is ProviderOperationalStatus.UNKNOWN:
            return self.configuration.allow_unknown_health

        if status is ProviderOperationalStatus.DEGRADED:
            return self.configuration.allow_degraded_providers

        return False

    def _mode_allows(
        self,
        provider: BaseAIProvider[Any, Any],
        mode: RoutingMode,
    ) -> bool:
        offline = self._is_offline(provider)

        if mode is RoutingMode.OFFLINE_ONLY:
            return offline

        if mode is RoutingMode.REMOTE_ONLY:
            return not offline

        return True

    def _priority_names(
        self,
        *,
        mode: RoutingMode,
        requested_provider: str | None,
    ) -> list[str]:
        registered = list(self.provider_names())
        ordered: list[str] = []

        def append_name(name: str | None) -> None:
            normalized = _normalize_provider_name(name)

            if (
                normalized
                and normalized in registered
                and normalized not in ordered
            ):
                ordered.append(normalized)

        if requested_provider:
            append_name(requested_provider)

        if mode is RoutingMode.EXPLICIT:
            return ordered

        if mode is RoutingMode.PREFER_OFFLINE:
            for name in registered:
                provider = self.get_provider(name)
                if provider is not None and self._is_offline(provider):
                    append_name(name)

            append_name(self.configuration.default_provider)

            for name in registered:
                append_name(name)

        elif mode in {
            RoutingMode.PREFER_REMOTE,
            RoutingMode.AUTOMATIC,
            RoutingMode.REMOTE_ONLY,
        }:
            append_name(self.configuration.default_provider)

            for name in registered:
                provider = self.get_provider(name)
                if provider is not None and not self._is_offline(provider):
                    append_name(name)

            append_name(self.configuration.fallback_provider)

            for name in registered:
                append_name(name)

        elif mode is RoutingMode.OFFLINE_ONLY:
            append_name(self.configuration.fallback_provider)

            for name in registered:
                provider = self.get_provider(name)
                if provider is not None and self._is_offline(provider):
                    append_name(name)

        else:
            for name in registered:
                append_name(name)

        return ordered

    def build_route(
        self,
        request: Any,
    ) -> tuple[ProviderRoute, ...]:
        """Build an ordered eligible-provider route for a request."""

        capability = self.required_capability(request)
        requested = self.requested_provider(request)
        mode = self.routing_mode(request)
        exclusions: dict[str, str] = {}
        routes: list[ProviderRoute] = []

        if requested and self.get_provider(requested) is None:
            exclusions[requested] = (
                RoutingFailureReason.NOT_REGISTERED.value
            )

            if mode is RoutingMode.EXPLICIT:
                raise NoProviderAvailableError(
                    f"Requested provider '{requested}' is not registered",
                    capability=capability,
                    requested_provider=requested,
                    exclusions=exclusions,
                )

        ordered_names = self._priority_names(
            mode=mode,
            requested_provider=requested,
        )

        for position, provider_name in enumerate(
            ordered_names,
            start=1,
        ):
            provider = self.get_provider(provider_name)

            if provider is None:
                exclusions[provider_name] = (
                    RoutingFailureReason.NOT_REGISTERED.value
                )
                continue

            if not provider.enabled:
                exclusions[provider_name] = (
                    RoutingFailureReason.DISABLED.value
                )
                continue

            if not provider.supports(capability):
                exclusions[provider_name] = (
                    RoutingFailureReason.UNSUPPORTED_CAPABILITY.value
                )
                continue

            if not self._mode_allows(provider, mode):
                exclusions[provider_name] = (
                    RoutingFailureReason.EXCLUDED_BY_MODE.value
                )
                continue

            if (
                mode is RoutingMode.EXPLICIT
                and requested
                and provider_name != requested
            ):
                exclusions[provider_name] = (
                    RoutingFailureReason.EXPLICIT_PROVIDER_MISMATCH.value
                )
                continue

            status = self._provider_status(provider)

            if not self._status_allowed(status):
                exclusions[provider_name] = (
                    RoutingFailureReason.UNHEALTHY.value
                )
                continue

            reason = "eligible"

            if requested and provider_name == requested:
                reason = "explicit provider preference"
            elif (
                self.configuration.default_provider
                and provider_name
                == _normalize_provider_name(
                    self.configuration.default_provider
                )
            ):
                reason = "configured default provider"
            elif self._is_offline(provider):
                reason = "offline fallback provider"
            else:
                reason = "eligible registered provider"

            routes.append(
                ProviderRoute(
                    provider_name=provider_name,
                    provider_type=self._provider_type(provider),
                    priority=position,
                    capability=capability,
                    status=status,
                    reason=reason,
                )
            )

        if self.configuration.prefer_healthy_providers:
            routes.sort(
                key=lambda route: (
                    0
                    if route.status
                    is ProviderOperationalStatus.HEALTHY
                    else 1,
                    route.priority,
                )
            )

        maximum = self.configuration.maximum_provider_attempts

        if maximum is not None:
            routes = routes[:maximum]

        if not routes:
            raise NoProviderAvailableError(
                (
                    "No registered AI provider can satisfy capability "
                    f"'{capability.value}'"
                ),
                capability=capability,
                requested_provider=requested,
                exclusions=exclusions,
            )

        return tuple(routes)

    def _can_fallback_after_error(
        self,
        error: AIProviderError,
        *,
        route_index: int,
        route_count: int,
        mode: RoutingMode,
    ) -> bool:
        if route_index >= route_count - 1:
            return False

        if not self.configuration.allow_fallback:
            return False

        if mode in {
            RoutingMode.EXPLICIT,
            RoutingMode.REMOTE_ONLY,
            RoutingMode.OFFLINE_ONLY,
        }:
            return False

        if error.retryable:
            return True

        return self.configuration.retry_next_provider_on_non_retryable_error

    def route_with_details(
        self,
        request: Any,
    ) -> RoutingResult:
        """Route and execute a request, returning routing diagnostics."""

        routes = self.build_route(request)
        capability = self.required_capability(request)
        requested = self.requested_provider(request)
        mode = self.routing_mode(request)
        attempts: list[RoutingAttempt] = []
        last_error: BaseException | None = None

        for index, route in enumerate(routes):
            provider = self.get_provider(route.provider_name)

            if provider is None:
                continue

            started_at = utc_now_iso()

            try:
                response = provider.generate(request)
                completed_at = utc_now_iso()

                attempts.append(
                    RoutingAttempt(
                        provider_name=provider.name,
                        started_at=started_at,
                        completed_at=completed_at,
                        success=True,
                    )
                )

                used_fallback = index > 0

                result = RoutingResult(
                    response=response,
                    selected_provider=provider.name,
                    requested_provider=requested,
                    capability=capability,
                    mode=mode,
                    used_fallback=used_fallback,
                    attempts=tuple(attempts),
                    routed_at=completed_at,
                    metadata={
                        "route_length": len(routes),
                        "selected_route_index": index,
                        "provider_type": (
                            provider.metadata.provider_type
                        ),
                    },
                )

                with self._lock:
                    self._routing_count += 1

                    if used_fallback:
                        self._fallback_count += 1

                    self._last_result = result

                return result

            except AIProviderError as error:
                completed_at = utc_now_iso()
                last_error = error

                attempts.append(
                    RoutingAttempt(
                        provider_name=provider.name,
                        started_at=started_at,
                        completed_at=completed_at,
                        success=False,
                        error_type=type(error).__name__,
                        error_message=str(error),
                        retryable=bool(error.retryable),
                    )
                )

                if not self._can_fallback_after_error(
                    error,
                    route_index=index,
                    route_count=len(routes),
                    mode=mode,
                ):
                    break

            except Exception as error:
                completed_at = utc_now_iso()
                last_error = error

                attempts.append(
                    RoutingAttempt(
                        provider_name=provider.name,
                        started_at=started_at,
                        completed_at=completed_at,
                        success=False,
                        error_type=type(error).__name__,
                        error_message=str(error),
                        retryable=False,
                    )
                )

                if (
                    not self.configuration.allow_fallback
                    or index >= len(routes) - 1
                    or mode
                    in {
                        RoutingMode.EXPLICIT,
                        RoutingMode.REMOTE_ONLY,
                        RoutingMode.OFFLINE_ONLY,
                    }
                ):
                    break

        with self._lock:
            self._routing_count += 1
            self._failure_count += 1

        raise AllProvidersFailedError(
            (
                "All eligible AI providers failed for capability "
                f"'{capability.value}'"
            ),
            capability=capability,
            attempts=attempts,
            last_error=last_error,
        )

    def route(self, request: Any) -> Any:
        """Route a request and return only the provider response."""

        return self.route_with_details(request).response

    async def route_with_details_async(
        self,
        request: Any,
    ) -> RoutingResult:
        """Asynchronously route and execute a request."""

        routes = self.build_route(request)
        capability = self.required_capability(request)
        requested = self.requested_provider(request)
        mode = self.routing_mode(request)
        attempts: list[RoutingAttempt] = []
        last_error: BaseException | None = None

        for index, route in enumerate(routes):
            provider = self.get_provider(route.provider_name)

            if provider is None:
                continue

            started_at = utc_now_iso()

            try:
                response = await provider.generate_async(request)
                completed_at = utc_now_iso()

                attempts.append(
                    RoutingAttempt(
                        provider_name=provider.name,
                        started_at=started_at,
                        completed_at=completed_at,
                        success=True,
                    )
                )

                used_fallback = index > 0

                result = RoutingResult(
                    response=response,
                    selected_provider=provider.name,
                    requested_provider=requested,
                    capability=capability,
                    mode=mode,
                    used_fallback=used_fallback,
                    attempts=tuple(attempts),
                    routed_at=completed_at,
                    metadata={
                        "route_length": len(routes),
                        "selected_route_index": index,
                        "provider_type": (
                            provider.metadata.provider_type
                        ),
                    },
                )

                with self._lock:
                    self._routing_count += 1

                    if used_fallback:
                        self._fallback_count += 1

                    self._last_result = result

                return result

            except AIProviderError as error:
                completed_at = utc_now_iso()
                last_error = error

                attempts.append(
                    RoutingAttempt(
                        provider_name=provider.name,
                        started_at=started_at,
                        completed_at=completed_at,
                        success=False,
                        error_type=type(error).__name__,
                        error_message=str(error),
                        retryable=bool(error.retryable),
                    )
                )

                if not self._can_fallback_after_error(
                    error,
                    route_index=index,
                    route_count=len(routes),
                    mode=mode,
                ):
                    break

            except Exception as error:
                completed_at = utc_now_iso()
                last_error = error

                attempts.append(
                    RoutingAttempt(
                        provider_name=provider.name,
                        started_at=started_at,
                        completed_at=completed_at,
                        success=False,
                        error_type=type(error).__name__,
                        error_message=str(error),
                        retryable=False,
                    )
                )

                if (
                    not self.configuration.allow_fallback
                    or index >= len(routes) - 1
                    or mode
                    in {
                        RoutingMode.EXPLICIT,
                        RoutingMode.REMOTE_ONLY,
                        RoutingMode.OFFLINE_ONLY,
                    }
                ):
                    break

        with self._lock:
            self._routing_count += 1
            self._failure_count += 1

        raise AllProvidersFailedError(
            (
                "All eligible AI providers failed for capability "
                f"'{capability.value}'"
            ),
            capability=capability,
            attempts=attempts,
            last_error=last_error,
        )

    async def route_async(self, request: Any) -> Any:
        """Asynchronously route and return only the response."""

        result = await self.route_with_details_async(request)
        return result.response

    def route_batch(
        self,
        requests: Sequence[Any],
        *,
        stop_on_error: bool = False,
    ) -> list[Any | AIRouterError]:
        """Route a sequence of requests synchronously."""

        results: list[Any | AIRouterError] = []

        for request in requests:
            try:
                results.append(self.route(request))
            except AIRouterError as error:
                if stop_on_error:
                    raise
                results.append(error)

        return results

    async def route_batch_async(
        self,
        requests: Sequence[Any],
        *,
        maximum_concurrency: int = 4,
        stop_on_error: bool = False,
    ) -> list[Any | AIRouterError]:
        """Route requests concurrently with bounded concurrency."""

        if maximum_concurrency < 1:
            raise ValueError(
                "maximum_concurrency must be at least 1"
            )

        semaphore = asyncio.Semaphore(maximum_concurrency)

        async def execute(request: Any) -> Any | AIRouterError:
            async with semaphore:
                try:
                    return await self.route_async(request)
                except AIRouterError as error:
                    if stop_on_error:
                        raise
                    return error

        return list(
            await asyncio.gather(
                *(execute(request) for request in requests)
            )
        )

    def health_report(self) -> dict[str, Any]:
        """Run health checks for all registered providers."""

        report: dict[str, Any] = {}

        for provider in self.providers():
            health = provider.health_check()
            report[provider.name] = {
                "status": health.status.value,
                "healthy": health.healthy,
                "message": health.message,
                "latency_seconds": health.latency_seconds,
                "model": health.model,
                "consecutive_failures": (
                    health.consecutive_failures
                ),
                "details": dict(health.details),
            }

        return report

    def metrics(self) -> dict[str, Any]:
        """Return routing and provider metrics."""

        with self._lock:
            routing_metrics = {
                "total_routes": self._routing_count,
                "fallback_routes": self._fallback_count,
                "failed_routes": self._failure_count,
                "fallback_rate": (
                    (
                        self._fallback_count
                        / self._routing_count
                        * 100.0
                    )
                    if self._routing_count
                    else 0.0
                ),
            }

        provider_metrics = {
            provider.name: asdict(provider.get_metrics())
            for provider in self.providers()
        }

        return {
            "router": routing_metrics,
            "providers": provider_metrics,
        }

    def describe(self) -> dict[str, Any]:
        """Return a serializable router description."""

        return {
            "module_version": MODULE_VERSION,
            "configuration": {
                **asdict(self.configuration),
                "mode": self.configuration.mode.value,
            },
            "providers": [
                provider.describe()
                for provider in self.providers()
            ],
            "metrics": self.metrics(),
        }

    def close(self) -> None:
        """Close all registered provider resources."""

        for provider in self.providers():
            provider.close()

    def __enter__(self) -> AIProviderRouter:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: Any,
    ) -> None:
        del exception_type, exception, traceback
        self.close()


def create_default_router(
    *,
    include_gemini: bool = True,
    include_offline: bool = True,
    configuration: RouterConfiguration | None = None,
) -> AIProviderRouter:
    """
    Create the standard BahuvuNewsAI provider router.

    Gemini initialization is lazy. Missing credentials do not prevent router
    construction; Gemini will simply be excluded or fail over when generation
    is attempted.
    """

    providers: list[BaseAIProvider[Any, Any]] = []

    if include_gemini:
        try:
            from ai.providers.gemini import create_gemini_provider

            providers.append(create_gemini_provider())

        except Exception:
            import traceback

            print("=" * 70)
            print("FAILED TO REGISTER GEMINI PROVIDER")
            traceback.print_exc()
            print("=" * 70)

            raise

    if include_offline:
        from ai.providers.offline import create_offline_provider

        providers.append(create_offline_provider())

    return AIProviderRouter(
        providers,
        configuration=configuration,
    )


@dataclass(frozen=True, slots=True)
class _SelfTestRequest:
    request_id: str
    task: str
    prompt: str
    provider: str | None = None
    routing_mode: str | None = None
    target_language: str = "te"


class _FailingRemoteProvider(BaseAIProvider[Any, Any]):
    """Deterministic remote provider used to test fallback."""

    def __init__(self) -> None:
        super().__init__(
            ProviderMetadata(
                name="remote-test",
                display_name="Failing Remote Test Provider",
                version=MODULE_VERSION,
                provider_type="remote",
                default_model="remote-test-v1",
                capabilities=frozenset(
                    {
                        ProviderCapability.TEXT_GENERATION,
                        ProviderCapability.TRANSLATION,
                    }
                ),
            ),
            timeout_seconds=2.0,
        )

    def _generate_once(
        self,
        request: Any,
        context: Any,
    ) -> Any:
        del request

        raise ProviderUnavailableError(
            "Simulated remote provider outage",
            provider=self.name,
            request_id=context.request_id,
        )

    def _perform_health_check(
        self,
    ) -> tuple[bool, str, dict[str, Any]]:
        return True, "Remote test provider is routable", {}


def _run_self_test() -> None:
    """Execute deterministic router validation."""

    from ai.providers.offline import create_offline_provider

    remote = _FailingRemoteProvider()
    offline = create_offline_provider()

    router = AIProviderRouter(
        [remote, offline],
        configuration=RouterConfiguration(
            mode=RoutingMode.AUTOMATIC,
            default_provider="remote-test",
            fallback_provider="offline",
            allow_fallback=True,
            check_health_before_routing=False,
            allow_unknown_health=True,
        ),
    )

    request = _SelfTestRequest(
        request_id="router_self_test_0001",
        task="translation",
        prompt=(
            "Officials issued a warning over continuing heavy rainfall."
        ),
    )

    route = router.build_route(request)
    result = router.route_with_details(request)
    metrics = router.metrics()
    health = router.health_report()

    assert len(route) == 2
    assert route[0].provider_name == "remote-test"
    assert route[1].provider_name == "offline"

    assert result.success
    assert result.selected_provider == "offline"
    assert result.used_fallback is True
    assert len(result.attempts) == 2
    assert result.attempts[0].success is False
    assert result.attempts[1].success is True
    assert "హెచ్చరిక" in result.response.text

    assert metrics["router"]["total_routes"] == 1
    assert metrics["router"]["fallback_routes"] == 1
    assert metrics["router"]["failed_routes"] == 0
    assert metrics["router"]["fallback_rate"] == 100.0

    assert health["remote-test"]["healthy"] is True
    assert health["offline"]["healthy"] is True

    explicit_request = _SelfTestRequest(
        request_id="router_self_test_0002",
        task="summarization",
        prompt=(
            "Heavy rain continued. Officials issued a warning. "
            "Emergency teams were deployed."
        ),
        provider="offline",
        routing_mode="explicit",
    )

    explicit_result = router.route_with_details(
        explicit_request
    )

    assert explicit_result.selected_provider == "offline"
    assert explicit_result.used_fallback is False

    print(MODULE_NAME)
    print(f"Module version  : {MODULE_VERSION}")
    print(f"Providers       : {', '.join(router.provider_names())}")
    print(f"Capability      : {result.capability.value}")
    print(f"Primary provider: {route[0].provider_name}")
    print(f"Selected provider: {result.selected_provider}")
    print(f"Fallback used   : {result.used_fallback}")
    print(f"Attempts        : {len(result.attempts)}")
    print(f"Response status : {result.response.status}")
    print(f"Response text   : {result.response.text}")
    print(
        "Fallback rate   : "
        f"{metrics['router']['fallback_rate']:.2f}%"
    )
    print("AI provider router self-test passed.")


if __name__ == "__main__":
    _run_self_test()